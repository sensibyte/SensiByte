import io
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db.models import Count, IntegerField, Value, Q, F, CharField, Case, When, OuterRef, Exists, QuerySet, \
    Prefetch
from django.db.models import Window
from django.db.models.functions import RowNumber
from django.http import FileResponse
from django.http import JsonResponse
from django.views.generic import FormView
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, A3
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph
from reportlab.platypus import Image
from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak, Table, TableStyle

from Base.global_models import Hospital
from Base.models import (
    Aislado, ResultadoAntibiotico, MecanismoResistenciaHospital,
    Antibiotico, AmbitoHospital, ServicioHospital, PerfilAntibiogramaHospital,
    SexoHospital, CategoriaMuestraHospital, MicroorganismoHospital, SubtipoMecanismoResistenciaHospital,
    AntibioticoHospital, PerfilAntibioticoHospital
)
from .forms import FiltroResistenciaForm, InformePredefinidoResistenciaForm
from .utils import calculate_ic95, build_antibiotics_bar_chart, build_piechart, build_mic_histogram, proportions_test

estilos = getSampleStyleSheet()

class ResultadosResistenciaView(FormView):
    """Vista del explorador de resistencias"""
    template_name = "Informes/explorador.html"
    form_class = FiltroResistenciaForm

    def get_form_kwargs(self):
        """Pasa el hospital actual al formulario para filtrar los queryset."""
        kwargs = super().get_form_kwargs()
        kwargs["hospital"] = self.request.user.hospital
        return kwargs

    def form_invalid(self, form):
        """Para cuando hay errores de validación del formulario, pasa errores personalizados"""
        # Si no es AJAX, añadir mensajes al framework de mensajes de Django
        for field, errors in form.errors.items():
            if field == "__all__": # serían errores generales de formulario, no de campo
                # ref: https://docs.djangoproject.com/en/5.2/ref/forms/validation/#form-and-field-validation
                for error in errors:
                    messages.error(self.request, error)
            else:
                field_label = form.fields[field].label or field
                for error in errors:
                    messages.error(self.request, f"{field_label}: {error}")

        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        user = self.request.user
        hospital = user.hospital

        # Variables del filtro del formulario
        fecha_inicio = form.cleaned_data["fecha_inicio"]
        fecha_fin = form.cleaned_data["fecha_fin"]
        edad_min = form.cleaned_data["edad_min"]
        edad_max = form.cleaned_data["edad_max"]
        sexo = form.cleaned_data["sexo"]
        ambito = form.cleaned_data["ambito"]
        servicio = form.cleaned_data["servicio"]
        categoria_muestra = form.cleaned_data["tipo_muestra"]
        unificar_sei_con_sensibles = form.cleaned_data["unificar_sei_con_sensibles"]
        considerar_variantes = form.cleaned_data["considerar_variantes"]
        microorganismo = form.cleaned_data["microorganismo"]

        # 1. Filtrar solo registros del hospital y microorganismo seleccionados. Excluiye demográficos que deben ser ignorados
        qs = (Aislado.objects.select_related(
            "registro",
            "registro__tipo_muestra__categoria",
            "registro__sexo__sexo",
            "registro__ambito__ambito",
            "registro__servicio__servicio",
            "microorganismo__microorganismo"
        ).prefetch_related(
            "mecanismos_resistencia__mecanismo",
            "subtipos_resistencia__subtipo_mecanismo"
        ).filter(
            registro__hospital=hospital,
            registro__fecha__range=(fecha_inicio, fecha_fin),
            microorganismo=microorganismo,
            registro__sexo__ignorar_informes=False,
            registro__ambito__ignorar_informes=False,
            registro__servicio__ignorar_informes=False,
            registro__tipo_muestra__categoria__ignorar_informes=False
        ))

        # 2. Filtros adicionales por los campos del formulario.
        if edad_min is not None:
            qs = qs.filter(registro__edad__gte=edad_min)
        if edad_max is not None:
            qs = qs.filter(registro__edad__lte=edad_max)
        if sexo:
            qs = qs.filter(registro__sexo__in=sexo)
        if ambito:
            qs = qs.filter(registro__ambito__in=ambito)
        if servicio:
            qs = qs.filter(registro__servicio__in=servicio)
        if categoria_muestra:
            qs = qs.filter(registro__tipo_muestra__categoria__in=categoria_muestra)

        # 3. Selección única por nh_hash: Django Window + RowNumber
        # refs: https://medium.com/@altafkhan_24475/part-2-window-functions-in-django-models-063caae63fd1
        # https://docs.djangoproject.com/en/5.2/ref/models/expressions/
        qs_anotado = qs.annotate(
            row_num=Window(
                expression=RowNumber(),
                partition_by=[F("registro__nh_hash")],
                order_by=F("registro__fecha").asc()  # la primera es la más antigua del grupo
            )
        )
        qs_final = qs_anotado.filter(row_num=1)  # sólo la primera fila, la más antigua, de cada nh_hash

        # 3. Verificar si hay resultados -> Si no hay, mandar el formulario de vuelta y mostrar un mensaje
        if not qs_final.exists():
            messages.info(self.request, "No hay resultados para esta consulta")
            return self.render_to_response(self.get_context_data(form=form, resultados=[]))

        # Guardar en memoria el total de aislados
        total_aislados = qs_final.count()

        # 4. Tabla de antibióticos
        # obtener IDs de antibióticos con resistencia intrínseca para este microorganismo
        resistencias_intrinsecas_ids = microorganismo.microorganismo.lista_ids_resistencia_intrinseca

        # Si se consideran variantes necesitamos también todos los antibióticos padre que NO tiene variantes
        # para construir una columna temporal con annotate que nos diga si el antibiótico tiene o no variantes con
        # la expresión Exists. Ref: https://docs.djangoproject.com/en/5.2/ref/models/expressions/#django.db.models.Exists
        tiene_variantes = Exists(
            Antibiotico.objects.filter(parent=OuterRef("antibiotico__antibiotico"))
        )

        # si se marcó considerar variantes en el formulario, mostramos resultados de variantes
        if considerar_variantes:
            filtro_antibiotico = (Q(antibiotico__antibiotico__es_variante=True) |
                                  Q(antibiotico__antibiotico__es_variante=False, tiene_variantes=False))
        # si no se marcó, solo los que NO son variantes
        else:
            filtro_antibiotico = Q(antibiotico__antibiotico__es_variante=False)

        # añadimos el filtro de visibilidad
        perfil = (
            PerfilAntibiogramaHospital.objects
            .filter(hospital=hospital,
                    grupo_eucast=microorganismo.microorganismo.grupo_eucast)
            .prefetch_related("perfilantibioticohospital_set")
            .first()
        )

        if perfil:
            antibioticos_visibles = (
                PerfilAntibioticoHospital.objects
                .filter(perfil=perfil, mostrar_en_informes=True) # sólo los que están activos para mostrar en informe
                .values_list("antibiotico_hospital", flat=True)
            )
        else:
            antibioticos_visibles = AntibioticoHospital.objects.none()

        filtro_antibiotico &= Q(antibiotico__id__in=antibioticos_visibles)

        resultados_antibio = (
            ResultadoAntibiotico.objects
            .select_related("antibiotico__antibiotico")
            .annotate(tiene_variantes=tiene_variantes)  # añade la columna booleana
            .filter(
                aislado__in=qs_final,
                interpretacion__in=["S", "I", "R"]
            ).filter(filtro_antibiotico)  # filtro variantes y visibilidad
            .exclude(
                antibiotico__antibiotico__id__in=resistencias_intrinsecas_ids  # excluye resistencias intrínsecas
            )
            .values("antibiotico__antibiotico__nombre")  # agregamos conteos
            .annotate(
                total=Count("id"),
                sensibles=Count("id", filter=Q(  # los conteos sensibles dependen de la elección en formulario
                    interpretacion__in=["S", "I"] if unificar_sei_con_sensibles else ["S"])),
                sei=(
                    Count("id", filter=Q(interpretacion="I"))  # los conteos sei dependen de la elección
                    if not unificar_sei_con_sensibles else Value(0, output_field=IntegerField())
                )
            )
            .filter(total__gt=1)  # antibióticos con más de 1 registro
            .order_by("antibiotico__orden_informe",  # orden según prioridad por 'orden_informe'
                      "antibiotico__antibiotico__nombre")
        )

        df_antibio = pd.DataFrame.from_records(list(resultados_antibio))

        # si no hay resultados mandar el mensaje a la UI y devolver el formulario
        if df_antibio.empty:
            messages.info(self.request, "No hay resultados para esta consulta")
            return self.render_to_response(self.get_context_data(form=form, resultados=[]))

        # Creamos las columnas faltantes del DataFrame: resistentes y porcentajes
        df_antibio["resistentes"] = df_antibio["total"] - df_antibio["sensibles"] - df_antibio.get("sei", 0)
        df_antibio["porcentaje_s"] = round((df_antibio["sensibles"] / df_antibio["total"]) * 100, 2)
        df_antibio["porcentaje_i"] = (
            round((df_antibio.get("sei", 0) / df_antibio["total"]) * 100, 2)
            if not unificar_sei_con_sensibles else None
        )
        df_antibio["porcentaje_r"] = (df_antibio["resistentes"] / df_antibio["total"]) * 100

        # 5. Cálculo de resultados
        resultados = self._get_clinical_category_results(df_antibio,
                                                         unificar_sei_con_sensibles=unificar_sei_con_sensibles)

        tabla_resumen = resultados["tabla_resumen"]
        antibioticos = resultados["antibioticos"]
        porcentaje_s = resultados["porcentaje_s"]
        porcentaje_si = resultados["porcentaje_si"]
        porcentaje_i = resultados["porcentaje_i"]
        porcentaje_r = resultados["porcentaje_r"]

        # 6. Cálculo de Mecanismos de resistencia
        # IDs únicos de mecanismos base, excluyendo los que son None
        mecanismos_base_ids = list(
            qs_final
            .values_list("mecanismos_resistencia__mecanismo", flat=True)
            .exclude(mecanismos_resistencia__mecanismo__isnull=True)
            .distinct()
        )

        resumen_mecanismos = self._get_arm_results(qs_final, total_aislados, mecanismos_base_ids, hospital)

        # 7. Gráficos
        graficos = self._get_charts(
            qs_final,
            antibioticos,
            porcentaje_s,
            porcentaje_si,
            porcentaje_i,
            porcentaje_r,
            resistencias_intrinsecas_ids,
            tiene_variantes,
            filtro_antibiotico
        )

        context = self.get_context_data(
            form=form,
            resultados=qs_final,
            tabla=tabla_resumen,
            total=total_aislados,
            unificar_sei_con_sensibles=unificar_sei_con_sensibles,
            resumen_mecanismos=resumen_mecanismos,
            **graficos
        )

        return self.render_to_response(context)

    @staticmethod
    def _get_clinical_category_results(df_antibio: pd.DataFrame,
                                       unificar_sei_con_sensibles: bool) -> dict:
        """Calcula intervalos de confianza y prepara los resultados de un DataFrame de resultados de antibióticos"""

        # Convertimos a vectores numpy
        sensibles = df_antibio["sensibles"].to_numpy()
        sei = df_antibio.get("sei", pd.Series(0, index=df_antibio.index)).to_numpy()
        total = df_antibio["total"].to_numpy()

        # Crea columna de resistentes
        df_antibio["resistentes"] = total - sensibles - sei

        if unificar_sei_con_sensibles:
            # Modo S+I: una sola columna con IC95
            # 'sensibles' ya contiene S+I cuando unificar_sei_con_sensibles=True
            df_antibio["porcentaje_s"] = np.round((sensibles / total) * 100, 2)

            # Calcular IC95 para S+I
            low_s, up_s = calculate_ic95(sensibles, total)
            df_antibio["ic_low"] = np.round(low_s * 100, 2)
            df_antibio["ic_high"] = np.round(up_s * 100, 2)

            # Porcentaje de resistentes
            df_antibio["porcentaje_r"] = np.round((df_antibio["resistentes"] / total) * 100, 2)

            # Extraer listas para gráficos
            antibioticos = df_antibio["antibiotico__antibiotico__nombre"].tolist()
            porcentaje_s = df_antibio["porcentaje_s"].tolist()
            porcentaje_i = [0] * len(df_antibio)  # No se muestra SEI, ya va incluido en S+SEI, pasamos como 0
            porcentaje_si = [0] * len(df_antibio) # Se lo pasamos como 0, pero no se muestra
            porcentaje_r = df_antibio["porcentaje_r"].tolist()

        else:
            # Modo S separado: mostrar S, I y S+I
            # Cuando unificar_sei_con_sensibles=False, 'sensibles' contiene solo S

            # Columna 1: % Sensibilidad (S solo)
            df_antibio["porcentaje_s"] = np.round((sensibles / total) * 100, 2)

            # Columna 2: % SEI
            df_antibio["porcentaje_i"] = np.round((sei / total) * 100, 2)

            # Calcular IC95 para SEI (solo si total >= 30 y hay sei)
            mask_i = (total >= 30) & (sei > 0)
            low_i, up_i = np.full(len(df_antibio), np.nan), np.full(len(df_antibio), np.nan)

            if mask_i.any():
                li, ui = calculate_ic95(sei[mask_i], total[mask_i])
                low_i[mask_i] = li * 100
                up_i[mask_i] = ui * 100

            df_antibio["ic_low_i"] = np.round(low_i, 2)
            df_antibio["ic_high_i"] = np.round(up_i, 2)

            # Columna 3: % S+I con IC95
            s_mas_i = sensibles + sei
            df_antibio["porcentaje_si"] = np.round((s_mas_i / total) * 100, 2)

            # Calcular IC95 para S+I
            low_si, up_si = calculate_ic95(s_mas_i, total)
            df_antibio["ic_low_si"] = np.round(low_si * 100, 2)
            df_antibio["ic_high_si"] = np.round(up_si * 100, 2)

            # Porcentaje de resistentes
            df_antibio["porcentaje_r"] = np.round((df_antibio["resistentes"] / total) * 100, 2)

            # Extraer listas para gráficos (usar S+I para los gráficos)
            antibioticos = df_antibio["antibiotico__antibiotico__nombre"].tolist()
            porcentaje_s = df_antibio["porcentaje_s"].tolist()
            porcentaje_si = df_antibio["porcentaje_si"].tolist()
            porcentaje_i = df_antibio["porcentaje_i"].tolist()
            porcentaje_r = df_antibio["porcentaje_r"].tolist()

        # Convertir DataFrame a lista de diccionarios
        tabla_resumen = df_antibio.to_dict(orient="records")

        return {
            "tabla_resumen": tabla_resumen,
            "antibioticos": antibioticos,
            "porcentaje_s": porcentaje_s,
            "porcentaje_si": porcentaje_si,
            "porcentaje_i": porcentaje_i,
            "porcentaje_r": porcentaje_r,
        }

    @staticmethod
    def _get_arm_results(qs_final, total_aislados: int, mecanismos_base_ids: list[int], hospital) -> list[dict]:
        """Genera un resumen de mecanismos de resistencia y sus subtipos para un conjunto de datos de un hospital"""
        resumen_mecanismos = []

        # Combinaciones de mecanismos por aislado: usamos defaultdict porque nos permite inicializar valores por defecto
        # de forma automática al acceder a una clave que aún no existe, evitando así KeyError. Formamos así una estructura
        # jerárquica sin necesidad de saber el número de claves (combinaciones de mecanismos, subtipos) de antemano.
        # ref: https://docs.python.org/es/3.13/library/collections.html#collections.defaultdict
        combinaciones_count = defaultdict(int)
        combinaciones_subtipos = defaultdict(list)

        # Mapeo de mecanismo_base_id a nombre del mecanismo
        mecanismos_nombres = {}
        for mec_base_id in mecanismos_base_ids:
            mecanismos_hospital = MecanismoResistenciaHospital.objects.filter(
                mecanismo_id=mec_base_id,
                hospital=hospital
            ).first()
            if mecanismos_hospital:
                # Añadimos el id del Mecanismo BASE con su nombre como valor al diccionario
                mecanismos_nombres[mec_base_id] = mecanismos_hospital.mecanismo.nombre

        # Obtener todos los aislados del queryset final con sus mecanismos
        aislados_con_mecanismos = qs_final.prefetch_related(
            "mecanismos_resistencia__mecanismo",
            "subtipos_resistencia__subtipo_mecanismo"
        ).distinct()

        for aislado in aislados_con_mecanismos:
            # Para cada uno de los Aislados obtenemos los mecanismos base de este aislado
            mecanismos_aislado = set()
            subtipos_por_mecanismo = defaultdict(list)

            # Filtra mecanismos del hospital y guarda los IDs base
            for mec_hosp in aislado.mecanismos_resistencia.filter(hospital=hospital):
                mec_base_id = mec_hosp.mecanismo_id
                if mec_base_id in mecanismos_base_ids:
                    mecanismos_aislado.add(mec_base_id) # Incorporamos el mecanismo al set

                    # Obtener subtipos para este mecanismo en este aislado
                    subtipos = aislado.subtipos_resistencia.filter(
                        hospital=hospital,
                        subtipo_mecanismo__mecanismo_id=mec_base_id
                    )
                    for subtipo in subtipos:
                        if subtipo.subtipo_mecanismo.nombre:
                            subtipos_por_mecanismo[mec_base_id].append( # Incorporamos el subtipo a la lista del dict
                                subtipo.subtipo_mecanismo.nombre
                            )

            if mecanismos_aislado:
                # Genera una clave única y ordenada de la combinación de mecanismos
                mecanismos_ordenados = sorted(mecanismos_aislado)
                combinacion_key = tuple(mecanismos_ordenados)
                combinaciones_count[combinacion_key] += 1

                # Añade los subtipos correspondientes a esta combinación
                for mec_id in mecanismos_ordenados:
                    if mec_id in subtipos_por_mecanismo:
                        combinaciones_subtipos[combinacion_key].extend(
                            [(mec_id, st) for st in subtipos_por_mecanismo[mec_id]]
                        )

        # Construye el resumen final a partir de las combinaciones encontradas
        for combinacion, count in combinaciones_count.items():
            # Crea nombre legible de la combinación
            nombres_mecanismos = [mecanismos_nombres.get(mec_id, f"Mecanismo {mec_id}")
                                  for mec_id in combinacion]
            nombre_combinacion = " + ".join(nombres_mecanismos)  # "A + B"

            porcentaje = round(100 * count / total_aislados, 2) if total_aislados else 0

            # Cuenta los subtipos y los ordena por frecuencia
            subtipos_conteo = defaultdict(int)
            for mec_id, subtipo_nombre in combinaciones_subtipos[combinacion]:
                subtipos_conteo[subtipo_nombre] += 1

            # Ordenamos los subtipos por conteo descendente
            subtipos_ordenados = sorted(
                subtipos_conteo.items(),
                key=lambda x: x[1],
                reverse=True
            )

            subtipo_lista = [f"{nombre}: {conteo}" for nombre, conteo in subtipos_ordenados]

            # Añade el registro al resumen
            resumen_mecanismos.append({
                "nombre": nombre_combinacion,
                "porcentaje": porcentaje,
                "conteo": count,
                "subtipos": " | ".join(subtipo_lista) if subtipo_lista else None,
                "es_combinacion": len(combinacion) > 1
            })

        # Ordena el resumen final por número de aislados descendente
        resumen_mecanismos = sorted(resumen_mecanismos, key=lambda x: x["conteo"], reverse=True)

        return resumen_mecanismos

    @staticmethod
    def _get_charts(qs_final,
                    antibioticos,
                    porcentaje_s,
                    porcentaje_si, # puede que lo necesite en un futuro si se hacen gráficos por antibiótico basados en S+I
                    porcentaje_i,
                    porcentaje_r,
                    resistencias_intrinsecas_ids,
                    tiene_variantes,
                    filtro_antibiotico
                    ):

        """Genera los gráficos y estadisticas para los aislados filtrados. Devuelve un diccionario con
        un gráfico de barras apiladas, gráficos de sectores e histogramas."""

        # Gráficos con barras apiladas antibióticos
        grafico_antibioticos = build_antibiotics_bar_chart(antibioticos, porcentaje_s, porcentaje_i, porcentaje_r)

        # Gráficos circulares (piecharts)
        # Obtenemos los datos
        stats = {
            "sexo": list(
                qs_final.values(nombre=F("registro__sexo__sexo__descripcion"))
                .annotate(cuenta=Count("id"))
                .order_by("-cuenta")
            ),
            "ambito": list(
                qs_final.values(nombre=F("registro__ambito__ambito__nombre"))
                .annotate(cuenta=Count("id"))
                .order_by("-cuenta")
            ),
            "servicio": list(
                qs_final.values(nombre=F("registro__servicio__servicio__nombre"))
                .annotate(cuenta=Count("id"))
                .order_by("-cuenta")
            ),
            "muestra": list(
                qs_final.values(nombre=F("registro__tipo_muestra__categoria__nombre"))
                .annotate(cuenta=Count("id"))
                .order_by("-cuenta")
            ),
        }

        # generamos los gráficos de sectores
        sexo_piechart = build_piechart(stats["sexo"], "Distribución por sexo")
        ambito_piechart = build_piechart(stats["ambito"], "Ámbito de procedencia")
        servicio_piechart = build_piechart(stats["servicio"], "Servicio clínico")
        muestra_piechart = build_piechart(stats["muestra"], "Tipo de muestra")

        # Histogramas de CMI
        # Obtener datos de CMI por antibiótico
        datos_cmi = (
            ResultadoAntibiotico.objects
            .select_related("antibiotico__antibiotico")
            .annotate(tiene_variantes=tiene_variantes)
            .filter(
                aislado__in=qs_final,
                cmi__isnull=False
            )
            .filter(filtro_antibiotico)
            .exclude(
                antibiotico__antibiotico__id__in=resistencias_intrinsecas_ids
            ).values(
                "antibiotico__antibiotico__nombre",
                "antibiotico__orden_informe",
                "cmi",
            )
        )

        if not datos_cmi:
            return None

        df_cmi = pd.DataFrame.from_records(list(datos_cmi))

        # Filtrar antibióticos con al menos 10 registros para crear histogramas
        conteos = df_cmi.groupby("antibiotico__antibiotico__nombre").size()
        antib_filtro = conteos[conteos >= 10].index

        if len(antib_filtro) == 0:
            return None

        # Mantenemos el orden según 'orden_informe'
        antibioticos_con_cmi = (
            df_cmi[["antibiotico__antibiotico__nombre", "antibiotico__orden_informe"]]
            .drop_duplicates()
            .set_index("antibiotico__antibiotico__nombre")
            .loc[antib_filtro]
            .sort_values("antibiotico__orden_informe")
            .index.tolist()
        )

        histogramas_cmi = build_mic_histogram(df_cmi, antibioticos_con_cmi)

        return {
            "grafico_antibioticos": grafico_antibioticos,
            "sexo_piechart": sexo_piechart,
            "ambito_piechart": ambito_piechart,
            "servicio_piechart": servicio_piechart,
            "muestra_piechart": muestra_piechart,
            "histogramas_cmi": histogramas_cmi
        }


class InformePredefinidoResistenciaPDFView(FormView):
    """Vista encargada de la generación de informes predefinidos en formato PDF con ReportLab
    url Reportlab: https://docs.reportlab.com/reportlab/userguide/ch1_intro/"""

    form_class = InformePredefinidoResistenciaForm
    template_name = "Informes/informe_predefinido.html"

    # colores personalizados para tablas
    verde = colors.HexColor("#D1E7DD")
    amarillo = colors.HexColor("#FFF3CD")
    rojo = colors.HexColor("#F8D7dA")
    violeta = colors.HexColor("#F1D7F8")

    def get_form_kwargs(self):
        """Pasa el hospital actual al formulario para filtrar los queryset."""
        kwargs = super().get_form_kwargs()
        kwargs["hospital"] = self.request.user.hospital
        return kwargs

    def form_invalid(self, form):
        """Maneja errores de validación para peticiones AJAX.
        En la plantilla hay 2 AJAX que hacen POST con los datos del formulario a la
        dirección de esta misma vista: uno se encarga de recoger una respuesta JSON con
        errores, el otro se encarga de recoger el archivo PDF generado si el form se valida."""

        # Si es AJAX, devolver errores como JSON
        if self.request.headers.get("X-Requested-With") == "XMLHttpRequest":
            errors = {}

            # Convertir errores del formulario en un diccionario
            for field, error_list in form.errors.items():
                errors[field] = [{"message": str(e)} for e in error_list]

            # Devuelve los errores en una respuesta JSON con código de error (HTTP400)
            return JsonResponse({
                "success": False,
                "status": "invalid",
                "errors": errors
            }, status=400)

        # Si no es AJAX -> renderizar el formulario normalmente
        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        # Variables demográficas
        hospital = self.request.user.hospital
        microorganismo = form.cleaned_data["microorganismo"]
        fecha_inicial = form.cleaned_data["fecha_inicial"]
        fecha_final = form.cleaned_data["fecha_final"]
        servicio = form.cleaned_data.get("servicio")
        categoria_muestra = form.cleaned_data.get("categoria_muestra")

        # Variables booleanas
        considerar_variantes = form.cleaned_data.get("considerar_variantes", False)
        unificar_sei_con_sensibles = form.cleaned_data.get("unificar_sei_con_sensibles", False)
        comparar_con_anterior = form.cleaned_data.get("comparar_con_periodo_anterior", False)

        # Construcción de datos para el PDF
        datos = self._build_data_for_pdf(
            hospital=hospital,
            microorganismo=microorganismo,
            fecha_inicial=fecha_inicial,
            fecha_final=fecha_final,
            considerar_variantes=considerar_variantes,
            unificar_sei_con_sensibles=unificar_sei_con_sensibles,
            servicio_filtro=servicio,
            categoria_muestra_filtro=categoria_muestra,
            comparar_con_anterior=comparar_con_anterior
        )

        # Contrucción del PDF con SimpleDocTemplate
        # Existe mucha información en Internet sobre como utilizar Reportlab. Algunos ejemplos:
        # https://www.reportlab.com/docs/reportlab-userguide.pdf
        # https://medium.com/@AlexanderObregon/creating-pdf-reports-with-python-a53439031117
        # https://medium.com/@parveengoyal198/mastering-pdf-report-generation-with-reportlab-a-comprehensive-tutorial-part-590a08af7017
        # https://medium.com/@parveengoyal198/mastering-pdf-report-generation-with-reportlab-a-comprehensive-tutorial-part-2-c970ccd15fb6

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A3))
        elementos = self._construir_informe_pdf(
            microorganismo=microorganismo,
            fecha_inicial=fecha_inicial,
            fecha_final=fecha_final,
            resultados_global=datos["resultados_global"],
            mecanismos_global=datos["mecanismos_global"],
            resultados_por_ambito=datos["resultados_por_ambito"],
            mecanismos_por_ambito=datos["mecanismos_por_ambito"],
            resultados_por_servicio=datos["resultados_por_servicio"],
            mecanismos_por_servicio=datos["mecanismos_por_servicio"],
            resultados_por_sexo=datos["resultados_por_sexo"],
            mecanismos_por_sexo=datos["mecanismos_por_sexo"],
            resultados_por_edad=datos["resultados_por_edad"],
            mecanismos_por_edad=datos["mecanismos_por_edad"],
            resultados_por_muestra=datos["resultados_por_muestra"],
            mecanismos_por_muestra=datos["mecanismos_por_muestra"],
            resultados_por_sexo_edad=datos["resultados_por_sexo_edad"],
            mecanismos_por_sexo_edad=datos["mecanismos_por_sexo_edad"],
            unificar_sei_con_sensibles=unificar_sei_con_sensibles,
            total_aislados=datos["total_aislados"],
            hospital=hospital,
            resultados_por_ambito_ic=datos["resultados_por_ambito"],
            resultados_por_servicio_ic=datos["resultados_por_servicio"],
            resultados_por_sexo_ic=datos["resultados_por_sexo"],
            resultados_por_edad_ic=datos["resultados_por_edad"],
            resultados_por_muestra_ic=datos["resultados_por_muestra"],
            resultados_por_sexo_edad_ic=datos["resultados_por_sexo_edad"],
            mecanismos_por_ambito_ic=datos["mecanismos_por_ambito"],
            mecanismos_por_servicio_ic=datos["mecanismos_por_servicio"],
            mecanismos_por_sexo_ic=datos["mecanismos_por_sexo"],
            mecanismos_por_edad_ic=datos["mecanismos_por_edad"],
            mecanismos_por_muestra_ic=datos["mecanismos_por_muestra"],
            mecanismos_por_sexo_edad_ic=datos["mecanismos_por_sexo_edad"],
        )

        doc.build(elementos)

        buffer.seek(0)
        # utilizamos el nombre del hospital, microorganismo y fechas filtradas para el nombre el archivo
        filename = f"{hospital.nombre}_sensibilidad_{microorganismo.microorganismo.nombre}_{fecha_inicial}-{fecha_final}.pdf"

        # devolvemos el archivo PDF
        return FileResponse(buffer, as_attachment=True, filename=filename)

    ###################################
    # Métodos de construcción de datos
    ###################################

    def _build_data_for_pdf(self, hospital: Hospital, microorganismo: MicroorganismoHospital,
                            fecha_inicial: date, fecha_final: date, considerar_variantes: bool = False,
                            unificar_sei_con_sensibles=True, servicio_filtro=None,
                            categoria_muestra_filtro=None,
                            comparar_con_anterior=True):
        """Método interno encargado de la construcción del conjunto de datos para construir el PDF"""

        # Queryset base con prefetch
        qs = (
            Aislado.objects
            .select_related(
                "registro__sexo__sexo",
                "registro__ambito__ambito",
                "registro__servicio__servicio",
                "registro__tipo_muestra__categoria",
                "microorganismo__microorganismo"
            )
            .prefetch_related(
                Prefetch("mecanismos_resistencia",
                         queryset=MecanismoResistenciaHospital.objects.select_related("mecanismo")),
                Prefetch("subtipos_resistencia",
                         queryset=SubtipoMecanismoResistenciaHospital.objects.select_related(
                             "subtipo_mecanismo__mecanismo"))
            )
            .filter(
                hospital=hospital,
                microorganismo=microorganismo,
                registro__fecha__range=[fecha_inicial, fecha_final],
                registro__sexo__ignorar_informes=False,
                registro__ambito__ignorar_informes=False,
                registro__servicio__ignorar_informes=False,
                registro__tipo_muestra__categoria__ignorar_informes=False
            )
        )

        # Selección única por paciente
        qs_anotado = qs.annotate(
            row_num=Window(
                expression=RowNumber(),
                partition_by=[F("registro__nh_hash")],
                order_by=F("registro__fecha").asc()
            )
        )

        # Extrae IDs para crear el queryset limpio
        ids_primer_aislado = list(qs_anotado.filter(row_num=1).values_list("id", flat=True))

        if not ids_primer_aislado:
            return self._empty_data()

        qs_filtrados = Aislado.objects.filter(id__in=ids_primer_aislado)  # queryset limpio

        # Aplicamos los filtros opcionales del formulario
        if servicio_filtro:
            qs_filtrados = qs_filtrados.filter(registro__servicio=servicio_filtro)
        if categoria_muestra_filtro:
            qs_filtrados = qs_filtrados.filter(registro__tipo_muestra__categoria=categoria_muestra_filtro)

        # Devolver una estructura de datos vacía si la queryset está vacía
        if not qs_filtrados.exists():
            return self._empty_data()

        # Almacenamos en memoria el total
        total_aislados = qs_filtrados.count()

        # Filtro de antibióticos visibles
        perfil = (
            PerfilAntibiogramaHospital.objects
            .filter(hospital=hospital, grupo_eucast=microorganismo.microorganismo.grupo_eucast)
            .prefetch_related("perfilantibioticohospital_set")
            .first()
        )

        if perfil:
            antibioticos_visibles = list(
                PerfilAntibioticoHospital.objects
                .filter(perfil=perfil, mostrar_en_informes=True)
                .values_list("antibiotico_hospital", flat=True)
            )
        else:
            antibioticos_visibles = []

        # Anotar grupos de edad
        qs_con_grupo_edad = qs_filtrados.annotate(

            grupo_edad=Case(
                When(registro__edad__lt=15, then=Value("<15 años")),
                When(registro__edad__lte=70, then=Value("15-70 años")),
                When(registro__edad__gt=70, then=Value(">70 años")),
                output_field=CharField()
            )
        )

        # Obtenemos los grupos válidos (N > 30)
        # Por ámbito
        ambitos_counts = dict(
            qs_filtrados.values("registro__ambito__ambito__nombre")
            .annotate(total=Count("id"))
            .values_list("registro__ambito__ambito__nombre", "total")
        )
        ambitos_validos = [k for k, v in ambitos_counts.items() if v >= 30]

        # Por servicio
        servicios_counts = dict(
            qs_filtrados.values("registro__servicio__servicio__nombre")
            .annotate(total=Count("id"))
            .values_list("registro__servicio__servicio__nombre", "total")
        )
        servicios_validos = [k for k, v in servicios_counts.items() if v >= 30]

        # Por sexo
        sexos_counts = dict(
            qs_filtrados.values("registro__sexo__sexo__descripcion")
            .annotate(total=Count("id"))
            .values_list("registro__sexo__sexo__descripcion", "total")
        )
        sexos_validos = [k for k, v in sexos_counts.items() if v >= 30]

        # Por muestra
        muestras_counts = dict(
            qs_filtrados.values("registro__tipo_muestra__categoria__nombre")
            .annotate(total=Count("id"))
            .values_list("registro__tipo_muestra__categoria__nombre", "total")
        )
        muestras_validas = [k for k, v in muestras_counts.items() if v >= 30]

        # Por edad
        edades_counts = dict(
            qs_con_grupo_edad.values("grupo_edad")
            .annotate(total=Count("id"))
            .values_list("grupo_edad", "total")
        )
        edades_validas = [k for k, v in edades_counts.items() if v >= 30]

        # Cálculos globales (sensibilidad y mecanismos de resistencia)
        resultados_global = self._get_results(qs_filtrados, considerar_variantes,
                                              unificar_sei_con_sensibles,
                                              calcular_ic=True, antibioticos_visibles=antibioticos_visibles)
        mecanismos_global = self._get_arm(qs_filtrados, total_aislados)

        # Preparar querysets filtradas por valores
        qs_ambito = self._filter_by_values(qs_filtrados, "registro__ambito__ambito__nombre", ambitos_validos)
        qs_servicio = self._filter_by_values(qs_filtrados, "registro__servicio__servicio__nombre", servicios_validos)
        qs_sexo = self._filter_by_values(qs_filtrados, "registro__sexo__sexo__descripcion", sexos_validos)
        qs_edad = self._filter_by_values(qs_con_grupo_edad, "grupo_edad", edades_validas)
        qs_muestra = self._filter_by_values(qs_filtrados, "registro__tipo_muestra__categoria__nombre", muestras_validas)

        # Calcular resultados y mecanismos
        # Resultados por grupo
        resultados_por_ambito = self._get_results_by_group(
            qs_ambito, "registro__ambito__ambito__nombre", considerar_variantes,
            unificar_sei_con_sensibles, calcular_ic=False,
            antibioticos_visibles=antibioticos_visibles
        )
        resultados_por_servicio = self._get_results_by_group(
            qs_servicio, "registro__servicio__servicio__nombre", considerar_variantes,
            unificar_sei_con_sensibles, calcular_ic=False,
            antibioticos_visibles=antibioticos_visibles
        )
        resultados_por_sexo = self._get_results_by_group(
            qs_sexo, "registro__sexo__sexo__descripcion", considerar_variantes,
            unificar_sei_con_sensibles, calcular_ic=False,
            antibioticos_visibles=antibioticos_visibles
        )
        resultados_por_edad = self._get_results_by_group(
            qs_edad, "grupo_edad", considerar_variantes, unificar_sei_con_sensibles,
            calcular_ic=False, antibioticos_visibles=antibioticos_visibles
        )
        resultados_por_muestra = self._get_results_by_group(
            qs_muestra, "registro__tipo_muestra__categoria__nombre", considerar_variantes,
            unificar_sei_con_sensibles, calcular_ic=False, antibioticos_visibles=antibioticos_visibles
        )
        resultados_por_sexo_edad = self._get_results_by_sex_and_age(
            qs_filtrados, considerar_variantes, unificar_sei_con_sensibles,
            calcular_ic=False, antibioticos_visibles=antibioticos_visibles
        )

        # Mecanismos por grupo
        mecanismos_por_ambito = self._get_arm(qs_ambito, total_aislados,
                                              group_by="registro__ambito__ambito__nombre")
        mecanismos_por_servicio = self._get_arm(qs_servicio, total_aislados,
                                                group_by="registro__servicio__servicio__nombre")
        mecanismos_por_sexo = self._get_arm(qs_sexo, total_aislados,
                                            group_by="registro__sexo__sexo__descripcion")
        mecanismos_por_edad = self._get_arm(qs_edad, total_aislados, group_by="grupo_edad")
        mecanismos_por_muestra = self._get_arm(qs_muestra, total_aislados,
                                               group_by="registro__tipo_muestra__categoria__nombre")
        mecanismos_por_sexo_edad = self._get_arm_sexo_edad(qs_filtrados)

        # Comparación con periodo anterior (si fue marcado en el formulario)
        if comparar_con_anterior:
            duracion = relativedelta(fecha_final, fecha_inicial)  # calculo del periodo anterior con relativedelta
            # necesitamos que los periodos sean adyacentes, sin solaparse, por lo que restamos 1 día
            # Nota: lo bueno de relativedelta es que maneja de forma natural los dias de los meses y años bisiestos
            # ref: https://dateutil.readthedocs.io/en/stable/relativedelta.html
            fecha_inicial_anterior = fecha_inicial - duracion - relativedelta(days=1)
            fecha_final_anterior = fecha_final - duracion - relativedelta(days=1)

            # Obtenemos la queryset del periodo anterior con necesita_mecanismos=True
            qs_anterior = self._get_previous_period_queryset(
                hospital, microorganismo, fecha_inicial_anterior, fecha_final_anterior,
                servicio_filtro, categoria_muestra_filtro, necesita_mecanismos=True
            )

            if qs_anterior is not None and qs_anterior.exists():
                total_aislados_anterior = qs_anterior.count()
                # Anotar grupo edad para queryset anterior
                qs_anterior_con_edad = qs_anterior.annotate(
                    grupo_edad=Case(
                        When(registro__edad__lt=15, then=Value("<15 años")),
                        When(registro__edad__lte=70, then=Value("15-70 años")),
                        When(registro__edad__gt=70, then=Value(">70 años")),
                        output_field=CharField()
                    )
                )

                # Calcular resultados del periodo anterior
                resultados_anterior_global = self._get_results(
                    qs_anterior, considerar_variantes, unificar_sei_con_sensibles,
                    calcular_ic=False, antibioticos_visibles=antibioticos_visibles
                )
                mecanismos_anterior_global = self._get_arm(qs_anterior, total_aislados_anterior)

                # Comparar globales
                resultados_global = self._compare_with_previous_period(
                    resultados_global, resultados_anterior_global, unificar_sei_con_sensibles
                )
                mecanismos_global = self._compare_mechs_with_previous_period(mecanismos_global,
                                                                                   mecanismos_anterior_global)

                # Calcula los resultados por grupos del periodo anterior
                resultados_anterior_ambito = self._get_results_by_group(
                    qs_anterior, "registro__ambito__ambito__nombre", considerar_variantes,
                    unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )
                resultados_anterior_servicio = self._get_results_by_group(
                    qs_anterior, "registro__servicio__servicio__nombre", considerar_variantes,
                    unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )
                resultados_anterior_sexo = self._get_results_by_group(
                    qs_anterior, "registro__sexo__sexo__descripcion", considerar_variantes,
                    unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )
                resultados_anterior_edad = self._get_results_by_group(
                    qs_anterior_con_edad, "grupo_edad", considerar_variantes,
                    unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )
                resultados_anterior_muestra = self._get_results_by_group(
                    qs_anterior, "registro__tipo_muestra__categoria__nombre", considerar_variantes,
                    unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )
                resultados_anterior_sexo_edad = self._get_results_by_sex_and_age(
                    qs_anterior, considerar_variantes, unificar_sei_con_sensibles, calcular_ic=False,
                    antibioticos_visibles=antibioticos_visibles
                )

                # Mecanismos del periodo anterior
                mecanismos_anterior_ambito = self._get_arm(qs_anterior, total_aislados_anterior,
                                                           group_by="registro__ambito__ambito__nombre")
                mecanismos_anterior_servicio = self._get_arm(qs_anterior, total_aislados_anterior,
                                                             group_by="registro__servicio__servicio__nombre")
                mecanismos_anterior_sexo = self._get_arm(qs_anterior, total_aislados_anterior,
                                                         group_by="registro__sexo__sexo__descripcion")
                mecanismos_anterior_edad = self._get_arm(qs_anterior_con_edad, total_aislados_anterior,
                                                         group_by="grupo_edad")
                mecanismos_anterior_muestra = self._get_arm(qs_anterior, total_aislados_anterior,
                                                            group_by="registro__tipo_muestra__categoria__nombre")
                mecanismos_anterior_sexo_edad = self._get_arm_sexo_edad(qs_anterior)

                # Comparar los distintos grupos
                resultados_por_ambito = self._compare_groups_with_previous_period(
                    resultados_por_ambito, resultados_anterior_ambito, unificar_sei_con_sensibles
                )
                resultados_por_servicio = self._compare_groups_with_previous_period(
                    resultados_por_servicio, resultados_anterior_servicio, unificar_sei_con_sensibles
                )
                resultados_por_sexo = self._compare_groups_with_previous_period(
                    resultados_por_sexo, resultados_anterior_sexo, unificar_sei_con_sensibles
                )
                resultados_por_edad = self._compare_groups_with_previous_period(
                    resultados_por_edad, resultados_anterior_edad, unificar_sei_con_sensibles
                )
                resultados_por_muestra = self._compare_groups_with_previous_period(
                    resultados_por_muestra, resultados_anterior_muestra, unificar_sei_con_sensibles
                )
                resultados_por_sexo_edad = self._compare_groups_with_previous_period(
                    resultados_por_sexo_edad, resultados_anterior_sexo_edad, unificar_sei_con_sensibles
                )

                mecanismos_por_ambito = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_ambito, mecanismos_anterior_ambito
                )
                mecanismos_por_servicio = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_servicio, mecanismos_anterior_servicio
                )
                mecanismos_por_sexo = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_sexo, mecanismos_anterior_sexo
                )
                mecanismos_por_edad = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_edad, mecanismos_anterior_edad
                )
                mecanismos_por_muestra = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_muestra, mecanismos_anterior_muestra
                )
                mecanismos_por_sexo_edad = self._compare_mechs_by_group_with_previous_period(
                    mecanismos_por_sexo_edad, mecanismos_anterior_sexo_edad
                )
            else:
                # No hay datos anteriores, añadir tendencias vacías
                self._agregar_tendencias_vacias(
                    resultados_global, mecanismos_global,
                    resultados_por_ambito, mecanismos_por_ambito,
                    resultados_por_servicio, mecanismos_por_servicio,
                    resultados_por_sexo, mecanismos_por_sexo,
                    resultados_por_edad, mecanismos_por_edad,
                    resultados_por_muestra, mecanismos_por_muestra,
                    resultados_por_sexo_edad, mecanismos_por_sexo_edad
                )
        else:
            # Sin comparación, añadimos las tendencias vacías
            self._agregar_tendencias_vacias(
                resultados_global, mecanismos_global,
                resultados_por_ambito, mecanismos_por_ambito,
                resultados_por_servicio, mecanismos_por_servicio,
                resultados_por_sexo, mecanismos_por_sexo,
                resultados_por_edad, mecanismos_por_edad,
                resultados_por_muestra, mecanismos_por_muestra,
                resultados_por_sexo_edad, mecanismos_por_sexo_edad
            )

        return {
            "resultados_global": resultados_global,
            "mecanismos_global": mecanismos_global,
            "resultados_por_ambito": resultados_por_ambito,
            "mecanismos_por_ambito": mecanismos_por_ambito,
            "resultados_por_servicio": resultados_por_servicio,
            "mecanismos_por_servicio": mecanismos_por_servicio,
            "resultados_por_sexo": resultados_por_sexo,
            "mecanismos_por_sexo": mecanismos_por_sexo,
            "resultados_por_edad": resultados_por_edad,
            "mecanismos_por_edad": mecanismos_por_edad,
            "resultados_por_muestra": resultados_por_muestra,
            "mecanismos_por_muestra": mecanismos_por_muestra,
            "resultados_por_sexo_edad": resultados_por_sexo_edad,
            "mecanismos_por_sexo_edad": mecanismos_por_sexo_edad,
            "total_aislados": total_aislados,
        }

    @staticmethod
    def _empty_data():
        """Devuelve una estructura vacía"""
        return {
            "resultados_global": [],
            "mecanismos_global": [],
            "resultados_por_ambito": {},
            "mecanismos_por_ambito": {},
            "resultados_por_servicio": {},
            "mecanismos_por_servicio": {},
            "resultados_por_sexo": {},
            "mecanismos_por_sexo": {},
            "resultados_por_edad": {},
            "mecanismos_por_edad": {},
            "resultados_por_muestra": {},
            "mecanismos_por_muestra": {},
            "resultados_por_sexo_edad": {},
            "mecanismos_por_sexo_edad": {},
            "total_aislados": 0,
        }

    @staticmethod
    def _get_results(qs: QuerySet[Aislado, Aislado], considerar_variantes: bool,
                     unificar_sei_con_sensibles: bool, calcular_ic: bool = True,
                     antibioticos_visibles=None) -> list[dict]:
        """Realiza los cálculos necesarios para la generación de datos."""

        # Subquery para casos en los que se marcó la opción de considerar variantes
        tiene_variantes = Exists(
            Antibiotico.objects.filter(parent=OuterRef("antibiotico__antibiotico"))
        )

        # Filtro de antibióticos según variantes
        if considerar_variantes:
            filtro_antibiotico = Q(antibiotico__antibiotico__es_variante=True) | Q(
                antibiotico__antibiotico__es_variante=False, tiene_variantes=False
            )
        else:
            filtro_antibiotico = Q(antibiotico__antibiotico__es_variante=False)

        # Obtener resistencias intrínsecas
        # traemos directamente la lista de IDs desde el microorganismo
        primer_microorganismo_hospital_id = (
            qs.values_list("microorganismo__id", flat=True)
            .first()
        )

        # lista de resistencias intrínsecas del microorganismo
        microorganismo_hospital = (MicroorganismoHospital.objects.select_related("microorganismo")
                                   .get(id=primer_microorganismo_hospital_id))

        ids_resistencia_intrinseca = microorganismo_hospital.microorganismo.lista_ids_resistencia_intrinseca or []

        # Construir el queryset de resultados de objetos ResultadoAntibiotico
        resultados_qs = (
            ResultadoAntibiotico.objects
            .select_related("antibiotico__antibiotico")
            .annotate(tiene_variantes=tiene_variantes)
            .filter(
                aislado__in=qs,
                interpretacion__in=["S", "I", "R"]
            )
            .filter(filtro_antibiotico)
        )

        # Filtro de antibióticos visibles
        if antibioticos_visibles is not None:
            resultados_qs = resultados_qs.filter(antibiotico__id__in=antibioticos_visibles)

        # Excluir resistencias intrínsecas si existen
        if ids_resistencia_intrinseca:
            resultados_qs = resultados_qs.exclude(
                antibiotico__antibiotico_id__in=ids_resistencia_intrinseca
            )

        # Queryset de resultados finales con anotaciones
        resultados = (
            resultados_qs
            .values(
                "antibiotico__antibiotico__nombre",
                "antibiotico__orden_informe"
            )
            .annotate(
                total=Count("id"),
                sensibles=Count(
                    "id",
                    filter=Q(interpretacion__in=(["S", "I"] if unificar_sei_con_sensibles else ["S"]))
                ),
                sei=Count("id", filter=Q(interpretacion="I"))
            )
            .filter(total__gt=1)
            .order_by(
                "antibiotico__orden_informe",
                "antibiotico__antibiotico__nombre"
            )
        )

        # Convertimos a lista
        resultados_list = list(resultados)

        if not resultados_list:
            return []

        # Preparar arrays numpy para cálculo de ICs por el método calculate_ic95()
        if calcular_ic:
            totales = np.array([res["total"] for res in resultados_list])
            sensibles_arr = np.array([res["sensibles"] for res in resultados_list])

            # Calcular los ICs
            ic_lows, ic_highs = calculate_ic95(sensibles_arr, totales)
            ic_lows = np.round(ic_lows * 100, 2)
            ic_highs = np.round(ic_highs * 100, 2)

        # Construir la tabla final de resultados
        tabla = []
        for idx, res in enumerate(resultados_list):
            total = res["total"]
            sensibles = res["sensibles"]
            sei = res["sei"]
            p_s = sensibles / total if total else 0

            # Usar los valores pre-calculados
            if calcular_ic:
                ic_low = ic_lows[idx]
                ic_high = ic_highs[idx]
            else:
                ic_low, ic_high = None, None

            # Calcular porcentaje de sei, si es necesario
            porcentaje_i = None
            if not unificar_sei_con_sensibles and total and sei > 0:
                porcentaje_i = np.round(100 * sei / total, 2)

            tabla.append({
                "nombre": res["antibiotico__antibiotico__nombre"],
                "orden_informe": res["antibiotico__orden_informe"],
                "total": total,
                "sensibles": sensibles,
                "sei": sei if not unificar_sei_con_sensibles else None, # solo si es necesario
                "porcentaje_s": np.round(100 * p_s, 2),
                "porcentaje_i": porcentaje_i,
                "ic_low": ic_low,
                "ic_high": ic_high,
                "necesita_asterisco": total < 30
            })

        return tabla

    @staticmethod
    def _get_arm(qs: QuerySet[Aislado, Aislado], total: int, group_by: str | None = None) -> list[dict] | dict[str, list[dict]]:
        """Realiza los cálculos necesarios para la generación de datos de los mecanismos de resistencia encontrados
         en el periodo filtrado, incluyendo combinaciones. Si se le pasa el argumento 'group_by' se calcula por grupo
         devolviendo un diccionario, si no se le pasa este argumento se calcula devolviendo una lista de diccionarios.
        """
        # Si no hay aislados devolver lista / diccionario vacío
        if total == 0:
            return [] if group_by is None else {}

        # Si no se le pasa el argumento 'group_by'
        if group_by is None:
            combinaciones_count = defaultdict(int)  # {tupla(combinacion): int}
            combinaciones_subtipos = defaultdict(
                lambda: defaultdict(set))  # {tupla(combinacion): {subtipo: set(aislados)}}
            mecanismos_nombres = {}

            # Usamos select_related y prefetch_related para reducir queries (los necesitamos para hacer listas)
            aislados = qs.select_related(
                "registro"
            ).prefetch_related(
                Prefetch("mecanismos_resistencia",  # prefetch
                         queryset=MecanismoResistenciaHospital.objects.select_related("mecanismo")),
                Prefetch("subtipos_resistencia",
                         queryset=SubtipoMecanismoResistenciaHospital.objects.select_related(
                             "subtipo_mecanismo__mecanismo"))
            )

            # Convertimos los aislados a listas
            aislados_list = list(aislados)

            for aislado in aislados_list:
                # Convertimos las relaciones a listas. Gracias al prefetch los tenemos ya en memoria y
                # podemos cargarlos todos sin tener que hacer una query nueva por cada aislado
                mecanismos_list = list(aislado.mecanismos_resistencia.all())
                subtipos_list = list(aislado.subtipos_resistencia.all())

                # Obtenemos los mecanismos del aislado
                mecanismos_aislado = []
                subtipos_por_mecanismo_base = defaultdict(set)

                # Creamos unn diccionario de búsqueda de mecanismos base
                mecanismos_base_ids = set()
                for mec_hosp in mecanismos_list:
                    mec_id = mec_hosp.id
                    mec_base_id = mec_hosp.mecanismo_id
                    mecanismos_aislado.append(mec_id)
                    mecanismos_base_ids.add(mec_base_id)

                    # Guardar nombre del mecanismo para localizarlo más tarde y formar los resultados de combinaciones
                    if mec_id not in mecanismos_nombres:
                        mecanismos_nombres[mec_id] = mec_hosp.mecanismo.nombre  # diccionario de búsqueda de mecanismos

                # Filtramos los subtipos
                for subtipo_rel in subtipos_list:
                    # nos quedamos con los subtipos cuyo mecanismo base está presente en el aislado
                    if subtipo_rel.subtipo_mecanismo.mecanismo_id in mecanismos_base_ids:
                        nombre = subtipo_rel.subtipo_mecanismo.nombre
                        if nombre:
                            subtipos_por_mecanismo_base[nombre].add(
                                aislado.id)  # diccionario {subtipo: set(aislado.id,) }

                # Si se encontraron mecanismos de resistencia
                if mecanismos_aislado:
                    # Crear clave de combinación ordenada sin duplicados
                    mecanismos_ordenados = tuple(sorted(set(mecanismos_aislado)))
                    combinaciones_count[mecanismos_ordenados] += 1

                    # Guardar subtipos únicos por aislado para esta combinación
                    for subtipo_nombre, aislados_set in subtipos_por_mecanismo_base.items():
                        combinaciones_subtipos[mecanismos_ordenados][subtipo_nombre].update(aislados_set)

            # Convierte a formato de salida
            mecanismos = []
            for combinacion, count in combinaciones_count.items():  # dict[tupla[int] -> int]
                # Crear nombre de la combinación
                nombres_mecanismos = [mecanismos_nombres.get(mec_id) for mec_id in combinacion]
                nombre_combinacion = " + ".join(nombres_mecanismos)

                porcentaje = np.round(100 * count / total, 2)

                # Contar aislados únicos por subtipo
                subtipos_conteo = {
                    subtipo: len(aislados_set)
                    for subtipo, aislados_set in combinaciones_subtipos[combinacion].items()
                }

                # Ordenar subtipos por conteo descendente
                subtipos_ordenados = sorted(
                    subtipos_conteo.items(),
                    key=lambda x: x[1],
                    reverse=True
                )

                subtipo_lista = [f"{nombre}: {conteo}" for nombre, conteo in subtipos_ordenados]

                mecanismos.append({
                    "nombre": nombre_combinacion,
                    "conteo": count,
                    "porcentaje": porcentaje,
                    "total": total,
                    "subtipos": " | ".join(subtipo_lista) if subtipo_lista else None,
                    "es_combinacion": len(combinacion) > 1
                })

            # Ordenar por conteo descendente
            mecanismos.sort(key=lambda x: x["conteo"], reverse=True)
            return mecanismos

        else:
            # Para resultados POR GRUPO
            mecanismos_por_grupo = defaultdict(list)

            # Obtener totales por grupo
            grupos_totales = dict(
                qs.values_list(group_by)
                .annotate(total=Count("id"))
                .values_list(group_by, "total")
            )

            if not grupos_totales:
                return {}

            # Prefetch para todos los grupos
            aislados = qs.select_related(
                "registro"
            ).prefetch_related(
                Prefetch("mecanismos_resistencia",
                         queryset=MecanismoResistenciaHospital.objects.select_related("mecanismo")),
                Prefetch("subtipos_resistencia",
                         queryset=SubtipoMecanismoResistenciaHospital.objects.select_related(
                             "subtipo_mecanismo__mecanismo"))
            )

            # Lista de aislados
            aislados_list = list(aislados)

            # Agrupamos aislados por grupo
            aislados_por_grupo = defaultdict(list)

            for aislado in aislados_list:
                # Obtener valor del grupo
                if "__" in group_by:
                    # Para campos relacionados como registro__sexo
                    parts = group_by.split("__")

                    obj = aislado
                    for part in parts:  # parts = [registro, sexo]
                        obj = getattr(obj, part, None)  # acceso iterativo al objeto atributo de clase, parar si es None
                        if obj is None:
                            break
                    grupo_val = obj
                else:
                    # para campos creados por anotaciones como 'grupo_edad'
                    grupo_val = getattr(aislado, group_by, None)

                if grupo_val:
                    aislados_por_grupo[grupo_val].append(aislado)

            # Procesamos cada grupo
            for grupo, total_grupo in grupos_totales.items():
                if total_grupo == 0:
                    continue

                combinaciones_count = defaultdict(int)
                combinaciones_subtipos = defaultdict(lambda: defaultdict(set))
                mecanismos_nombres = {}

                aislados_grupo = aislados_por_grupo.get(grupo, [])

                # Análogamente al caso general
                for aislado in aislados_grupo:
                    # Convertir relaciones a listas una sola vez
                    mecanismos_list = list(aislado.mecanismos_resistencia.all())
                    subtipos_list = list(aislado.subtipos_resistencia.all())

                    # Obtener mecanismos de este aislado
                    mecanismos_aislado = []
                    subtipos_por_mecanismo_base = defaultdict(set)
                    mecanismos_base_ids = set()

                    for mec_hosp in mecanismos_list:
                        mec_id = mec_hosp.id
                        mec_base_id = mec_hosp.mecanismo_id
                        mecanismos_aislado.append(mec_id)
                        mecanismos_base_ids.add(mec_base_id)

                        if mec_id not in mecanismos_nombres:
                            mecanismos_nombres[mec_id] = mec_hosp.mecanismo.nombre

                    # Filtrar subtipos
                    for subtipo_rel in subtipos_list:
                        if subtipo_rel.subtipo_mecanismo.mecanismo_id in mecanismos_base_ids:
                            nombre = subtipo_rel.subtipo_mecanismo.nombre
                            if nombre:
                                subtipos_por_mecanismo_base[nombre].add(aislado.id)

                    if mecanismos_aislado:
                        mecanismos_ordenados = tuple(sorted(set(mecanismos_aislado)))
                        combinaciones_count[mecanismos_ordenados] += 1

                        for subtipo_nombre, aislados_set in subtipos_por_mecanismo_base.items():
                            combinaciones_subtipos[mecanismos_ordenados][subtipo_nombre].update(aislados_set)

                # Convertir a formato de salida para este grupo
                mecanismos_grupo = []
                for combinacion, count in combinaciones_count.items():
                    nombres_mecanismos = [mecanismos_nombres.get(mec_id) for mec_id in combinacion]
                    nombre_combinacion = " + ".join(nombres_mecanismos)

                    porcentaje = round(100 * count / total_grupo, 2)

                    # Contar aislados únicos por subtipo
                    subtipos_conteo = {
                        subtipo: len(aislados_set)
                        for subtipo, aislados_set in combinaciones_subtipos[combinacion].items()
                    }

                    subtipos_ordenados = sorted(
                        subtipos_conteo.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )

                    subtipo_lista = [f"{nombre}: {conteo}" for nombre, conteo in subtipos_ordenados]

                    mecanismos_grupo.append({
                        "nombre": nombre_combinacion,
                        "conteo": count,
                        "total": total_grupo,
                        "porcentaje": porcentaje,
                        "subtipos": " | ".join(subtipo_lista) if subtipo_lista else None,
                        "es_combinacion": len(combinacion) > 1
                    })

                mecanismos_grupo.sort(key=lambda x: x["conteo"], reverse=True)
                mecanismos_por_grupo[grupo] = mecanismos_grupo
            return dict(mecanismos_por_grupo)

    def _group_filter_by_min(self, qs: QuerySet[Aislado, Aislado], campo_grupo: str, minimo: int = 30) -> list[str]:
        """Filtra grupos demográficos por un mínimo de 30 aislados.
        Lógica:
        1. Si el campo no está mapeado en 'mapping', agrupa directamente por 'campo_grupo' y devuelve los valores con total >= 'minimo'
        2. Si el campo está mapeado, filtra primero por los valores permitidos en el modelo asociado
        3. Cuenta los aislados por cada categoría
        4. Devuelve solo las categorías con total >= 'minimo'
        Para tipo de muestra, también permite incluir categorías con 'ignorar_minimo=True' (por ejemplo, si hiciera falta para hemocultivos)"""

        mapping = {
            "registro__ambito__ambito__nombre": (AmbitoHospital, "ambito__nombre"),
            "registro__servicio__servicio__nombre": (ServicioHospital, "servicio__nombre"),
            "registro__sexo__sexo__descripcion": (SexoHospital, "sexo__descripcion"),
            "registro__tipo_muestra__categoria__nombre": (CategoriaMuestraHospital, "nombre"),
        }

        # Caso genérico: el campo no tiene modelo asociado en el mapping (por ejemplo, 'grupo_edad')
        if campo_grupo not in mapping:
            return list(
                qs.values(campo_grupo)
                .annotate(total=Count("id"))  # cuenta por IDs
                .filter(total__gte=minimo)  # filtra >= 'minimo'
                .values_list(campo_grupo, flat=True)  # devuelve lista
            )

        # Caso mapeado: usar el modelo asociado para obtener las categorías válidas
        modelo, campo_modelo = mapping[campo_grupo]

        # 1. Obtener categorías válidas del hospital del usuario
        valores_permitidos = list(
            modelo.objects.filter(
                ignorar_informes=False,
                hospital=self.request.user.hospital
            ).values_list(campo_modelo, flat=True)
        )

        # 2. Cálculo de conteos de aislados por categoría
        conteos = (
            qs.filter(**{f"{campo_grupo}__in": valores_permitidos})
            .values(campo_grupo)
            .annotate(total=Count("id"))
            .order_by(campo_grupo)
        )

        categorias_validas = []

        # 3. Evaluamos cada categoría
        for item in conteos:
            categoria_name = item[campo_grupo]
            total = item["total"]

            if total >= minimo:
                categorias_validas.append(categoria_name)
            elif campo_grupo == "registro__tipo_muestra__categoria__nombre":

                # Excepción con el tipo de muestra con ignorar_minimo = True
                categoria = modelo.objects.get(
                    hospital=self.request.user.hospital,
                    nombre=categoria_name
                )
                if getattr(categoria, "ignorar_minimo", False):
                    categorias_validas.append(categoria_name)  # si está marcada la opción, se ignora

        return categorias_validas

    @staticmethod
    def _filter_by_values(qs: QuerySet[Aislado, Aislado], campo: str, valores: list) -> QuerySet[Aislado, Aislado]:
        """Helper para filtrar por valores: devuelve None si la lista está vacía y filtra el queryset en caso contrario"""
        if not valores:
            return qs.none()
        return qs.filter(**{f"{campo}__in": valores})  # desempaqueta el diccionario

    def _get_results_by_group(self, qs: QuerySet[Aislado, Aislado], group_field: str,
                              considerar_variantes: bool,
                              unificar_sei_con_sensibles: bool, calcular_ic: bool = False,
                              antibioticos_visibles: list[int] = None) -> dict[str, list[dict[str, Any]]]:
        """Calcula los resultados por grupo pasado en los argumentos."""
        resultados_por_grupo = defaultdict(list)

        # Obtener grupos válidos (>=30 aislados) con sus totales
        grupos_validos = dict(
            qs.values(group_field)
            .annotate(total=Count("id"))
            .filter(total__gte=30)
            .values_list(group_field, "total")
        )

        if not grupos_validos:
            return {}

        # Prefetch para evitar queries repetidas
        qs = qs.select_related(
            "microorganismo__microorganismo",
            "registro__sexo__sexo",
            "registro__ambito__ambito",
            "registro__servicio__servicio",
            "registro__tipo_muestra__categoria"
        )

        for valor, total_grupo in grupos_validos.items():
            sub_qs = qs.filter(**{group_field: valor})

            # Obtenemos los resultados de % de sensibilidad para cada grupo
            resultados = self._get_results(
                sub_qs, considerar_variantes, unificar_sei_con_sensibles,
                calcular_ic=calcular_ic,
                antibioticos_visibles=antibioticos_visibles
            )

            if resultados:
                # Agregamos el total de cada grupo que fue anotado: el número de aislados en total. Puede que NO todos
                # tengan resultados para un antibiótico en cuestión
                for resultado in resultados:
                    resultado["total_grupo"] = total_grupo
                    # resultado['total'] que viene de _get_results() se mantiene como el total de pruebas
                    # para ese antibiótico (puede haber menos que total del grupo)

                resultados_por_grupo[valor] = resultados

        return dict(resultados_por_grupo)

    def _get_results_by_sex_and_age(self, qs: QuerySet[Aislado, Aislado], considerar_variantes: bool,
                                    unificar_sei_con_sensibles: bool, calcular_ic: bool = False,
                                    antibioticos_visibles: list = None):
        """Calcula los resultados por grupos formados por sexo y edad. Devuelve un diccionario con las distintas categorías
        por sexo y edad como claves y una lista de diccionarios con el nombre del antibiótico y datos de sensibilidad, IC95,
        orden en el informe y si necesita asterisco"""
        resultados_por_grupo = {}

        # Grupos de sexo y edad
        combinaciones = [
            ("Mujer", "<15", {"registro__edad__lt": 15}),
            ("Mujer", "15-70", {"registro__edad__gte": 15, "registro__edad__lte": 70}),
            ("Mujer", ">70", {"registro__edad__gt": 70}),
            ("Hombre", "<15", {"registro__edad__lt": 15}),
            ("Hombre", "15-70", {"registro__edad__gte": 15, "registro__edad__lte": 70}),
            ("Hombre", ">70", {"registro__edad__gt": 70}),
        ]

        # Conteos de todas las combinaciones
        conteos_cache = {}

        # anotación de los grupos de edad
        qs_con_grupos = qs.annotate(
            grupo_edad=Case(
                When(registro__edad__lt=15, then=Value("<15")),
                When(registro__edad__lte=70, then=Value("15-70")),
                When(registro__edad__gt=70, then=Value(">70")),
                output_field=CharField()
            )
        )

        # obtenemos los conteos
        conteos = (
            qs_con_grupos
            .values("registro__sexo__sexo__descripcion", "grupo_edad")
            .annotate(total=Count("id"))
        )

        for item in conteos:
            sexo = item["registro__sexo__sexo__descripcion"]
            edad = item["grupo_edad"]
            total = item["total"]
            # montamos el diccionario {tupla(sexo, edad): total}
            key = (sexo, edad)
            conteos_cache[key] = total

        # Procesar solo combinaciones con >= 30 aislados
        for sexo, edad, filtros_edad in combinaciones:
            key = (sexo, edad)
            if conteos_cache.get(key, 0) < 30:
                continue

            sub_qs = qs.filter(
                registro__sexo__sexo__descripcion=sexo,
                **filtros_edad
            )

            resultados = self._get_results(
                sub_qs,
                considerar_variantes,
                unificar_sei_con_sensibles,
                calcular_ic=calcular_ic,
                antibioticos_visibles=antibioticos_visibles
            )

            if resultados:
                total_grupo_real = conteos_cache.get(key, 0)
                for resultado in resultados:
                    resultado["total_grupo"] = total_grupo_real

                edad_label = {"<15": "<15 años", "15-70": "15–70 años", ">70": ">70 años"}[edad]
                clave = f"{sexo} {edad_label}"
                resultados_por_grupo[clave] = resultados

        return resultados_por_grupo

    def _get_arm_sexo_edad(self, qs: QuerySet[Aislado, Aislado]) -> dict[str, list[dict[str, Any]]]:
        """Realiza los cálculos necesarios para la generación de datos de los mecanismos de resistencia encontrados
         en el periodo filtrado, para las combinaciones de sexo y edad. Devuelve un diccionario con las categorías por
         sexo y edad como claves y una lista de diccionarios con información sobre el nombre del mecanismo, contaje,
         porcentaje, total y subtipos encontrados para el mecanismo"""

        mecanismos_por_grupo = {}

        # Combinaciones sexo y edad
        combinaciones = [
            ("Mujer", "<15", {"registro__edad__lt": 15}),
            ("Mujer", "15-70", {"registro__edad__gte": 15, "registro__edad__lte": 70}),
            ("Mujer", ">70", {"registro__edad__gt": 70}),
            ("Hombre", "<15", {"registro__edad__lt": 15}),
            ("Hombre", "15-70", {"registro__edad__gte": 15, "registro__edad__lte": 70}),
            ("Hombre", ">70", {"registro__edad__gt": 70}),
        ]

        # Conteos de todas las combinaciones
        qs_con_grupos = qs.annotate(
            grupo_edad=Case(
                When(registro__edad__lt=15, then=Value("<15")),
                When(registro__edad__lte=70, then=Value("15-70")),
                When(registro__edad__gt=70, then=Value(">70")),
                output_field=CharField()
            )
        )

        # obtenemos los conteos
        conteos = (
            qs_con_grupos
            .values("registro__sexo__sexo__descripcion", "grupo_edad")
            .annotate(total=Count("id"))
        )

        conteos_cache = {}
        for item in conteos:
            sexo = item["registro__sexo__sexo__descripcion"]
            edad = item["grupo_edad"]
            total = item["total"]
            # montamos el diccionario {tupla(sexo, edad): total}
            key = (sexo, edad)
            conteos_cache[key] = total

        # Procesar combinaciones válidas
        for sexo, edad, filtros_edad in combinaciones:
            key = (sexo, edad)
            if conteos_cache.get(key, 0) < 30:
                continue

            sub_qs = qs.filter(
                registro__sexo__sexo__descripcion=sexo,
                **filtros_edad
            )

            total_sub_qs = sub_qs.count()

            mecanismos = self._get_arm(sub_qs, total_sub_qs)  # obtenemos los mecanismos asociados (list[dict])
            if mecanismos:
                edad_label = {"<15": "<15 años", "15-70": "15–70 años", ">70": ">70 años"}[edad]
                clave = f"{sexo} {edad_label}"
                mecanismos_por_grupo[clave] = mecanismos

        return mecanismos_por_grupo

    @staticmethod
    def _get_previous_period_queryset(hospital: Hospital, microorganismo: MicroorganismoHospital,
                                      fecha_inicial_anterior: date,
                                      fecha_final_anterior: date,
                                      servicio_filtro=None,
                                      categoria_muestra_filtro=None,
                                      necesita_mecanismos=False) -> QuerySet[Aislado, Aislado] | None:
        """
        Obtenemos la queryset de Aislados para el periodo inmediatamente anterior al analizado.
        """

        # Queryset
        qs = (
            Aislado.objects
            .select_related(
                "registro__sexo__sexo",
                "registro__ambito__ambito",
                "registro__servicio__servicio",
                "registro__tipo_muestra__categoria",
                "microorganismo__microorganismo"
            )
            .filter(
                hospital=hospital,
                microorganismo=microorganismo,
                registro__fecha__range=[fecha_inicial_anterior, fecha_final_anterior]
            )
        )

        # Añadir prefetch si es necesario
        if necesita_mecanismos:
            qs = qs.prefetch_related(
                "mecanismos_resistencia__mecanismo",
                "subtipos_resistencia__subtipo_mecanismo"
            )

        # Deduplicación por paciente
        qs_anotado = qs.annotate(
            row_num=Window(
                expression=RowNumber(),
                partition_by=[F("registro__nh_hash")],
                order_by=F("registro__fecha").asc()
            )
        )

        # Extraemos IDs
        ids_primer_aislado = list(qs_anotado.filter(row_num=1).values_list("id", flat=True))

        if not ids_primer_aislado:
            return None

        # Crea queryset limpio
        qs_filtrados = Aislado.objects.filter(id__in=ids_primer_aislado)

        # Aplicamos filtros opcionales
        if servicio_filtro:
            qs_filtrados = qs_filtrados.filter(registro__servicio=servicio_filtro)
        if categoria_muestra_filtro:
            qs_filtrados = qs_filtrados.filter(registro__tipo_muestra__categoria=categoria_muestra_filtro)

        # Excluimos demográficos ignorados
        qs_filtrados = qs_filtrados.filter(
            registro__ambito__ignorar_informes=False,
            registro__servicio__ignorar_informes=False,
            registro__sexo__ignorar_informes=False,
            registro__tipo_muestra__categoria__ignorar_informes=False
        )

        return qs_filtrados if qs_filtrados.exists() else None

    @staticmethod
    def _compare_with_previous_period(resultados_actuales: list[dict], resultados_anteriores: list[dict],
                                      unificar_sei_con_sensibles: bool = True) -> list[dict]:
        """Compara resultados actuales con el periodo anterior y añade flechas si el p-valor está
        por debajo del nivel de significación alfa=0.05 para un test de proporciones.
        Utiliza para este fin el método 'proportions_test'"""

        # Si no hay resultados para el periodo anterior devuelve el campo 'tendencia' con cadena vacía
        if not resultados_anteriores:
            for r in resultados_actuales:
                r["tendencia"] = ""
            return resultados_actuales

        # Diccionario de búsqueda por los nombres de antibióticos
        anterior_dict = {r["nombre"]: r for r in resultados_anteriores}

        # Comparar cada antibiótico
        for r_actual in resultados_actuales:
            nombre = r_actual["nombre"]

            if nombre not in anterior_dict:
                r_actual["tendencia"] = ""
                continue

            r_anterior = anterior_dict[nombre]

            # Si NO se consideran SEI como sensibles, usar S+I para la comparación
            if not unificar_sei_con_sensibles:
                sensibles_actual = r_actual["sensibles"] + r_actual.get("sei", 0)
                sensibles_anterior = r_anterior["sensibles"] + r_anterior.get("sei", 0)
            else:
                # Si se consideran, usar directamente 'sensibles' que ya incluye I
                sensibles_actual = r_actual["sensibles"]
                sensibles_anterior = r_anterior["sensibles"]

            # Test de proporciones
            r_actual["tendencia"] = proportions_test(
                sensibles_actual=sensibles_actual,
                total_actual=r_actual["total"],
                sensibles_anterior=sensibles_anterior,
                total_anterior=r_anterior["total"]
            )

        return resultados_actuales

    @staticmethod
    def _compare_mechs_with_previous_period(mecanismos_actuales: list[dict],
                                            mecanismos_anteriores: list[dict]) -> list[dict]:
        """Compara mecanismos actuales con los del periodo anterior y añade flechas si el p-valor está
        por debajo del nivel de significación alfa=0.05 para un test de proporciones.
        Utiliza para este fin el método 'proportions_test'"""

        # Si no hay resultados para el periodo anterior devuelve el campo 'tendencia' con cadena vacía
        if not mecanismos_anteriores:
            for m in mecanismos_actuales:
                m["tendencia"] = ""
            return mecanismos_actuales

        # Diccionario de búsqueda por los nombres de los mecanismos
        anterior_dict = {m["nombre"]: m for m in mecanismos_anteriores}

        # Compara cada mecanismo
        for m_actual in mecanismos_actuales:
            nombre = m_actual["nombre"] # extraemos el nombre del mecanismo actual

            if nombre not in anterior_dict: # si no está en el periodo anterior asignamos cadena vacía a 'tendencia'
                m_actual["tendencia"] = ""
                continue

            m_anterior = anterior_dict[nombre] # si lo encontramos en el periodo anterior -> test de proporciones
                                               # y añadimos a los mecanismos actuales la tendencia obtenida

            m_actual["tendencia"] = proportions_test(
                sensibles_actual=m_actual["conteo"],
                total_actual=m_actual["total"],
                sensibles_anterior=m_anterior["conteo"],
                total_anterior=m_anterior["total"]
            )

        return mecanismos_actuales

    def _compare_groups_with_previous_period(self,
                                             resultados_por_grupo_actual: dict[str, list[dict[str, Any]]],
                                             resultados_por_grupo_anterior: dict[str, list[dict[str, Any]]],
                                             unificar_sei_con_sensibles: bool = True) \
            -> dict[str, list[dict[str, Any]]]:
        """Compara resultados por grupos con el año anterior. Utiliza los diccionarios por grupo del periodo
        actual y del periodo anterior como argumentos y devuelve el diccionario del grupo actual actualizado con la
        clave 'tendencia'
        """
        # Si no hay resultados en el periodo anterior asignamos cadena vacía al campo 'tendencia'
        if not resultados_por_grupo_anterior:
            for grupo_resultados in resultados_por_grupo_actual.values():
                for r in grupo_resultados:
                    r["tendencia"] = ""
            return resultados_por_grupo_actual

        # Comparar cada grupo
        for grupo, resultados_actuales in resultados_por_grupo_actual.items():
            # Si encontramos el grupo en los resultados anteriores los comparamos con el método interno
            # _compare_with_previous_period()
            if grupo in resultados_por_grupo_anterior:
                self._compare_with_previous_period(
                    resultados_actuales,
                    resultados_por_grupo_anterior[grupo],
                    unificar_sei_con_sensibles
                )
            # Si no lo encontramos le asignamos cadena vacía a la 'tendencia'
            else:
                for r in resultados_actuales:
                    r["tendencia"] = ""

        return resultados_por_grupo_actual

    def _compare_mechs_by_group_with_previous_period(self, mecanismos_por_grupo_actual: dict[str, list[dict]],
                                                            mecanismos_por_grupo_anterior: dict[str, list[dict]]) \
            -> dict[str, list[dict]]:
        """Compara mecanismos por grupos con el periodo anterior. Toma como argumentos el diccionario con mecanismos
        actuales por grupo y el diccionario con mecanismos del periodo anterior por grupo. Devuelve el diccionario de
        mecanismos actuales por grupo actualizado con la nueva clave 'tendencia'
        """
        # Si no hay resultados en el periodo anterior asignamos cadena vacía al campo 'tendencia'
        if not mecanismos_por_grupo_anterior:
            for grupo_mecanismos in mecanismos_por_grupo_actual.values():
                for m in grupo_mecanismos:
                    m["tendencia"] = ""
            return mecanismos_por_grupo_actual

        # Comparar cada grupo
        for grupo, mecanismos_actuales in mecanismos_por_grupo_actual.items():
            if grupo in mecanismos_por_grupo_anterior:
                # Si se encuentra el grupo en el periodo anterior aplicamos el método interno
                # _compare_mechs_with_previous_period()
                self._compare_mechs_with_previous_period(
                    mecanismos_actuales, mecanismos_por_grupo_anterior[grupo]
                )
            else:
                # Si no se encuentra, asignamos cadena vacía al campo 'tendencia'
                for m in mecanismos_actuales:
                    m["tendencia"] = ""

        return mecanismos_por_grupo_actual

    @staticmethod
    def _agregar_tendencias_vacias(*items):
        """Helper para añadir tendencias vacías a resultados y mecanismos"""
        for item in items:
            if isinstance(item, list):
                for elemento in item:
                    elemento["tendencia"] = ""
            elif isinstance(item, dict):
                for lista_items in item.values():
                    if isinstance(lista_items, list):
                        for elemento in lista_items:
                            elemento["tendencia"] = ""


    ###################################
    # Métodos de construcción del PDF
    ###################################

    def _construir_informe_pdf(
            self, microorganismo, fecha_inicial, fecha_final, resultados_global, mecanismos_global,
            resultados_por_ambito, mecanismos_por_ambito, resultados_por_servicio,
            mecanismos_por_servicio, resultados_por_sexo, mecanismos_por_sexo,
            resultados_por_edad, mecanismos_por_edad, resultados_por_muestra,
            mecanismos_por_muestra, resultados_por_sexo_edad, mecanismos_por_sexo_edad,
            unificar_sei_con_sensibles, total_aislados, hospital,
            resultados_por_ambito_ic=None, resultados_por_servicio_ic=None,
            resultados_por_sexo_ic=None, resultados_por_edad_ic=None,
            resultados_por_muestra_ic=None, resultados_por_sexo_edad_ic=None,
            mecanismos_por_ambito_ic=None, mecanismos_por_servicio_ic=None,
            mecanismos_por_sexo_ic=None, mecanismos_por_edad_ic=None,
            mecanismos_por_muestra_ic=None, mecanismos_por_sexo_edad_ic=None
    ):
        # Estilos
        estilo_titulo = estilos["Title"]
        estilo_h2 = estilos["Heading2"]
        estilo_normal = estilos["Normal"]

        elementos = []

        # Si hay un logo asociado al hospital se lo ponemos arriba a la derecha
        if hospital.logo:
            try:
                logo = Image(hospital.logo.path, width=6 * cm, height=3 * cm, kind="proportional")
                logo.hAlign = "RIGHT"
                elementos.append(logo)
            except Exception as e:
                print(f"Error cargando logo: {e}")

        # Cabecera
        elementos.append(Paragraph("Informe acumulado de sensibilidad", estilo_titulo))
        elementos.append(Paragraph(f"Hospital: {hospital.nombre}", estilo_normal))
        elementos.append(Paragraph(f"Microorganismo: {microorganismo.microorganismo.nombre}", estilo_normal))
        elementos.append(Paragraph(f"Año: {fecha_inicial.year}", estilo_normal))
        elementos.append(
            Paragraph(f"Periodo: {fecha_inicial.strftime("%d/%m/%Y")} a {fecha_final.strftime("%d/%m/%Y")}",
                      estilo_normal))
        elementos.append(Spacer(1, 12))

        # Si se consideran I como SEI advertirlo en la cabecera
        if unificar_sei_con_sensibles:
            elementos.append(Paragraph(
                "Nota: Los resultados de sensibilidad mostrados incluyen tanto interpretaciones S como I (SEI, sensible a exposición incrementada).",
                estilo_normal
            ))

        # Espacio
        elementos.append(Spacer(1, 12))

        # 1. Resultados globales
        elementos.append(Paragraph("1. Sensibilidad global", estilo_h2))

        # Aislados analizados
        elementos.append(Paragraph(f"Número total de aislados únicos analizados: {total_aislados}", estilo_normal))

        if resultados_global:
            elementos.append(self._tabla_resultados_global(resultados_global, unificar_sei_con_sensibles))
            elementos.append(Spacer(1, 12))
        else:
            elementos.append(Paragraph("No hay datos globales para este filtro.", estilo_normal))
            elementos.append(Spacer(1, 12))

        if mecanismos_global:
            elementos.append(Spacer(1, 12))
            elementos.append(self._tabla_mecanismos_global(mecanismos_global))

        elementos.append(PageBreak()) # salto de página

        # 2-7. Resúmenes por grupos
        secciones = [
            ("2. Sensibilidad por ámbito de atención", resultados_por_ambito, mecanismos_por_ambito, "Ámbito"),
            ("3. Sensibilidad por servicio clínico", resultados_por_servicio, mecanismos_por_servicio, "Servicio"),
            ("4. Sensibilidad por sexo", resultados_por_sexo, mecanismos_por_sexo, "Sexo"),
            ("5. Sensibilidad por edad", resultados_por_edad, mecanismos_por_edad, "Edad"),
            ("6. Sensibilidad por sexo y edad", resultados_por_sexo_edad, mecanismos_por_sexo_edad, "Sexo y Edad"),
            ("7. Sensibilidad por tipo de muestra", resultados_por_muestra, mecanismos_por_muestra, "Tipo de muestra"),
        ]

        # Para cada una de las páginas de las secciones 2-7 añadimos las 2 tablas y salto de página
        for titulo_seccion, resultados, mecanismos, nombre_grupo in secciones:
            elementos.append(Paragraph(titulo_seccion, estilo_h2))
            elementos.append(self._tabla_por_grupo_reportlab(
                resultados,
                nombre_grupo,
                unificar_sei_con_sensibles
            ))
            if mecanismos:
                elementos.append(Spacer(1, 12))
                elementos.append(self._tabla_mecanismos_por_grupo(mecanismos, titulo=f"Mecanismos por {nombre_grupo}"))
            elementos.append(PageBreak())

        # 8-13. Tablas con los intervalos de confianza IC95%
        secciones_ic = [
            ("8. Sensibilidad por ámbito (IC95%)", resultados_por_ambito_ic, "Ámbito"),
            ("9. Sensibilidad por servicio (IC95%)", resultados_por_servicio_ic, "Servicio"),
            ("10. Sensibilidad por sexo (IC95%)", resultados_por_sexo_ic, "Sexo"),
            ("11. Sensibilidad por edad (IC95%)", resultados_por_edad_ic, "Edad"),
            ("12. Sensibilidad por sexo y edad (IC95%)", resultados_por_sexo_edad_ic, "Sexo y Edad"),
            ("13. Sensibilidad por tipo de muestra (IC95%)", resultados_por_muestra_ic, "Tipo de muestra"),
        ]

        secciones_mecanismos_ic = [
            mecanismos_por_ambito_ic,
            mecanismos_por_servicio_ic,
            mecanismos_por_sexo_ic,
            mecanismos_por_edad_ic,
            mecanismos_por_sexo_edad_ic,
            mecanismos_por_muestra_ic,
        ]

        # Para cada una de las secciones 8-13 añadimos las 2 tablas y salto de página
        for idx, ((titulo_seccion, resultados_ic, nombre_grupo), mecanismos_ic) in enumerate(
                zip(secciones_ic, secciones_mecanismos_ic) # combinaciones de las 2 listas
        ):
            elementos.append(Paragraph(titulo_seccion, estilo_h2))

            if resultados_ic:
                tabla = self._tabla_sensibilidad_por_grupo_con_ic(
                    resultados_ic,
                    nombre_grupo,
                    unificar_sei_con_sensibles
                )
                elementos.append(tabla)
            else:
                elementos.append(Paragraph(f"No hay datos para {nombre_grupo.lower()}.", estilo_normal))

            if mecanismos_ic:
                elementos.append(Spacer(1, 12))
                tabla_mecanismos = self._tabla_mecanismos_por_grupo_con_ic(
                    mecanismos_ic,
                    titulo=f"Mecanismos por {nombre_grupo} (IC95%)"
                )
                elementos.append(tabla_mecanismos)

            elementos.append(PageBreak())

        # Leyenda al final
        elementos.extend(self._crear_pagina_leyenda())

        return elementos

    # Tablas
    def _tabla_resultados_global(self, resultados_global: list[dict[str, Any]],
                                 unificar_sei_con_sensibles: bool) -> Table:
        """Tabla global de resultados con IC95% y tendencias"""

        if unificar_sei_con_sensibles:
            # Modo S+I: Una sola columna con colores e IC95
            header = ["Antibiótico", "Sensibles / Total", "% Sensibilidad (IC95)"]
            rows = [header]

            for r in resultados_global:
                tendencia = r.get("tendencia", "")
                porcentaje_str = f"{r['porcentaje_s']}%"

                # Agregar asterisco si N < 30 y necesita_asterisco
                if r["total"] < 30 and r.get("necesita_asterisco"):
                    porcentaje_str = f"{porcentaje_str}*"

                porcentaje_completo = f"{porcentaje_str} ({r['ic_low']}–{r['ic_high']})"

                if tendencia:
                    porcentaje_completo = f"{tendencia} {porcentaje_completo}"

                fila = [
                    r["nombre"],
                    f"{r['sensibles']} / {r['total']}",
                    porcentaje_completo
                ]
                rows.append(fila)

            table = Table(rows, repeatRows=1)
            estilos_tab = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]

            # Colorear según %S (columna 2)
            for i, fila in enumerate(rows[1:], start=1):
                try:
                    texto_porcentaje = str(fila[2])
                    texto_limpio = texto_porcentaje.replace("↑", "").replace("↓", "").replace("*", "").strip()
                    valor = float(texto_limpio.split("%")[0])
                except Exception:
                    continue

                if valor >= 85:
                    color = self.verde
                elif valor >= 50:
                    color = self.amarillo
                else:
                    color = self.rojo
                estilos_tab.append(("BACKGROUND", (2, i), (2, i), color))

        else:
            # Modo S solo: Cinco columnas separadas
            header = ["Antibiótico", "S / Total", "% Sensibilidad (S)", "I / Total", "% I (SEI)",
                      "% S+I (IC95)"]
            rows = [header]

            for r in resultados_global:
                tendencia = r.get("tendencia", "")

                # Datos base
                total = r["total"]
                sensibles = r["sensibles"]  # Solo S cuando unificar_sei_con_sensibles=False
                sei = r.get("sei", 0)
                s_mas_i = sensibles + sei

                # Columna 1: S / Total
                s_total_str = f"{sensibles} / {total}"

                # Columna 2: % Sensibilidad (S solo)
                porcentaje_s_solo = r["porcentaje_s"]

                # Columna 3: I / Total
                i_total_str = f"{sei} / {total}"

                # Columna 4: % I
                porcentaje_i = r.get("porcentaje_i", 0) if r.get("porcentaje_i") is not None else 0

                # Columna 5: % S+I con IC95
                porcentaje_si = np.round(100 * s_mas_i / total, 2) if total else 0

                # Calcular IC95 para S+I
                ic_low, ic_high = calculate_ic95(s_mas_i, total) # calcula los intervalos de confianza
                ic_low = np.round(ic_low * 100, 2) # se redondean a 2 decimales
                ic_high = np.round(ic_high * 100, 2)
                porcentaje_si_completo = f"{porcentaje_si}% ({ic_low}–{ic_high})"

                # Agregar asterisco si N < 30 y necesita_asterisco
                if total < 30 and r.get("necesita_asterisco"):
                    # Insertar el asterisco después del %
                    porcentaje_si_completo = porcentaje_si_completo.replace("%", "%*", 1)

                if tendencia:
                    porcentaje_si_completo = f"{tendencia} {porcentaje_si_completo}"

                fila = [
                    r["nombre"],
                    s_total_str,
                    f"{porcentaje_s_solo}%",
                    i_total_str,
                    f"{porcentaje_i}%",
                    porcentaje_si_completo
                ]
                rows.append(fila)

            table = Table(rows, repeatRows=1)
            estilos_tab = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]

            # Colorear solo la columna S+I (columna 5) según %S+I
            for i, fila in enumerate(rows[1:], start=1):
                try:
                    texto_porcentaje = str(fila[5])
                    texto_limpio = texto_porcentaje.replace("↑", "").replace("↓", "").replace("*", "").strip()
                    valor = float(texto_limpio.split("%")[0])
                except Exception:
                    continue

                if valor >= 85:
                    color = self.verde
                elif valor >= 50:
                    color = self.amarillo
                else:
                    color = self.rojo
                estilos_tab.append(("BACKGROUND", (5, i), (5, i), color))

        table.setStyle(TableStyle(estilos_tab))
        return table

    def _tabla_mecanismos_global(self, mecanismos_global: list[dict[str, Any]]) -> Table:
        """Tabla de mecanismos globales con tendencias"""
        header = ["Mecanismo", "Frecuencia", "Porcentaje", "Subtipos"]
        rows = [header]

        for m in mecanismos_global:
            # Construir porcentaje con flecha si existe
            tendencia = m.get("tendencia", "")
            porcentaje_str = f"{m["porcentaje"]}%"

            if tendencia:
                porcentaje_str = f"{tendencia} {porcentaje_str}"

            frecuencia_str = f"{m["conteo"]}/{m["total"]}"
            subtipos_str = m.get("subtipos", "-") or "-"

            rows.append([
                m["nombre"],
                frecuencia_str,
                porcentaje_str,
                subtipos_str
            ])

        table = Table(rows, repeatRows=1)
        estilos_tab = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("BACKGROUND", (0, 1), (-1, -1), self.violeta),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        table.setStyle(TableStyle(estilos_tab))
        return table

    def _tabla_por_grupo_reportlab(self, resultados_por_grupo: dict[str, list[dict[str, Any]]],
                                   titulo: str,
                                   unificar_sei_con_sensibles: bool) -> Table | Paragraph:
        """Construye tabla para resultados por grupo"""
        normal = estilos["Normal"]
        if not resultados_por_grupo:
            return Paragraph(f"No hay datos para {titulo.lower()}.", normal)

        grupos = list(resultados_por_grupo.keys())

        # Calcular totales por grupo usando la clave 'total_grupo'
        totales_por_grupo = {}
        for grupo, resultados in resultados_por_grupo.items():
            if resultados:
                totales_por_grupo[grupo] = resultados[0].get("total_grupo",
                                                             resultados[0]["total"])  # Usar 'total_grupo' si existe,
                                                                                      # si no 'total'

        # Estilo personalizado para encabezados
        estilo_encabezado = ParagraphStyle(
            "EncabezadoColumna",
            parent=estilos["Normal"],
            fontSize=8,
            alignment=TA_CENTER,
            leading=10,
            spaceAfter=0,
            spaceBefore=0
        )

        # Estilo para nombres de antibióticos con wrapping
        estilo_antibiotico = ParagraphStyle(
            "AntibioticoCelda",
            parent=estilos["Normal"],
            fontSize=9,
            leading=10,
            alignment=TA_LEFT # alineamos a la izquierda para que no haya solapamiento del nombre
        )

        # Construimos encabezados usando Paragraph con HTML
        header = [Paragraph("<b>Antibiótico</b>", estilo_encabezado)]

        for g in grupos:
            total_grupo = totales_por_grupo.get(g, 0)
            # Usar tamaños de fuente diferentes dentro del mismo Paragraph
            header_html = f'''<b><font size="11">{g}</font></b><br/>
                              <font size="9">(%S+I)</font><br/>
                              <font size="9">(N={total_grupo})</font>'''
            header.append(Paragraph(header_html, estilo_encabezado))

        data = [header]

        antibios_con_orden = {}
        for grupo in grupos:
            for r in resultados_por_grupo[grupo]:
                nombre = r["nombre"]
                if nombre not in antibios_con_orden:
                    antibios_con_orden[nombre] = r.get("orden_informe", 999999) # fallback alto para 'orden_infome'

        # Ordenar por 'orden_informe' y luego por nombre
        antibios = sorted(
            antibios_con_orden.keys(),
            key=lambda x: (antibios_con_orden[x], x)
        )

        for nombre in antibios:
            fila = [Paragraph(nombre, estilo_antibiotico)]  # Usar Paragraph para wrapping y así alineamiento a izquierda
            for grupo in grupos:
                # busca dentro del grupo el diccionario cuyo antibiótico contenga el nombre
                item = next((r for r in resultados_por_grupo[grupo] if r["nombre"] == nombre), None)
                if item:
                    tendencia = item.get("tendencia", "")

                    # Calcular S+I si no se consideran SEI como sensibles
                    if not unificar_sei_con_sensibles:
                        total = item["total"]
                        sensibles = item["sensibles"]
                        sei = item.get("sei", 0)
                        s_mas_i = sensibles + sei
                        porcentaje_si = np.round(100 * s_mas_i / total, 2) if total else 0
                    else:
                        porcentaje_si = item["porcentaje_s"]

                    if item["total"] >= 30:
                        valor = f"{porcentaje_si}%"
                    elif item.get("necesita_asterisco"):
                        valor = f"{porcentaje_si}%*"
                    else:
                        valor = "n/a"

                    if tendencia and valor != "n/a":
                        valor = f"{tendencia} {valor}"
                else:
                    valor = "n/a"
                fila.append(valor)
            data.append(fila)

        total_width = landscape(A3)[0] - 2 * 20 * mm
        ancho_antibio = 70 * mm
        num_columnas = len(grupos)
        ancho_col = max((total_width - ancho_antibio) / max(num_columnas, 1), 25 * mm)
        colWidths = [ancho_antibio] + [ancho_col] * num_columnas

        table = Table(data, colWidths=colWidths, repeatRows=1)
        estilos_tabla = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ]

        for i, fila in enumerate(data[1:], start=1): # data[0:] es el header, partimos desde cada una de las filas
                                                    # de antibióticos
            # Obtener el nombre del antibiótico del Paragraph
            nombre_antibio = antibios[i - 1]
            for col_idx in range(1, len(fila)):
                if col_idx - 1 >= len(grupos):
                    continue # saltamos columna extra que no tenga grupo correspondiente
                grupo = grupos[col_idx - 1]

                # busca en la lista de resultados el diccionario que corresponde al antibiótico de la fila
                item = next(
                    (r for r in resultados_por_grupo.get(grupo, []) if r["nombre"] == nombre_antibio),
                    None
                )

                if item:
                    # Calcular S+I para colorear correctamente
                    if not unificar_sei_con_sensibles:
                        total = item["total"]
                        sensibles = item["sensibles"]
                        sei = item.get("sei", 0)
                        s_mas_i = sensibles + sei
                        valor = np.round(100 * s_mas_i / total, 2) if total else 0
                    else:
                        valor = item["porcentaje_s"]

                    if valor >= 85:
                        color = self.verde
                    elif valor >= 50:
                        color = self.amarillo
                    else:
                        color = self.rojo
                    estilos_tabla.append(("BACKGROUND", (col_idx, i), (col_idx, i), color))

        table.setStyle(TableStyle(estilos_tabla))
        return table

    def _tabla_sensibilidad_por_grupo_con_ic(self, resultados_por_grupo: dict[str, list[dict[str, Any]]],
                                             titulo: str, unificar_sei_con_sensibles: bool) -> Table | Paragraph:
        """Construye tabla por grupo analizado con IC95%"""
        normal = estilos["Normal"]
        if not resultados_por_grupo:
            return Paragraph(f"No hay datos para {titulo.lower()}.", normal)

        grupos = list(resultados_por_grupo.keys())

        # Calcular totales por grupo
        totales_por_grupo = {}
        for grupo, resultados in resultados_por_grupo.items():
            if resultados:
                totales_por_grupo[grupo] = resultados[0].get("total_grupo", resultados[0]["total"])

        # Estilo para encabezados
        estilo_encabezado = ParagraphStyle(
            "EncabezadoColumna",
            parent=estilos["Normal"],
            fontSize=8,
            alignment=TA_CENTER,
            leading=10,
            spaceAfter=0,
            spaceBefore=0
        )

        # Estilo para nombres de antibióticos con wrapping
        estilo_antibiotico = ParagraphStyle(
            "AntibioticoCelda",
            parent=estilos["Normal"],
            fontSize=9,
            leading=10,
            alignment=TA_LEFT
        )

        # Construir encabezados
        header = [Paragraph("<b>Antibiótico</b>", estilo_encabezado)]
        for g in grupos:
            total_grupo = totales_por_grupo.get(g, 0)
            header_html = f'''<b><font size="11">{g}</font></b><br/>
                              <font size="9">(%S+I IC95%)</font><br/>
                              <font size="9">(N={total_grupo})</font>'''
            header.append(Paragraph(header_html, estilo_encabezado))

        data = [header]

        antibios_con_orden = {}
        for grupo in grupos:
            for r in resultados_por_grupo[grupo]:
                nombre = r["nombre"]
                if nombre not in antibios_con_orden:
                    antibios_con_orden[nombre] = r.get("orden_informe", 999999)

        # Ordenar por 'orden_informe' y luego por nombre
        antibios = sorted(
            antibios_con_orden.keys(),
            key=lambda x: (antibios_con_orden[x], x)
        )

        for nombre in antibios:
            fila = [Paragraph(nombre, estilo_antibiotico)]  # Usar Paragraph para wrapping
            for grupo in grupos:
                item = next((r for r in resultados_por_grupo[grupo] if r["nombre"] == nombre), None)
                if item:
                    total = item.get("total", 0)

                    # Calcular S+I y sus IC95
                    if not unificar_sei_con_sensibles:
                        sensibles = item.get("sensibles", 0)
                        sei = item.get("sei", 0)
                        s_mas_i = sensibles + sei

                        if total > 0:
                            ic_low, ic_high = calculate_ic95(s_mas_i, total)
                            ic_low = np.round(ic_low * 100, 2)
                            ic_high = np.round(ic_high * 100, 2)
                        else:
                            ic_low = ic_high = None
                    else:
                        # Usar los IC95 que ya vienen calculados
                        ic_low = item.get("ic_low")
                        ic_high = item.get("ic_high")

                        # Si no están calculados, calcularlos
                        if ic_low is None or ic_high is None:
                            sensibles = item.get("sensibles", 0)
                            if total > 0:
                                ic_low, ic_high = calculate_ic95(sensibles, total)
                                ic_low = np.round(ic_low * 100, 2)
                                ic_high = np.round(ic_high * 100, 2)
                            else:
                                ic_low = ic_high = None

                    if ic_low is not None and ic_high is not None:
                        tendencia = item.get("tendencia", "")
                        ic_texto = f"({ic_low}–{ic_high})"

                        if item.get("necesita_asterisco"):
                            ic_texto += "*"

                        if tendencia:
                            valor = f"{tendencia} {ic_texto}"
                        else:
                            valor = ic_texto
                    else:
                        valor = "n/a"
                else:
                    valor = "n/a"
                fila.append(valor)
            data.append(fila)

        total_width = landscape(A3)[0] - 2 * 20 * mm
        ancho_antibio = 70 * mm
        num_columnas = len(grupos)
        ancho_col = max((total_width - ancho_antibio) / max(num_columnas, 1), 25 * mm)
        colWidths = [ancho_antibio] + [ancho_col] * num_columnas

        table = Table(data, colWidths=colWidths, repeatRows=1)
        estilos_tabla = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ]

        for i, fila in enumerate(data[1:], start=1):
            # Obtener el nombre del antibiótico del Paragraph
            nombre_antibio = antibios[i - 1]
            for col_idx in range(1, len(fila)):
                if col_idx - 1 >= len(grupos):
                    continue
                grupo = grupos[col_idx - 1]

                item = next(
                    (r for r in resultados_por_grupo.get(grupo, []) if r["nombre"] == nombre_antibio),
                    None
                )

                if item:
                    # Calcular S+I para colorear correctamente
                    if not unificar_sei_con_sensibles:
                        total = item["total"]
                        sensibles = item["sensibles"]
                        sei = item.get("sei", 0)
                        s_mas_i = sensibles + sei
                        valor = np.round(100 * s_mas_i / total, 2) if total else 0
                    else:
                        valor = item["porcentaje_s"]

                    if valor >= 85:
                        color = self.verde
                    elif valor >= 50:
                        color = self.amarillo
                    else:
                        color = self.rojo
                    estilos_tabla.append(("BACKGROUND", (col_idx, i), (col_idx, i), color))

        table.setStyle(TableStyle(estilos_tabla))
        return table

    def _tabla_mecanismos_por_grupo(self, mecanismos_por_grupo: dict[str, list[dict[str, Any]]],
                                    titulo="Mecanismos de resistencia") -> Table:
        """Tabla de mecanismos por grupo"""
        grupos = list(mecanismos_por_grupo.keys())
        num_cols = len(grupos) + 1

        # Estilo para título
        estilo_titulo = ParagraphStyle(
            "TituloMecanismos",
            parent=estilos["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER
        )

        # Estilo para encabezados de columnas
        estilo_encabezado = ParagraphStyle(
            "EncabezadoMecanismos",
            parent=estilos["Normal"],
            fontSize=9,
            alignment=TA_CENTER,
            leading=11
        )

        # Primera fila: título
        titulo_paragraph = Paragraph(titulo, estilo_titulo)
        data = [[titulo_paragraph] + [""] * (len(grupos))]

        # Segunda fila: headers
        header_row = [Paragraph("<b>Mecanismo</b>", estilo_encabezado)]
        for grupo in grupos:
            if mecanismos_por_grupo[grupo]:
                total_grupo = mecanismos_por_grupo[grupo][0]["total"]
                header_html = f"<b><font size='10'>{grupo}</font></b><br/><font size='9'>(N={total_grupo})</font>"
                header_row.append(Paragraph(header_html, estilo_encabezado))
            else:
                header_row.append(Paragraph(f"<b>{grupo}</b>", estilo_encabezado))

        data.append(header_row)

        # Mecanismos
        # Ordenar mecanismos por frecuencia máxima entre grupos
        mecanismos_con_frecuencia = {}

        # Recopila todos los mecanismos únicos con su frecuencia máxima
        for grupo, lista in mecanismos_por_grupo.items():
            for m in lista:
                nombre = m["nombre"]
                conteo = m["conteo"]

                # Guardamos el conteo máximo de este mecanismo entre todos los grupos
                if nombre not in mecanismos_con_frecuencia:
                    mecanismos_con_frecuencia[nombre] = conteo
                else:
                    mecanismos_con_frecuencia[nombre] = max(mecanismos_con_frecuencia[nombre], conteo)

        # Ordenar por frecuencia descendente (mayor a menor) con sorted()
        mecanismos_ordenados = sorted(
            mecanismos_con_frecuencia.keys(),
            key=lambda m: mecanismos_con_frecuencia[m],
            reverse=True # mayor a menor
        )

        for mecanismo in mecanismos_ordenados:
            fila = [mecanismo]
            for grupo in grupos:
                texto = "-"
                for m in mecanismos_por_grupo.get(grupo, []):
                    if m["nombre"] == mecanismo:
                        tendencia = m.get("tendencia", "")
                        porcentaje = f"{m["porcentaje"]}%"
                        frecuencia = f"({m["conteo"]}/{m["total"]})"

                        if tendencia:
                            texto = f"{tendencia} {porcentaje} {frecuencia}"
                        else:
                            texto = f"{porcentaje} {frecuencia}"
                        break
                fila.append(texto)
            data.append(fila)

        table = Table(data, repeatRows=2, hAlign="CENTER")
        estilos_tabla = [
            ("SPAN", (0, 0), (num_cols - 1, 0)),
            ("GRID", (0, 0), (num_cols - 1, -1), 0.25, colors.black),
            ("BACKGROUND", (0, 0), (num_cols - 1, 0), colors.lightgrey),
            ("BACKGROUND", (0, 1), (num_cols - 1, 1), colors.lightgrey),
            ("BACKGROUND", (0, 2), (num_cols - 1, -1), self.violeta),
            ("ALIGN", (0, 0), (num_cols - 1, -1), "CENTER"),
            ("VALIGN", (0, 0), (num_cols - 1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 2), (num_cols - 1, -1), 9),
            ("LEFTPADDING", (0, 0), (num_cols - 1, -1), 3),
            ("RIGHTPADDING", (0, 0), (num_cols - 1, -1), 3),
            ("TOPPADDING", (0, 0), (num_cols - 1, 1), 5),
            ("BOTTOMPADDING", (0, 0), (num_cols - 1, 1), 5),
        ]
        table.setStyle(TableStyle(estilos_tabla))
        return table


    def _tabla_mecanismos_por_grupo_con_ic(self, mecanismos_por_grupo: dict[str, list[dict[str, Any]]],
                                           titulo: str ="Mecanismos de resistencia")-> Table | Paragraph:
        """Tabla de mecanismos con IC95%"""
        normal = estilos["Normal"]
        if not mecanismos_por_grupo:
            return Paragraph("No hay datos de mecanismos.", normal)

        grupos = list(mecanismos_por_grupo.keys())
        num_cols = len(grupos) + 1

        # Estilos
        estilo_titulo = ParagraphStyle(
            "TituloMecanismos",
            parent=estilos["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER
        )

        estilo_encabezado = ParagraphStyle(
            "EncabezadoMecanismos",
            parent=estilos["Normal"],
            fontSize=8,
            alignment=TA_CENTER,
            leading=10
        )

        # Primera fila: título
        titulo_paragraph = Paragraph(titulo, estilo_titulo)
        data = [[titulo_paragraph] + [""] * (len(grupos))]

        # Segunda fila: headers
        header_row = [Paragraph("<b>Mecanismo</b>", estilo_encabezado)]
        for grupo in grupos:
            if mecanismos_por_grupo[grupo]:
                total_grupo = mecanismos_por_grupo[grupo][0]["total"]
                header_html = f'''<b><font size="10">{grupo}</font></b><br/>
                                  <font size="9">(IC95%)</font><br/>
                                  <font size="9">(N={total_grupo})</font>'''
                header_row.append(Paragraph(header_html, estilo_encabezado))
            else:
                header_html = f"<b>{grupo}</b><br/>(IC95%)"
                header_row.append(Paragraph(header_html, estilo_encabezado))

        data.append(header_row)

        # Mecanismos
        # Ordenar mecanismos por frecuencia máxima entre grupos
        mecanismos_con_frecuencia = {}

        # Recopila todos los mecanismos únicos con su frecuencia máxima
        for grupo, lista in mecanismos_por_grupo.items():
            for m in lista:
                nombre = m["nombre"]
                conteo = m["conteo"]

                # Guardamos el conteo máximo de este mecanismo entre todos los grupos
                if nombre not in mecanismos_con_frecuencia:
                    mecanismos_con_frecuencia[nombre] = conteo
                else:
                    mecanismos_con_frecuencia[nombre] = max(mecanismos_con_frecuencia[nombre], conteo)

        # Ordenar por frecuencia descendente (mayor a menor)
        mecanismos_ordenados = sorted(
            mecanismos_con_frecuencia.keys(),
            key=lambda m: mecanismos_con_frecuencia[m],
            reverse=True
        )

        for mecanismo in mecanismos_ordenados:
            fila = [mecanismo]
            for grupo in grupos:
                texto = "-"
                for m in mecanismos_por_grupo.get(grupo, []):
                    if m["nombre"] == mecanismo:
                        tendencia = m.get("tendencia", "")
                        porcentaje = f"{m["porcentaje"]}%"
                        frecuencia = f"({m["conteo"]}/{m["total"]})"

                        if tendencia:
                            texto = f"{tendencia} {porcentaje} {frecuencia}"
                        else:
                            texto = f"{porcentaje} {frecuencia}"
                        break
                fila.append(texto)
            data.append(fila)

        table = Table(data, repeatRows=2, hAlign="CENTER")
        estilos_tabla = [
            ("SPAN", (0, 0), (num_cols - 1, 0)),
            ("GRID", (0, 0), (num_cols - 1, -1), 0.25, colors.black),
            ("BACKGROUND", (0, 0), (num_cols - 1, 0), colors.lightgrey),
            ("BACKGROUND", (0, 1), (num_cols - 1, 1), colors.lightgrey),
            ("BACKGROUND", (0, 2), (num_cols - 1, -1), self.violeta),
            ("ALIGN", (0, 0), (num_cols - 1, -1), "CENTER"),
            ("VALIGN", (0, 0), (num_cols - 1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 2), (num_cols - 1, -1), 9),
            ("LEFTPADDING", (0, 0), (num_cols - 1, -1), 3),
            ("RIGHTPADDING", (0, 0), (num_cols - 1, -1), 3),
            ("TOPPADDING", (0, 0), (num_cols - 1, 1), 5),
            ("BOTTOMPADDING", (0, 0), (num_cols - 1, 1), 5),
        ]
        table.setStyle(TableStyle(estilos_tabla))
        return table

    def _crear_pagina_leyenda(self) -> list[Paragraph | Spacer | Table]:
        """Crea página con leyenda de colores"""
        estilo_titulo = estilos["Heading1"]
        estilo_normal = estilos["Normal"]
        elementos: list[Paragraph | Spacer | Table] = [Paragraph("Leyenda de colores", estilo_titulo),
                                                       Spacer(1, 12)]

        data = [
            ["", ">85% de las cepas sensibles"],
            ["", "50-85% de las cepas sensibles"],
            ["", "<50% de las cepas sensibles"]
        ]
        col_widths = [2 * cm, 12 * cm]
        tabla_leyenda = Table(data, colWidths=col_widths)
        estilos_tabla = [
            ("BACKGROUND", (0, 0), (0, 0), self.verde),
            ("BACKGROUND", (0, 1), (0, 1), self.amarillo),
            ("BACKGROUND", (0, 2), (0, 2), self.rojo),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (1, 0), (1, -1), 12),
            ("LEFTPADDING", (1, 0), (1, -1), 10),
            ("RIGHTPADDING", (1, 0), (1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]
        tabla_leyenda.setStyle(TableStyle(estilos_tabla))
        elementos.append(tabla_leyenda)
        elementos.append(Spacer(1, 30))
        elementos.append(Paragraph(
            "Nota: Los valores marcados con asterisco (*) han sido calculados con menos de 30 observaciones.",
            estilo_normal
        ))

        return elementos
