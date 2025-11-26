from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import statsmodels.api as sm
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db.models import Window, F, Q, Exists, OuterRef, QuerySet
from django.db.models.functions import RowNumber
from django.http import JsonResponse
from django.shortcuts import redirect, render
from pygam import LinearGAM, s
from scipy.special import expit, logit
from scipy.stats import norm, shapiro, jarque_bera
from sklearn.metrics import mean_absolute_error as mae
from sklearn.metrics import mean_squared_error
from statsmodels.stats.diagnostic import het_breuschpagan, het_white, acorr_ljungbox
from statsmodels.stats.stattools import durbin_watson

from Base.global_models import Antibiotico, Hospital
from Base.models import (Aislado, PerfilAntibiogramaHospital, MecanismoResistenciaHospital, \
                         SubtipoMecanismoResistenciaHospital, PerfilAntibioticoHospital, EucastVersion,
                         MicroorganismoHospital, AntibioticoHospital, \
                         ResultadoAntibiotico, ReinterpretacionAntibiotico, SexoHospital, AmbitoHospital,
                         ServicioHospital,
                         CategoriaMuestraHospital)
from .forms import ReinterpretacionForm
from .utils import (smape, adaptative_config_gam, build_linear_regression_plot, build_gam_plot, build_acf_plot)


# Vista del formulario de reinterpretación de resultados
def reinterpretar_resultados(request):
    if request.method == "POST":
        form = ReinterpretacionForm(request.POST, hospital=request.user.hospital)

        if not form.is_valid():
            # Si no es AJAX, añadir mensajes al framework de mensajes de Django
            for field, errors in form.errors.items():
                if field == "__all__":  # serían errores generales de formulario, no de campo
                    for error in errors:
                        messages.error(request, error)
                else:
                    field_label = form.fields[field].label or field
                    for error in errors:
                        messages.error(request, f"{field_label}: {error}")

            return render(request, "Tendencias/reinterpretacion_form.html", {"form": form})

        if form.is_valid():
            fecha_inicio = form.cleaned_data["fecha_inicio"]
            fecha_fin = form.cleaned_data["fecha_fin"]
            version_eucast = form.cleaned_data["version_eucast"]
            microorganismo = form.cleaned_data.get("microorganismo")

            # Filtrar aislados con select_related para optimizar
            aislados_qs = Aislado.objects.filter(
                registro__fecha__range=(fecha_inicio, fecha_fin),
                hospital=request.user.hospital  # Filtrar por hospital del usuario
            ).select_related(
                "microorganismo__microorganismo__grupo_eucast",
                "registro__sexo__sexo",
                "registro__tipo_muestra__tipo_muestra"
            )

            if microorganismo:
                aislados_qs = aislados_qs.filter(microorganismo=microorganismo)

            total_aislados = aislados_qs.count()
            total_reinterpretaciones = 0

            # Barra de progreso
            for i, aislado in enumerate(aislados_qs, 1):
                print(f"Procesando aislado {i}/{total_aislados}...")
                reinterpretaciones = ReinterpretacionAntibiotico.reinterpretar(
                    aislado=aislado,
                    version_eucast=version_eucast
                )
                total_reinterpretaciones += len(reinterpretaciones)

            messages.success(
                request,
                f"Reinterpretación completada: {total_aislados} aislados, "
                f"{total_reinterpretaciones} resultados reinterpretados."
            )
            return redirect("Tendencias:reinterpretar_resultados")

    else:
        form = ReinterpretacionForm(hospital=request.user.hospital)

    return render(request, "Tendencias/reinterpretacion_form.html", {"form": form})


# Vista del formulario de análisis de tendencias con modelos de regresión
def vista_tendencias_regresion(request):
    """Vista para analizar tendencias con modelos de regresión."""
    hospital = request.user.hospital

    # Fechas por defecto
    fecha_inicio_default = date.today() - timedelta(days=730)
    fecha_fin_default = date.today()

    # Valores iniciales del contexto
    contexto = {
        "hospital": hospital,
        "versiones_eucast": EucastVersion.objects.all().order_by("-anyo"),

        "microorganismos": MicroorganismoHospital.objects.filter(  # Microorganismos filtrados por hospital
            hospital=hospital
        ).select_related("microorganismo").order_by("microorganismo__nombre"),

        "sexos": SexoHospital.objects.filter(hospital=hospital, ignorar_informes=False),
        "ambitos": AmbitoHospital.objects.filter(hospital=hospital, ignorar_informes=False),
        "servicios": ServicioHospital.objects.filter(hospital=hospital, ignorar_informes=False),
        "tipos_muestra": CategoriaMuestraHospital.objects.filter(hospital=hospital, ignorar_informes=False),

        "fecha_inicio": fecha_inicio_default,
        "fecha_fin": fecha_fin_default,
        "agrupacion": "trimestre",
        "edad_min": "0",
        "edad_max": "120",

        # Listas vacías por defecto para los campos AJAX
        "antibioticos": [],
        "mecanismos": [],
        "subtipos": []
    }

    # Si el request es GET, render inicial vacío con el contexto por defecto
    if request.method != "POST":
        return render(request, "Tendencias/tendencias.html", contexto)

    # Cuando no es GET-> envío del formulario, request de tipo POST
    form_data = request.POST  # contenido del formulario

    # Capturar valores seleccionados
    micro_id = form_data.get("microorganismo", "")
    antibio_id = form_data.get("antibiotico", "")
    mec_id = form_data.get("mec_resistencia", "")
    sub_mec_id = form_data.get("sub_mec_resistencia", "")

    # Actualización del contexto con lo enviado por el formulario
    contexto.update({
        # Campos simples (texto, select, date)
        "microorganismo_selected": micro_id,
        "version_eucast_selected": form_data.get("version_eucast", ""),
        "antibiotico_selected": antibio_id,

        # Hay que extraer la fecha a partir de la cadena del formulario
        "fecha_inicio": datetime.strptime(form_data.get("fecha_inicio"), "%Y-%m-%d").date(),
        "fecha_fin": datetime.strptime(form_data.get("fecha_fin"), "%Y-%m-%d").date(),

        "agrupacion": form_data.get("agrupacion", "trimestre"),
        "edad_min": form_data.get("edad_min", "0"),
        "edad_max": form_data.get("edad_max", "120"),

        # Campos multi-select (getlist) -> listas vacías como fallback
        # Todos los valores son enteros, las IDs de los objetos
        "sexo_selected": [int(x) for x in form_data.getlist("sexo", []) if x],
        "ambito_selected": [int(x) for x in form_data.getlist("ambito", []) if x],
        "servicio_selected": [int(x) for x in form_data.getlist("servicio", []) if x],
        "tipo_muestra_selected": [int(x) for x in form_data.getlist("tipo_muestra", []) if x],
        "mec_resistencia_selected": mec_id,
        "sub_mec_resistencia_selected": sub_mec_id
    })

    # Pre-cargar opciones de los campos rellenados por endpoints AJAX, según lo seleccionado
    # Si hay microorganismo seleccionado, cargar antibióticos y mecanismos
    if micro_id:
        try:
            microorganismo_obj = MicroorganismoHospital.objects.get(
                id=micro_id,
                hospital=hospital
            )
            grupo_eucast = microorganismo_obj.microorganismo.grupo_eucast

            # Cargar antibióticos según el perfil del grupo EUCAST
            perfil = PerfilAntibiogramaHospital.objects.filter(
                grupo_eucast=grupo_eucast
            )

            # Actualización de los contextos
            # Cargar los antibióticos asociados al microorganismo por perfil
            contexto["antibioticos"] = (
                AntibioticoHospital.objects.filter(
                    perfilantibiogramahospital__in=perfil
                )
                .select_related("antibiotico")
                .order_by("antibiotico__nombre")
            )

            # Cargar mecanismos según el grupo EUCAST
            contexto["mecanismos"] = (
                MecanismoResistenciaHospital.objects.filter(
                    mecanismo__grupos_eucast=grupo_eucast,
                )
                .select_related("mecanismo")
                .order_by("mecanismo__nombre")
                .distinct()
            )

        except MicroorganismoHospital.DoesNotExist:
            pass

    # Si hay un mecanismo seleccionado, cargar sus subtipos
    if mec_id:
        try:
            mecanismo_obj = MecanismoResistenciaHospital.objects.get(
                id=mec_id,
                hospital=hospital
            )

            # Cargar subtipos relacionados para este mecanismo
            contexto["subtipos"] = (
                SubtipoMecanismoResistenciaHospital.objects.filter(
                    hospital=hospital,
                    subtipo_mecanismo__mecanismo=mecanismo_obj.mecanismo
                )
                .select_related("subtipo_mecanismo")
                .order_by("subtipo_mecanismo__nombre")
                .distinct()
            )

        except MecanismoResistenciaHospital.DoesNotExist:
            pass

    # Versión de EUCAST
    version_id = form_data.get("version_eucast")

    # Validar campos requeridos
    # Se debe seleccionar siempre microorganismo y versión de EUCAST
    if not all([micro_id, version_id]):
        messages.error(request, "Por favor, seleccione microorganismo y versión EUCAST.")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Se debe seleccionar antibiótico o mecanismo (al menos uno)
    if not antibio_id and not mec_id:
        messages.error(request, "Por favor, seleccione un antibiótico o un mecanismo de resistencia.")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Una vez obtenida la información requerida para el análisis de tendencias
    try:
        fecha_inicio = contexto["fecha_inicio"]
        fecha_fin = contexto["fecha_fin"]
        version_eucast = EucastVersion.objects.get(id=version_id)
        microorganismo = MicroorganismoHospital.objects.get(id=micro_id, hospital=hospital)

        # Obtenemos el antibiótico
        antibiotico = None
        if antibio_id:
            antibiotico = AntibioticoHospital.objects.get(id=antibio_id, hospital=hospital)

        # Invocamos el resto de objetos de variables clínico-epidemiológicas y demográficas
        sexos = SexoHospital.objects.filter(id__in=contexto["sexo_selected"])
        edad_min = contexto["edad_min"]
        edad_max = contexto["edad_max"]
        ambitos = AmbitoHospital.objects.filter(id__in=contexto["ambito_selected"])
        servicios = ServicioHospital.objects.filter(id__in=contexto["servicio_selected"])
        tipo_muestras = CategoriaMuestraHospital.objects.filter(id__in=contexto["tipo_muestra_selected"])

        # Obtener mecanismo y subtipo si fueron seleccionados
        mecanismo = None
        subtipo_mecanismo = None
        if mec_id:
            try:
                mecanismo = MecanismoResistenciaHospital.objects.get(id=mec_id, hospital=hospital)
            except MecanismoResistenciaHospital.DoesNotExist:
                pass

        if sub_mec_id:
            try:
                subtipo_mecanismo = SubtipoMecanismoResistenciaHospital.objects.get(id=sub_mec_id, hospital=hospital)
            except SubtipoMecanismoResistenciaHospital.DoesNotExist:
                pass

    except Exception as e:
        messages.error(request, f"Error en los parámetros: {str(e)}")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Validación de fechas
    if fecha_inicio > fecha_fin:
        messages.error(request, "La fecha de inicio debe ser anterior a la fecha de fin.")
        return render(request, "Tendencias/tendencias.html", contexto)

    periodos = calculate_periods(fecha_inicio, fecha_fin, contexto["agrupacion"])

    # Se requieren, al menos, 3 puntos para un análisis de regresión linear
    if not periodos or len(periodos) < 3:
        messages.warning(request, "Se necesitan al menos 3 periodos para realizar análisis de regresión.")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Obtener datos según modo: antibiótico o mecanismo
    if antibiotico:
        datos_tendencia, avisos, sin_reinterpretados = get_tendency_data(
            hospital=hospital,
            microorganismo=microorganismo,
            antibiotico=antibiotico,
            version_eucast=version_eucast,
            periodos=periodos,

            sexos=sexos,
            edad_min=edad_min,
            edad_max=edad_max,
            ambitos=ambitos,
            servicios=servicios,
            tipo_muestras=tipo_muestras,

            mecanismo=mecanismo,
            subtipo=subtipo_mecanismo
        )
        titulo_analisis = f"{antibiotico.antibiotico.nombre}"
    else:
        # Modo mecanismo: análisis de prevalencia del mecanismo
        datos_tendencia, avisos, sin_reinterpretados = get_mech_tendendy_data(
            hospital=hospital,
            microorganismo=microorganismo,
            version_eucast=version_eucast,
            periodos=periodos,
            sexos=sexos,
            edad_min=edad_min,
            edad_max=edad_max,
            ambitos=ambitos,
            servicios=servicios,
            tipo_muestras=tipo_muestras,
            mecanismo=mecanismo,
            subtipo=subtipo_mecanismo
        )
        titulo_analisis = mecanismo.mecanismo.nombre if mecanismo else "Mecanismo"

    if sin_reinterpretados:
        messages.error(request, "Se deben generar previamente reinterpretaciones según la versión de EUCAST elegida.")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Crear el DataFrame con los datos de tendencia
    df = create_tendency_dataframe(datos_tendencia)

    # Si no hay datos, volver a la vista con mensaje de error
    if df.empty or df["total"].sum() == 0:
        messages.error(request, "No hay suficientes datos para realizar el análisis.")
        return render(request, "Tendencias/tendencias.html", contexto)

    # Realizar análisis de regresión
    resultados_regresion = build_regression_analysis(df,
                                                     contexto["agrupacion"],
                                                     titulo_analisis=titulo_analisis,
                                                     modo_mecanismo=(antibiotico is None))

    resultados_lista = []
    for modelo_nombre in ["lineal", "gam"]:
        res = resultados_regresion.get(modelo_nombre)
        if not res:
            continue

        # Si encontramos errores, lo mostramos en la UI
        # sin este bloque resulta difícil ver qué pasó, porqué no hay resultado
        if "error" in res:
            resultados_lista.append({
                "nombre": modelo_nombre.capitalize(),
                "error": res["error"]
            })
        else:
            # Preparamos para pasar al contexto
            resultados_lista.append({
                "nombre": modelo_nombre.capitalize(),
                "r2": res.get("r2", "N/A"),
                "mae": res.get("mae", "N/A"),
                "rmse": res.get("rmse", "N/A"),
                "edof": res.get("edof", "N/A"),
                "lambda": res.get("lambda", "N/A"),
                "n_splines": res.get("n_splines", "N/A"),
                "p_valor": res.get("p_valor", "N/A"),
                "pred_siguiente": res.get("pred_siguiente", "N/A"),
                "pred_lower": res.get("pred_lower", "N/A"),
                "pred_upper": res.get("pred_upper", "N/A"),
                "tasa_variacion": res.get("tasa_variacion", "N/A"),
                "tasa_variacion_ic_lower": res.get("tasa_variacion_ic_lower", "N/A"),
                "tasa_variacion_ic_upper": res.get("tasa_variacion_ic_upper", "N/A"),
                "tendencia": res.get("tendencia", "N/A"),
                "grafico": res.get("grafico", None),
                "diagnosticos": res.get("diagnosticos", {}),
                "intercepto": res.get("intercepto", "N/A"),
                "pendiente": res.get("pendiente", "N/A"),
                "p_valor_f": res.get("p_valor_f", "N/A"),
                "f_statistic": res.get("f_statistic", "N/A"),
                "significativo": res.get("significativo", False),
                "aic": res.get("aic", "N/A"),
                "bic": res.get("bic", "N/A"),
                "cv_mae": res.get("cv_mae", "N/A"),
                "cv_mae_std": res.get("cv_mae_std", "N/A"),
                "cv_rmse": res.get("cv_rmse", "N/A"),
                "cv_rmse_std": res.get("cv_rmse_std", "N/A"),
                "cv_smape": res.get("cv_smape", "N/A"),
                "cv_smape_std": res.get("cv_smape_std", "N/A"),
                "cv_num_folds": res.get("cv_num_folds", 0),
            })

        estadisticas_globales = get_global_statistics(datos_tendencia)

        # Actualizamos el contexto para devolverlo a la vista
        contexto.update({
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "version_eucast": version_eucast,
            "microorganismo": microorganismo,
            "antibiotico": antibiotico,
            "mecanismo_analizado": mecanismo,
            "subtipo_analizado": subtipo_mecanismo,
            "modo_mecanismo": (antibiotico is None),
            "titulo_analisis": titulo_analisis,
            "agrupacion": contexto["agrupacion"],
            "datos_tendencia": datos_tendencia,
            "estadisticas_globales": estadisticas_globales,
            "resultados_lista": resultados_lista,
            "resultados_regresion": resultados_regresion,
            "avisos": avisos,
            "mostrar_resultados": True,
        })

    return render(request, "Tendencias/tendencias.html", contexto)


# Funciónes auxiliares de la vista
def calculate_periods(fecha_inicio: date, fecha_fin: date, agrupacion: str) -> list[dict]:
    """Calcula los periodos según agrupación."""
    periodos = []

    if agrupacion == "trimestre":
        delta = relativedelta(months=3)
    elif agrupacion == "semestre":
        delta = relativedelta(months=6)
    else:
        delta = relativedelta(years=1)

    ultimo_label = None
    fecha_actual = fecha_inicio

    # Recorremos hasta llegar a la fecha final
    while fecha_actual <= fecha_fin:

        # fin del bloque actual
        fin_periodo = min(fecha_actual + delta - timedelta(days=1), fecha_fin)

        if agrupacion == "trimestre":
            trimestre = ((fecha_actual.month - 1) // 3) + 1
            label = f"Q{trimestre} {fecha_actual.year}"  # para formar Q1 año, Q2 año, Q3 año, Q4 año
        elif agrupacion == "semestre":
            semestre = 1 if fecha_actual.month <= 6 else 2
            label = f"S{semestre} {fecha_actual.year}"  # para formar S1 año, S2 año
        else:
            label = str(fecha_actual.year)

        # se añade un nuevo periodo sólo si el label cambia
        if label != ultimo_label:
            periodos.append({
                "inicio": fecha_actual,
                "fin": fin_periodo,
                "label": label
            })
            ultimo_label = label

        # avanza la fecha al siguiente bloque
        fecha_actual = fin_periodo + timedelta(days=1)

    return periodos


def get_tendency_data(hospital: Hospital,
                      microorganismo: MicroorganismoHospital,
                      antibiotico: AntibioticoHospital, version_eucast: EucastVersion,
                      periodos: list[dict], sexos: QuerySet[SexoHospital], edad_min: int, edad_max: int,
                      ambitos: QuerySet[AmbitoHospital], servicios: QuerySet[ServicioHospital],
                      tipo_muestras: QuerySet[CategoriaMuestraHospital], mecanismo: MecanismoResistenciaHospital | None,
                      subtipo: SubtipoMecanismoResistenciaHospital | None):
    """Obtiene datos de tendencia para cada periodo."""
    datos = []
    avisos = {
        "total_copiados": 0,
        "periodos_con_copiados": [],
        "periodos_sin_datos": []
    }

    # Rango global para deduplicación
    fecha_inicio_global = periodos[0]["inicio"]
    fecha_fin_global = periodos[-1]["fin"]
    sin_reinterpretados = True

    for periodo in periodos:
        inicio = periodo["inicio"]
        fin = periodo["fin"]

        # Obtenemos los conteos de las categorías clínicas y contadores copiados
        conteos_originales, conteos_reinterpretados, info_copiados, tiene_reinterpretados = \
            count_results(
                hospital, microorganismo, antibiotico, version_eucast, inicio, fin,
                sexos, edad_min, edad_max, ambitos, servicios, tipo_muestras, mecanismo,
                subtipo,
                fecha_inicio_global=fecha_inicio_global,
                fecha_fin_global=fecha_fin_global
            )

        if tiene_reinterpretados:
            sin_reinterpretados = False

        # Unificamos los conteos para cada categoría clínica
        conteos_totales = {
            "S": conteos_originales["S"] + conteos_reinterpretados["S"],
            "I": conteos_originales["I"] + conteos_reinterpretados["I"],
            "R": conteos_originales["R"] + conteos_reinterpretados["R"],
        }

        total = sum(conteos_totales.values())

        # Cálculo de porcentajes
        if total > 0:
            porcentajes = {
                "S": round((conteos_totales["S"] / total) * 100, 1),
                "I": round((conteos_totales["I"] / total) * 100, 1),
                "R": round((conteos_totales["R"] / total) * 100, 1),
            }
        else:
            porcentajes = {"S": 0, "I": 0, "R": 0}
            avisos["periodos_sin_datos"].append(periodo["label"])

        tiene_copiados = info_copiados["num_copiados"] > 0

        # Si tiene copiados añadir a los avisos de la UI
        if tiene_copiados:
            avisos["total_copiados"] += info_copiados["num_copiados"]
            avisos["periodos_con_copiados"].append(periodo["label"])

        datos.append({
            "periodo": periodo["label"],
            "inicio": inicio,
            "fin": fin,
            "conteos": conteos_totales,
            "porcentajes": porcentajes,
            "total": total,
            "num_originales": sum(conteos_originales.values()),
            "num_reinterpretados": sum(conteos_reinterpretados.values()),
            "tiene_copiados": tiene_copiados,
            "num_copiados": info_copiados["num_copiados"],
        })

    # Devolvemos la tupla de datos, avisos y boolean de interpretados
    return datos, avisos, sin_reinterpretados


def count_results(hospital: Hospital,
                  microorganismo: MicroorganismoHospital,
                  antibiotico: AntibioticoHospital, version_eucast: EucastVersion,
                  fecha_inicio: date, fecha_fin: date,
                  sexos: QuerySet[SexoHospital] = None,
                  edad_min: int | None = None,
                  edad_max: int | None = None,
                  ambitos: QuerySet[AmbitoHospital] | None = None,
                  servicios: QuerySet[ServicioHospital] = None,
                  tipo_muestras: QuerySet[CategoriaMuestraHospital] = None,
                  mecanismo: MecanismoResistenciaHospital | None = None,
                  subtipo_mecanismo: SubtipoMecanismoResistenciaHospital | None = None,
                  considerar_variantes: bool = False,
                  fecha_inicio_global: date = None,
                  fecha_fin_global: date = None) -> tuple[dict, dict, dict, bool]:
    """
    Cuenta resultados originales y reinterpretaciones considerando
    solo 1 aislado por paciente (nh_hash) en el periodo.
    - Excluye nh_hash nulos
    - Excluye resistencias intrínsecas
    - Filtra por perfil de visibilidad del hospital
    - Aplica lógica de variantes
    Devuelve una tupla con (conteos_originales, conteos_reinterpretados, info_copiados)
    """
    # PASO 1: Identificar aislados únicos por paciente (nh_hash)
    # Si se proporciona rango global, deduplicar sobre ese rango completo
    # para evitar contar el mismo paciente múltiples veces en diferentes periodos

    fecha_dedup_inicio = fecha_inicio_global if fecha_inicio_global else fecha_inicio
    fecha_dedup_fin = fecha_fin_global if fecha_fin_global else fecha_fin

    # Queryset base con todos los filtros para deduplicación
    qs_dedup = Aislado.objects.filter(
        microorganismo=microorganismo,
        hospital=hospital,
        registro__fecha__gte=fecha_dedup_inicio,
        registro__fecha__lte=fecha_dedup_fin,
        registro__sexo__ignorar_informes=False,
        registro__ambito__ignorar_informes=False,
        registro__servicio__ignorar_informes=False,
        registro__tipo_muestra__categoria__ignorar_informes=False,
    ).exclude(registro__nh_hash__isnull=True)

    # Aplica filtros dinámicos opcionales
    if edad_min is not None:
        qs_dedup = qs_dedup.filter(registro__edad__gte=edad_min)
    if edad_max is not None:
        qs_dedup = qs_dedup.filter(registro__edad__lte=edad_max)
    if sexos:
        qs_dedup = qs_dedup.filter(registro__sexo__in=sexos)
    if ambitos:
        qs_dedup = qs_dedup.filter(registro__ambito__in=ambitos)
    if servicios:
        qs_dedup = qs_dedup.filter(registro__servicio__in=servicios)
    if tipo_muestras:
        qs_dedup = qs_dedup.filter(registro__tipo_muestra__categoria__in=tipo_muestras)
    if mecanismo:
        qs_dedup = qs_dedup.filter(mecanismos_resistencia=mecanismo)
    if subtipo_mecanismo:
        qs_dedup = qs_dedup.filter(subtipos_resistencia=subtipo_mecanismo)

    # Window function para obtener el más antiguo por "nh_hash" en el rango de deduplicación
    qs_anotado = qs_dedup.annotate(
        row_num=Window(
            expression=RowNumber(),
            partition_by=[F("registro__nh_hash")],
            order_by=F("registro__fecha").asc()  # el más antiguo
        )
    )

    # Obtenemos los IDs únicos en lista, considerando el rango completo
    aislados_unicos_ids = list(
        qs_anotado.filter(row_num=1).values_list("id", flat=True)
    )

    # Filtramos por periodo usando los IDs de la lista anterior
    aislados_en_periodo = [
        a_id for a_id in aislados_unicos_ids
        if Aislado.objects.filter(
            id=a_id,
            registro__fecha__gte=fecha_inicio,
            registro__fecha__lte=fecha_fin
        ).exists()
    ]

    # Resistencias intrínsecas y perfil
    # Obtenemos resistencias intrínsecas para este microorganismo
    resistencias_intrinsecas_ids = microorganismo.microorganismo.lista_ids_resistencia_intrinseca

    # Obtenemos los antibióticos VISIBLES según el PERFIL del hospital
    perfil = (
        PerfilAntibiogramaHospital.objects
        .filter(
            hospital=hospital,
            grupo_eucast=microorganismo.microorganismo.grupo_eucast
        )
        .prefetch_related("perfilantibioticohospital_set")
        .first()
    )

    if perfil:
        antibioticos_visibles = (
            PerfilAntibioticoHospital.objects
            .filter(perfil=perfil, mostrar_en_informes=True)
            .values_list("antibiotico_hospital", flat=True)
        )
    else:
        # Si no hay perfil, no hay antibióticos visibles
        antibioticos_visibles = []

    # Marcamos las variantes (si aplica)
    tiene_variantes = Exists(
        Antibiotico.objects.filter(parent=OuterRef("antibiotico__antibiotico"))
    )

    # PASO 2: Contar desde ResultadoAntibiotico (originales)
    resultados_originales_qs = (
        ResultadoAntibiotico.objects
        .annotate(tiene_variantes=tiene_variantes)  # anotamos las variantes
        .filter(
            antibiotico=antibiotico,
            aislado__id__in=aislados_en_periodo,  # Usamos los aislados filtrados por periodo
            aislado__version_eucast=version_eucast,
            interpretacion__in=["S", "I", "R"],
            antibiotico__id__in=antibioticos_visibles,  # Seleccionamos sólo los visibles
        )
        .exclude(
            antibiotico__antibiotico__id__in=resistencias_intrinsecas_ids  # Excluir intrínsecas
        )
    )

    # Aplicamos el filtro de variantes si corresponde
    if considerar_variantes:
        resultados_originales_qs = resultados_originales_qs.filter(
            Q(antibiotico__antibiotico__es_variante=True) |
            Q(antibiotico__antibiotico__es_variante=False, tiene_variantes=False)
        )
    else:
        resultados_originales_qs = resultados_originales_qs.filter(
            antibiotico__antibiotico__es_variante=False
        )

    # Resultados de interpretación
    resultados_originales = (resultados_originales_qs
                             .values_list("interpretacion", flat=True))

    conteos_originales = {"S": 0, "I": 0, "R": 0}

    for interp in resultados_originales:
        if interp in conteos_originales:
            conteos_originales[interp] += 1  # Actualizamos contador de resultados originales

    # PASO 3: Contar desde ReinterpretacionAntibiotico. Básicamente, lo mismo de antes, pero para las reinterpretaciones.
    reinterpretaciones_qs = (
        ReinterpretacionAntibiotico.objects
        .filter(
            resultado_original__aislado__id__in=aislados_en_periodo,  # Usar los filtrados por periodo
            resultado_original__antibiotico=antibiotico,
            version_eucast=version_eucast,
            interpretacion_nueva__in=["S", "I", "R"],
            resultado_original__antibiotico__id__in=antibioticos_visibles,  # Sólo visibles
        )
        .exclude(
            resultado_original__aislado__version_eucast=version_eucast
        )
        .exclude(
            resultado_original__antibiotico__antibiotico__id__in=resistencias_intrinsecas_ids  # Excluir intrínsecas
        )
        .select_related(
            "resultado_original__aislado",
            "resultado_original__aislado__registro",
            "resultado_original__antibiotico__antibiotico",
        )
    )

    # Aplicamos filtro de variantes si corresponde
    if considerar_variantes:
        reinterpretaciones_qs = reinterpretaciones_qs.filter(
            Q(resultado_original__antibiotico__antibiotico__es_variante=True) |
            Q(resultado_original__antibiotico__antibiotico__es_variante=False) &
            ~Exists(
                Antibiotico.objects.filter(
                    parent=OuterRef("resultado_original__antibiotico__antibiotico_id")
                )
            )
        )
    else:
        reinterpretaciones_qs = reinterpretaciones_qs.filter(
            resultado_original__antibiotico__antibiotico__es_variante=False
        )

    reinterpretaciones = reinterpretaciones_qs

    tiene_reinterpretados = reinterpretaciones.exists()

    conteos_reinterpretados = {"S": 0, "I": 0, "R": 0}
    num_copiados = 0
    total_reinterpretaciones = 0

    # Actualizamos contadores de reinterpretados y copiados
    for reinterp in reinterpretaciones:
        total_reinterpretaciones += 1

        if reinterp.interpretacion_nueva in conteos_reinterpretados:
            conteos_reinterpretados[reinterp.interpretacion_nueva] += 1

        # Verificar si es copiado (no reinterpretado)
        if not reinterp.es_reinterpretado:
            num_copiados += 1

    porcentaje_copiados = (
        round((num_copiados / total_reinterpretaciones) * 100, 1)
        if total_reinterpretaciones > 0
        else 0
    )

    info_copiados = {
        "num_copiados": num_copiados,
        "total_reinterpretaciones": total_reinterpretaciones,
        "porcentaje_copiados": porcentaje_copiados
    }

    # PASO 4: Devuelve la tupla
    return conteos_originales, conteos_reinterpretados, info_copiados, tiene_reinterpretados


def get_mech_tendendy_data(hospital: Hospital, microorganismo: MicroorganismoHospital,
                           version_eucast: EucastVersion, periodos: list[dict],
                           sexos: QuerySet[SexoHospital], edad_min: int, edad_max: int,
                           ambitos: QuerySet[AmbitoHospital], servicios: QuerySet[ServicioHospital],
                           tipo_muestras: QuerySet[CategoriaMuestraHospital],
                           mecanismo: MecanismoResistenciaHospital | None,
                           subtipo: SubtipoMecanismoResistenciaHospital | None) -> tuple[list, dict, bool]:
    """
    Obtiene datos de prevalencia de mecanismo de resistencia por periodo.
    Calcula el porcentaje de aislados que tienen el mecanismo sobre el total.
    """
    sin_reinterpretados = True
    datos = []
    avisos = {
        "total_copiados": 0,
        "periodos_con_copiados": [],
        "periodos_sin_datos": []
    }

    fecha_inicio_global = periodos[0]["inicio"] if periodos else None
    fecha_fin_global = periodos[-1]["fin"] if periodos else None

    for periodo in periodos:
        inicio = periodo["inicio"]
        fin = periodo["fin"]

        # Contar aislados CON el mecanismo y totales
        conteos, periodo_sin_reinterpretados = count_results_with_mech(
            hospital=hospital,
            microorganismo=microorganismo,
            version_eucast=version_eucast,
            fecha_inicio=inicio,
            fecha_fin=fin,
            sexos=sexos,
            edad_min=edad_min,
            edad_max=edad_max,
            ambitos=ambitos,
            servicios=servicios,
            tipo_muestras=tipo_muestras,
            mecanismo=mecanismo,
            subtipo=subtipo,
            fecha_inicio_global=fecha_inicio_global,
            fecha_fin_global=fecha_fin_global
        )

        if not periodo_sin_reinterpretados:
            sin_reinterpretados = False

        total = conteos["total"]
        con_mecanismo = conteos["con_mecanismo"]
        sin_mecanismo = total - con_mecanismo

        # Calculamos los porcentajes
        if total > 0:
            porcentaje_con = round((con_mecanismo / total) * 100, 1)
            porcentaje_sin = round((sin_mecanismo / total) * 100, 1)
        else:
            porcentaje_con = 0
            porcentaje_sin = 0
            avisos["periodos_sin_datos"].append(periodo["label"])

        # Adaptar estructura para compatibilidad con gráficos
        # Usamos "S" para aislados CON mecanismo, "R" para SIN mecanismo
        datos.append({
            "periodo": periodo["label"],
            "inicio": inicio,
            "fin": fin,
            "conteos": {
                "S": con_mecanismo,  # CON mecanismo
                "I": 0,
                "R": sin_mecanismo  # SIN mecanismo
            },
            "porcentajes": {
                "S": porcentaje_con,  # % CON mecanismo
                "I": 0,
                "R": porcentaje_sin  # % SIN mecanismo
            },
            "total": total,
            "num_originales": total,
            "num_reinterpretados": 0,
            "tiene_copiados": False,
            "num_copiados": 0,
        })

    return datos, avisos, sin_reinterpretados  # Devolvemos la tupla


def count_results_with_mech(hospital: Hospital,
                            microorganismo: MicroorganismoHospital,
                            version_eucast: EucastVersion,
                            fecha_inicio: date,
                            fecha_fin: date,
                            sexos: QuerySet[SexoHospital], edad_min: int, edad_max: int,
                            ambitos: QuerySet[AmbitoHospital], servicios: QuerySet[ServicioHospital],
                            tipo_muestras: QuerySet[CategoriaMuestraHospital],
                            mecanismo: MecanismoResistenciaHospital | None,
                            subtipo: SubtipoMecanismoResistenciaHospital | None,
                            fecha_inicio_global: date = None,
                            fecha_fin_global: date = None) -> tuple[dict, bool]:
    """
    Cuenta aislados únicos (por nh_hash) con y sin el mecanismo especificado.
    Considera ResultadoAntibiotico para la versión EUCAST seleccionada, y ReinterpretacionAntibiotico
    hacia atrás.
    Devuelve un diccionario con contajes dict: {"total": int, "con_mecanismo": int} y el bool sin_reinterpretados
    """
    # Rango para deduplicación
    fecha_dedup_inicio = fecha_inicio_global if fecha_inicio_global else fecha_inicio
    fecha_dedup_fin = fecha_fin_global if fecha_fin_global else fecha_fin

    # PASO 1: Obtener TODOS los aislados únicos
    qs_todos_base = Aislado.objects.filter(
        microorganismo=microorganismo,
        hospital=hospital,
        registro__fecha__gte=fecha_dedup_inicio,
        registro__fecha__lte=fecha_dedup_fin,
        registro__sexo__ignorar_informes=False,
        registro__ambito__ignorar_informes=False,
        registro__servicio__ignorar_informes=False,
        registro__tipo_muestra__categoria__ignorar_informes=False,
    ).exclude(registro__nh_hash__isnull=True)

    # Aplicar filtros demográficos
    if edad_min is not None:
        qs_todos_base = qs_todos_base.filter(registro__edad__gte=edad_min)
    if edad_max is not None:
        qs_todos_base = qs_todos_base.filter(registro__edad__lte=edad_max)
    if sexos:
        qs_todos_base = qs_todos_base.filter(registro__sexo__in=sexos)
    if ambitos:
        qs_todos_base = qs_todos_base.filter(registro__ambito__in=ambitos)
    if servicios:
        qs_todos_base = qs_todos_base.filter(registro__servicio__in=servicios)
    if tipo_muestras:
        qs_todos_base = qs_todos_base.filter(registro__tipo_muestra__categoria__in=tipo_muestras)

    # Deduplicar por nh_hash (el más antiguo)
    qs_todos_anotado = qs_todos_base.annotate(
        row_num=Window(
            expression=RowNumber(),
            partition_by=[F("registro__nh_hash")],
            order_by=F("registro__fecha").asc()
        )
    )

    todos_aislados_unicos_ids = list(
        qs_todos_anotado.filter(row_num=1).values_list("id", flat=True)
    )

    # Filtrar por periodo actual
    todos_aislados_en_periodo = [
        aid for aid in todos_aislados_unicos_ids
        if Aislado.objects.filter(
            id=aid,
            registro__fecha__gte=fecha_inicio,
            registro__fecha__lte=fecha_fin
        ).exists()
    ]

    # PASO 2: Calcular el TOTAL (denominador)
    # Aislados que tienen datos para la version_eucast
    # (originales o reinterpretados)

    # Aislados originales con version_eucast coincidente
    aislados_originales_ids = set(
        Aislado.objects.filter(
            id__in=todos_aislados_en_periodo,
            version_eucast=version_eucast
        ).values_list("id", flat=True)
    )

    # Aislados con reinterpretaciones para esta version_eucast
    aislados_reinterpretados_ids = set(
        ReinterpretacionAntibiotico.objects.filter(
            resultado_original__aislado__id__in=todos_aislados_en_periodo,
            version_eucast=version_eucast
        ).exclude(
            resultado_original__aislado__version_eucast=version_eucast
        ).values_list(
            "resultado_original__aislado_id",
            flat=True
        ).distinct()
    )

    sin_reinterpretados = len(aislados_reinterpretados_ids) == 0

    # Total = originales + reinterpretados (sin duplicados)
    todos_aislados_con_datos = aislados_originales_ids | aislados_reinterpretados_ids
    total_aislados = len(todos_aislados_con_datos)

    # PASO 3: Contar aislados CON el mecanismo (numerador)
    if not mecanismo and not subtipo:
        # Si no hay mecanismo especificado, se cuentan todos
        return {
            "total": total_aislados,
            "con_mecanismo": total_aislados
        }, sin_reinterpretados

    # Filtrar los aislados que tienen datos por el mecanismo
    qs_con_mecanismo = Aislado.objects.filter(
        id__in=list(todos_aislados_con_datos)
    )

    if mecanismo:
        qs_con_mecanismo = qs_con_mecanismo.filter(
            mecanismos_resistencia=mecanismo
        )

    if subtipo:
        qs_con_mecanismo = qs_con_mecanismo.filter(
            subtipos_resistencia=subtipo
        )

    con_mecanismo = qs_con_mecanismo.count()

    return {
        "total": total_aislados,
        "con_mecanismo": con_mecanismo
    }, sin_reinterpretados


def create_tendency_dataframe(datos_tendencia: list[dict]) -> pd.DataFrame:
    """Crea pandas.DataFrame con datos de tendencia."""
    data = []
    for i, dato in enumerate(datos_tendencia):
        if dato["total"] > 0:
            data.append({
                "periodo_num": i,
                "periodo_label": dato["periodo"],
                "porcentaje_si": dato["porcentajes"]["S"] + dato["porcentajes"]["I"],
                "contaje_si": dato["conteos"]["S"] + dato["conteos"]["I"],
                "total": dato["total"],
                "fin": dato["fin"]
            })
    return pd.DataFrame(data)


# ANÁLISIS DE REGRESIÓN
def build_regression_analysis(df: pd.DataFrame, agrupacion: str, titulo_analisis: str = "",
                              modo_mecanismo: bool = False) -> dict:
    """Realiza análisis con dos modelos de regresión: Lineal y GAM."""
    if len(df) < 3:
        return {"error": "Se necesitan al menos 3 periodos con datos"}

    X = df["periodo_num"].values.reshape(-1, 1)
    y = df["porcentaje_si"].values
    n = len(df)

    resultados = {}

    # Etiquetas según modo
    if modo_mecanismo:
        ylabel = "% Prevalencia del mecanismo"
        titulo_grafico_lineal = f"Tendencia Lineal - {titulo_analisis}"
        titulo_grafico_gam = f"Tendencia GAM - {titulo_analisis}"
    else:
        ylabel = "% Sensibles + Intermedios"
        titulo_grafico_lineal = f"Tendencia Lineal - {titulo_analisis}"
        titulo_grafico_gam = f"Tendencia GAM (Generalized Additive Model) - {titulo_analisis}"

    # Validación cruzada mediante rolling origin y selección de hiperparámetros por GridSearch - Capacidad PREDICTIVA
    validacion_cv = foward_chaining_expanding_window_cv(df)

    # REGRESIÓN LINEAL
    try:
        X_const = sm.add_constant(X)
        modelo_lin = sm.OLS(y, X_const).fit()

        cv_metrics_lin = validacion_cv.get("lineal", {})

        if "rmse" in cv_metrics_lin and cv_metrics_lin["rmse"]:
            cv_rmse = np.nanmean(cv_metrics_lin["rmse"])
            cv_smape = np.nanmean(cv_metrics_lin["smape"])
            print(f"  Capacidad predictiva (CV): RMSE={cv_rmse:.2f}, SMAPE={cv_smape:.2f}%")

        y_pred_lin = modelo_lin.predict(X_const)

        # Métricas IN-SAMPLE - Bondad de ajuste
        mae_lin_in_sample = mae(y, y_pred_lin)
        rmse_lin_in_sample = np.sqrt(mean_squared_error(y, y_pred_lin))
        smape_lin_in_sample = smape(y, y_pred_lin)

        print(modelo_lin.summary())

        # p-valor de la pendiente (coeficiente de periodo_num)
        p_valor_pendiente = modelo_lin.pvalues[1]

        # Intervalos de confianza (es numpy array, no DataFrame)
        conf_int = modelo_lin.conf_int(alpha=0.05)

        # F-statistic (significación global del modelo)
        f_statistic = modelo_lin.fvalue
        p_valor_f = modelo_lin.f_pvalue

        # Tests de diagnóstico
        diagnosticos_lineal = {}
        try:
            # Test de Jarque-Bera para normalidad de residuos
            jb_stat, jb_p = jarque_bera(modelo_lin.resid)
            diagnosticos_lineal["jarque_bera_p"] = round(float(jb_p), 4)
            diagnosticos_lineal["jarque_bera_stat"] = round(float(jb_stat), 4)
        except Exception as e:
            print(f"Error en Jarque-Bera (lineal): {e}")

        try:
            # Test de Shapiro-Wilk para normalidad de residuos
            if n <= 50:
                sw_stat, sw_p = shapiro(modelo_lin.resid)
                diagnosticos_lineal["shapiro_p"] = round(float(sw_p), 4)
                diagnosticos_lineal["shapiro_stat"] = round(float(sw_stat), 4)
        except Exception as e:
            print(f"Error en Shapiro-Wilk: {e}")

        try:
            # Test de Breusch-Pagan para homocedasticidad
            bp_test = het_breuschpagan(modelo_lin.resid, modelo_lin.model.exog)
            diagnosticos_lineal["breusch_pagan_p"] = round(float(bp_test[1]), 4)
            diagnosticos_lineal["breusch_pagan_stat"] = round(float(bp_test[0]), 4)
        except Exception as e:
            print(f"Error en Breusch-Pagan: {e}")

        try:
            # Test de Durbin-Watson para autocorrelación
            dw_stat = durbin_watson(modelo_lin.resid)
            diagnosticos_lineal["durbin_watson"] = round(float(dw_stat), 4)
        except Exception as e:
            print(f"Error en Durbin-Watson: {e}")

        try:
            # Test de Ljung–Box para autocorrelación (varios lags)
            # Usamos lags hasta min(10, n/5) para evitar sobreajuste en muestras pequeñas
            # Número de lags: mínimo 10 o n//5
            lb_lags = min(10, max(1, n // 5))

            # Ljung-Box
            lb_result = acorr_ljungbox(modelo_lin.resid, lags=lb_lags, return_df=True)

            # Extraemos estadístico y p-valor del primer lag
            lb_stat = lb_result["lb_stat"].iloc[-1]
            lb_p = lb_result["lb_pvalue"].iloc[-1]

            diagnosticos_lineal["ljung_box_lag"] = lb_lags
            diagnosticos_lineal["ljung_box_stat"] = round(float(lb_stat), 4)
            diagnosticos_lineal["ljung_box_p"] = round(float(lb_p), 4)

            print("Ljung-Box p:", lb_p)
        except Exception as e:
            print(f"Error en Ljung-Box: {e}")

        try:
            # White"s Test para heterocedasticidad (más general que Breusch-Pagan)
            white_test = het_white(modelo_lin.resid, modelo_lin.model.exog)
            diagnosticos_lineal["white_p"] = round(float(white_test[1]), 4)
            diagnosticos_lineal["white_stat"] = round(float(white_test[0]), 4)
        except Exception as e:
            print(f"Error en White test: {e}")

        diagnosticos_lineal["acf_plot"] = build_acf_plot(modelo_lin.resid, n,
                                                         title="ACF de los residuos de la regresión linear")

        # Intervalo de confianza para el coeficiente de determinación - aproximación por el coeficiente de correlación r
        r2 = modelo_lin.rsquared
        r = np.sqrt(r2) if modelo_lin.params[1] >= 0 else -np.sqrt(r2)

        # Transformación de Fisher: z = 0.5 * ln(1+r/1-r)
        z = 0.5 * np.log((1 + r) / (1 - r))
        se = 1 / np.sqrt(n - 3)
        z_low = z - norm.ppf(0.975) * se
        z_up = z + norm.ppf(0.975) * se

        # Volver a r con la inversa: (e^2z) - 1 / (e^2z) + 1
        r_low = (np.exp(2 * z_low) - 1) / (np.exp(2 * z_low) + 1)
        r_up = (np.exp(2 * z_up) - 1) / (np.exp(2 * z_up) + 1)

        # Intervalo para R2
        R2_low = r_low ** 2
        R2_up = r_up ** 2

        diagnosticos_lineal["R2_ic_low"] = round(float(R2_low), 4)
        diagnosticos_lineal["R2_ic_up"] = round(float(R2_up), 4)

        # Tasa variación -> transformación logit
        # https://stats.oarc.ucla.edu/other/mult-pkg/faq/general/faq-how-do-i-interpret-odds-ratios-in-logistic-regression/?utm_source=chatgpt.com
        epsilon = 1e-6
        p = np.clip(y / 100, epsilon, 1 - epsilon)
        y_logit = np.log(p / (1 - p))  # para ajustar el modelo logit

        modelo_logit = sm.OLS(y_logit, X_const).fit()
        pendiente_logit = modelo_logit.params[1]  # la pendiente es el cambio en log-odds por unidad de tiempo
        p_logit = modelo_logit.pvalues[1]

        ic_logit = modelo_logit.conf_int()  # Esto es numpy array
        ic_pendiente_logit_lower = float(ic_logit[1, 0])  # Fila 1 (pendiente), columna 0 (lower)
        ic_pendiente_logit_upper = float(ic_logit[1, 1])  # Fila 1 (pendiente), columna 1 (upper)

        tasa_variacion = (np.exp(pendiente_logit) - 1) * 100  # tasa de variación por unidad de tiempo
        tasa_variacion_ic = (
            (np.exp(ic_pendiente_logit_lower) - 1) * 100,
            (np.exp(ic_pendiente_logit_upper) - 1) * 100
        )

        # Predicción
        periodo_siguiente = np.array([[df["periodo_num"].max() + 1]])
        periodo_siguiente_const = sm.add_constant(periodo_siguiente, has_constant="add")
        pred_siguiente_lin = modelo_lin.predict(periodo_siguiente_const)[0]

        # Intervalo de predicción
        try:
            pred_ols = modelo_lin.get_prediction(periodo_siguiente_const)
            pred_interval = pred_ols.summary_frame(alpha=0.05)

            # Intervalo de CONFIANZA (más estrecho)
            ci_lower_lin = max(0, float(pred_interval["mean_ci_lower"].values[0]))
            ci_upper_lin = min(100, float(pred_interval["mean_ci_upper"].values[0]))

            # Intervalos de PREDICCIÓN
            pred_lower_lin = max(0, float(pred_interval["obs_ci_lower"].values[0]))
            pred_upper_lin = min(100, float(pred_interval["obs_ci_upper"].values[0]))
        except:
            pred_lower_lin = None
            pred_upper_lin = None

        # X extendido para toda la línea (histórico + predicción)
        X_extended = np.arange(df["periodo_num"].min(), df["periodo_num"].max() + 2).reshape(-1, 1)
        X_extended_const = sm.add_constant(X_extended, has_constant="add")

        # Predicciones para toda la línea
        y_pred_extended = modelo_lin.predict(X_extended_const)

        # Intervalos de PREDICCIÓN para toda la línea
        try:
            pred_ols_extended = modelo_lin.get_prediction(X_extended_const)
            pred_interval_extended = pred_ols_extended.summary_frame(alpha=0.05)

            # Extraer límites y asegurar que estén en [0, 100]
            pred_lower_extended = np.clip(pred_interval_extended["obs_ci_lower"].values, 0, 100)
            pred_upper_extended = np.clip(pred_interval_extended["obs_ci_upper"].values, 0, 100)

            print(f"   IP 95% en predicción: [{pred_lower_extended[-1]:.2f}, {pred_upper_extended[-1]:.2f}]")
        except Exception as e:
            print(f"   Error calculando intervalos: {e}")
            pred_lower_extended = None
            pred_upper_extended = None

        # Gráfico
        grafico_lin = build_linear_regression_plot(
            df, y_pred_lin, pred_siguiente_lin,
            X_extended, pred_lower_extended, pred_upper_extended,
            agrupacion, titulo_grafico_lineal, ylabel
        )

        if p_valor_pendiente < 0.05:
            if modelo_lin.params[1] > 0:
                tendencia = "ascendente"
            else:
                tendencia = "descendente"
        else:
            tendencia = "estable (no significativa)"

        resultados["lineal"] = {
            "r2": round(modelo_lin.rsquared, 4),
            "mae": round(mae_lin_in_sample, 2),
            "rmse": round(rmse_lin_in_sample, 4),
            "smape": round(smape_lin_in_sample, 4),
            "p_valor": round(p_valor_pendiente, 4),
            "p_valor_f": round(p_valor_f, 4),
            "f_statistic": round(f_statistic, 4),
            "pred_siguiente": round(pred_siguiente_lin, 2),
            "pred_lower": round(pred_lower_lin, 2),
            "pred_upper": round(pred_upper_lin, 2),
            "tasa_variacion": round(tasa_variacion, 4),
            "tasa_variacion_ic_lower": round(tasa_variacion_ic[0], 4),
            "tasa_variacion_ic_upper": round(tasa_variacion_ic[1], 4),
            "grafico": grafico_lin,
            "pendiente": round(modelo_lin.params[1], 4),
            "intercepto": round(modelo_lin.params[0], 4),
            "tendencia": tendencia,
            "significativo": p_valor_pendiente < 0.05,
            "aic": round(modelo_lin.aic, 2),
            "bic": round(modelo_lin.bic, 2),
            "diagnosticos": diagnosticos_lineal,

            # Métricas de validación cruzada
            "cv_mae": cv_metrics_lin.get("mae_mean", "N/A"),
            "cv_mae_std": cv_metrics_lin.get("mae_std", "N/A"),
            "cv_rmse": cv_metrics_lin.get("rmse_mean", "N/A"),
            "cv_rmse_std": cv_metrics_lin.get("rmse_std", "N/A"),
            "cv_smape": cv_metrics_lin.get("smape_mean", "N/A"),
            "cv_smape_std": cv_metrics_lin.get("smape_std", "N/A"),
            "cv_num_folds": cv_metrics_lin.get("num_folds_validos", 0),
        }

    except Exception as e:
        import traceback
        resultados["lineal"] = {"error": f"Error en regresión lineal: {str(e)}\n{traceback.format_exc()}"}

    # GAM (Generalized Additive Model)
    try:
        # Calcular configuración adaptativa para GAM
        n_splines, spline_order = adaptative_config_gam(len(df))
        cv_metrics_gam = validacion_cv.get("gam", {})
        lam = cv_metrics_gam["best_lambda"]
        print(f"\n=== GAM Config ===")
        print(f"N observaciones: {len(df)}")
        print(f"N splines: {n_splines}")
        print(f"Spline order: {spline_order}")
        print(f"Lambda: {lam}")

        # Transformación logit
        y_percent = y / 100.0
        epsilon = 1e-6
        y_percent_safe = np.clip(y_percent, epsilon, 1 - epsilon)
        y_logit = logit(y_percent_safe)

        # Ajustar GAM con configuración adaptativa
        gam = LinearGAM(s(0, n_splines=n_splines, spline_order=spline_order), lam=lam).fit(X.flatten(), y_logit)

        print(gam.summary())

        # Predicciones
        y_gam_logit = gam.predict(X.flatten())
        y_gam = expit(y_gam_logit) * 100.0

        # R², MAE y RMSE
        r2_gam = gam.statistics_["pseudo_r2"]["explained_deviance"]
        residuals_gam = y - y_gam

        mae_gam = mae(y, y_gam)
        rmse_gam = np.sqrt(np.mean(residuals_gam ** 2))

        # EDOF
        edof = gam.statistics_["edof"]

        # AIC
        aic_gam = gam.statistics_["AIC"]

        # Diagnósticos
        diagnosticos_gam = {}

        try:
            jb_stat, jb_p = jarque_bera(residuals_gam)
            diagnosticos_gam["jarque_bera_p"] = round(float(jb_p), 4)
            diagnosticos_gam["jarque_bera_stat"] = round(float(jb_stat), 4)
        except Exception as e:
            print(f"Error en Jarque-Bera (GAM): {e}")

        try:
            if n <= 50:
                sw_stat, sw_p = shapiro(residuals_gam)
                diagnosticos_gam["shapiro_p"] = round(float(sw_p), 4)
                diagnosticos_gam["shapiro_stat"] = round(float(sw_stat), 4)
        except Exception as e:
            print(f"Error en Shapiro-Wilk: {e}")

        try:
            # Test de Ljung–Box para autocorrelación (varios lags)
            # Usamos lags hasta min(10, n/5) para evitar sobreajuste en muestras pequeñas
            # Número de lags: mínimo 10 o n//5
            lb_lags = min(10, max(1, n // 5))

            # Ljung-Box
            lb_result = acorr_ljungbox(residuals_gam, lags=lb_lags, return_df=True)

            # Extraemos estadístico y p-valor del primer lag
            lb_stat = lb_result["lb_stat"].iloc[-1]
            lb_p = lb_result["lb_pvalue"].iloc[-1]

            diagnosticos_gam["ljung_box_lag"] = lb_lags
            diagnosticos_gam["ljung_box_stat"] = round(float(lb_stat), 4)
            diagnosticos_gam["ljung_box_p"] = round(float(lb_p), 4)

            print("Ljung-Box p:", lb_p)
        except Exception as e:
            print(f"Error en Ljung-Box: {e}")

        try:
            # White"s Test para heterocedasticidad (más general que Breusch-Pagan)
            X_white = sm.add_constant(X.flatten())
            white_test = het_white(residuals_gam, X_white)
            diagnosticos_gam["white_p"] = round(float(white_test[1]), 4)
            diagnosticos_gam["white_stat"] = round(float(white_test[0]), 4)
        except Exception as e:
            print(f"Error en White test: {e}")

        diagnosticos_gam["acf_plot"] = build_acf_plot(residuals_gam, n,
                                                      title="ACF de los residuos del GAM")

        diagnosticos_gam["gcv_score"] = round(float(gam.statistics_["GCV"]), 4)
        diagnosticos_gam["pseudo_r2"] = round(float(gam.statistics_["pseudo_r2"]["explained_deviance"]), 4)

        # P-valores
        p_valores_gam = {}
        try:
            p_valores_gam["smooth_term"] = round(float(gam.statistics_["p_values"][0]), 4)
        except:
            p_valores_gam["smooth_term"] = "N/A"

        # Predicción futura
        periodo_siguiente_val = df["periodo_num"].max() + 1
        X_pred = np.array([[periodo_siguiente_val]])
        pred_logit = float(gam.predict(X_pred)[0])
        pred_siguiente_gam = float(expit(pred_logit) * 100.0)

        # Intervalo de CONFIANZA (incertidumbre del ajuste)
        try:
            ci = gam.confidence_intervals(X_pred, width=0.95)
            ci_lower_gam = np.clip(expit(ci[0, 0]) * 100, 0, 100)
            ci_upper_gam = np.clip(expit(ci[0, 1]) * 100, 0, 100)
            print(f"   IC 95% (confianza en la media): [{ci_lower_gam:.2f}, {ci_upper_gam:.2f}]")
        except Exception as e:
            print(f"   Error IC confianza: {e}")
            ci_lower_gam = None
            ci_upper_gam = None

        # Intervalo de PREDICCIÓN (incertidumbre total)
        try:
            pi = gam.prediction_intervals(X_pred, width=0.95)
            pred_lower_gam = np.clip(expit(pi[0, 0]) * 100, 0, 100)
            pred_upper_gam = np.clip(expit(pi[0, 1]) * 100, 0, 100)
            print(f"   IP 95% (predicción individual): [{pred_lower_gam:.2f}, {pred_upper_gam:.2f}]")
        except Exception as e:
            print(f"   Error IP predicción: {e}")
            pred_lower_gam = None
            pred_upper_gam = None

        # Curva extendida
        x_historic = np.linspace(df["periodo_num"].min(), df["periodo_num"].max(), 75)
        x_future = np.linspace(df["periodo_num"].max(), periodo_siguiente_val, 76)
        x_smooth_extended = np.unique(np.concatenate([x_historic, x_future]))

        y_smooth_logit = gam.predict(x_smooth_extended)
        y_smooth_extended = expit(y_smooth_logit) * 100.0

        # Intervalo de CONFIANZA para toda la curva
        try:
            ci_curva = gam.confidence_intervals(x_smooth_extended.reshape(-1, 1), width=0.95)
            ci_lower_curva = np.clip(expit(ci_curva[:, 0]) * 100, 0, 100)
            ci_upper_curva = np.clip(expit(ci_curva[:, 1]) * 100, 0, 100)
        except Exception as e:
            print(f"   Error IC confianza curva: {e}")
            ci_lower_curva = None
            ci_upper_curva = None

        # Intervalo de PREDICCIÓN para toda la curva
        try:
            pi_curva = gam.prediction_intervals(x_smooth_extended.reshape(-1, 1), width=0.95)
            pred_lower_curva = np.clip(expit(pi_curva[:, 0]) * 100, 0, 100)
            pred_upper_curva = np.clip(expit(pi_curva[:, 1]) * 100, 0, 100)
        except Exception as e:
            print(f"   Error IP predicción curva: {e}")
            pred_lower_curva = None
            pred_upper_curva = None

        grafico_gam = build_gam_plot(
            df, x_smooth_extended, y_smooth_extended,
            periodo_siguiente_val, pred_siguiente_gam,
            pred_lower_curva, pred_upper_curva,
            agrupacion,
            titulo_grafico_gam, ylabel)

        print(f"R² GAM: {r2_gam:.4f}")
        print(f"RMSE GAM: {rmse_gam:.4f}")
        print(f"EDOF: {edof:.2f}")
        print(f"Predicción: {pred_siguiente_gam:.2f}%")

        resultados["gam"] = {
            "r2": round(r2_gam, 4),
            "mae": round(mae_gam, 4),
            "rmse": round(rmse_gam, 4),
            "pred_siguiente": round(pred_siguiente_gam, 2),
            "pred_lower": round(pred_lower_gam, 2),
            "pred_upper": round(pred_upper_gam, 2),
            "grafico": grafico_gam,
            "n_splines": n_splines,
            "spline_order": spline_order,
            "edof": round(edof, 2),
            "lambda": round(lam, 1),
            "p_valor": p_valores_gam.get("smooth_term", "N/A"),
            "aic": round(aic_gam, 2),
            "metodo": f"GAM (orden {spline_order}, lambda óptimo GCV)",
            "diagnosticos": diagnosticos_gam,

            "cv_mae": cv_metrics_gam.get("mae_mean", "N/A"),
            "cv_mae_std": cv_metrics_gam.get("mae_std", "N/A"),
            "cv_rmse": cv_metrics_gam.get("rmse_mean", "N/A"),
            "cv_rmse_std": cv_metrics_gam.get("rmse_std", "N/A"),
            "cv_smape": cv_metrics_gam.get("smape_mean", "N/A"),
            "cv_smape_std": cv_metrics_gam.get("smape_std", "N/A"),
            "cv_num_folds": cv_metrics_gam.get("num_folds_validos", 0),
        }

    except Exception as e:
        print(f"\n❌ ERROR GAM: {str(e)}")
        resultados["gam"] = {"error": f"Error en GAM: {str(e)}"}

    return resultados


def foward_chaining_expanding_window_cv(df: pd.DataFrame) -> dict:
    """
    Realiza validación cruzada Rolling Forward Chaining/ Expanding Window con ventana de test
    de tamaño adaptable para series temporales. También realiza la selección del
    hiperparámetro lambda para la regresión GAM por GridSearch.
    ref: https://medium.com/@pacosun/respect-the-order-cross-validation-in-time-series-7d12beab79a1

    La ventana de predicción se adapta según los datos disponibles:
    - Hasta 10 períodos: ventana test one-step ahead, test = 1
    - Entre 11 y 20 períodos: ventana two-step ahead, test = 2
    - Más de 20 períodos: ventana three-step ahead, test = 3
    """

    # Determinar el tamaño de ventana de predicción según datos disponibles
    n = len(df)

    if n <= 10:
        test_window = 1
        min_train = 3
    elif n <= 20:
        test_window = 2
        min_train = 5
    else:
        test_window = 3
        min_train = 7

    # Verificar que tenemos suficientes datos
    if n < min_train + test_window:
        error_msg = f"Insuficientes datos para CV: se necesitan al menos {min_train + test_window} períodos, pero solo hay {n}"
        return {
            "lineal": {"error": error_msg},
            "gam": {"error": error_msg},
        }

    # Calcular número de folds
    num_folds = n - min_train - test_window + 1

    print(f"\n=== Validación Cruzada Rolling-Origin ===")
    print(f"Total períodos: {n}")
    print(f"Ventana mínima entrenamiento: {min_train}")
    print(f"Ventana de predicción (test): {test_window} período(s)")
    print(f"Número de folds: {num_folds}")

    errores = {
        "lineal": {"errores_crudos": [], "smape": []},
        "gam": {"errores_crudos": [], "smape": []},
    }

    gam_errors_by_lambda = defaultdict(list)
    lam_grid = np.logspace(-3, 3, 20)

    # PASO 1: evaluar en todos los folds
    print(f"\n{"=" * 60}")
    print("FASE 1: EVALUACIÓN DE HIPERPARÁMETROS")
    print(f"{"=" * 60}")

    gam_evaluation_errors = []  # Para guardar errores de eval GAM

    for i in range(num_folds):
        train_end = min_train + i
        test_start = train_end
        test_end = test_start + test_window # test el siguiente punto temporal

        df_train = df.iloc[:train_end].copy()
        df_test = df.iloc[test_start:test_end].copy()

        X_train = df_train["periodo_num"].values.reshape(-1, 1)
        y_train = df_train["porcentaje_si"].values
        X_test = df_test["periodo_num"].values.reshape(-1, 1)
        y_test = df_test["porcentaje_si"].values

        print(f"\nFold {i + 1}/{num_folds}: Train={train_end}, Test={test_start + 1}-{test_end}")

        # MODELO LINEAL
        try:
            X_train_const = sm.add_constant(X_train, has_constant="add")
            X_test_const = sm.add_constant(X_test, has_constant="add")
            modelo_lin = sm.OLS(y_train, X_train_const).fit()

            # Cálculo de métricas
            pred_lin = modelo_lin.predict(X_test_const)
            pred_lin = np.clip(pred_lin, 0, 100)

            errores_crudos = y_test - pred_lin
            mae_lin = np.mean(np.abs(errores_crudos))
            rmse_lin = np.sqrt(np.mean(errores_crudos ** 2))
            smape_lin = np.mean([smape(y_test[j], pred_lin[j]) for j in range(len(y_test))])

            # Guaramos los errores
            for err in errores_crudos:
                errores["lineal"]["errores_crudos"].append(err)
            for j in range(len(y_test)):
                errores["lineal"]["smape"].append(smape(y_test[j], pred_lin[j]))

            print(f"  Lineal: MAE={mae_lin:.2f}%, RMSE={rmse_lin:.2f}, SMAPE={smape_lin:.2f}%")

            if test_window > 1:
                for j in range(len(y_test)):
                    print(f"    t+{j + 1}: pred={pred_lin[j]:.2f}%, real={y_test[j]:.2f}%")
            else:
                print(f"    pred={pred_lin[0]:.2f}%, real={y_test[0]:.2f}%")

        except Exception as e:
            # Errores detallados
            error_detail = f"Fold {i + 1}: {str(e)}"
            print(f"  Lineal: Error - {error_detail}")
            for _ in range(test_window):
                errores["lineal"]["errores_crudos"].append(np.nan)
                errores["lineal"]["smape"].append(np.nan)

        # GAM (evaluar TODAS las lambdas)
        if len(df_train) < 5:
            msg = f"Saltando fold {i + 1} - solo {len(df_train)} obs (mínimo 5 para GAM)"
            print(f"  GAM: {msg}")
            gam_evaluation_errors.append(msg)
            continue

        try:
            # Preparar datos
            X_train_gam = df_train["periodo_num"].values.reshape(-1, 1)
            y_train_percent = df_train["porcentaje_si"].values
            y_train_prop = y_train_percent / 100.0

            # Transformación logit:
            # La variable respuesta es una proporción en el intervalo (0, 1).
            # Un GAM ajustado directamente sobre proporciones puede generar predicciones fuera de este rango.
            # Para evitarlo, transformamos la proporción mediante la función logit, que mapea (0, 1) a (-inf, +inf).
            # Tras ajustar el GAM en la escala logit, aplicamos la función logística inversa para recuperar
            # las predicciones en la escala original (porcentaje).
            # Dado que logit(p) no está definida para p = 0 o p = 1, usamos un epsilon para mantener los valores
            # dentro del intervalo abierto (0, 1).
            epsilon = 1e-6
            y_train_prop_safe = np.clip(y_train_prop, epsilon, 1 - epsilon)
            y_train_logit = logit(y_train_prop_safe)

            n_splines_cv, spline_order = adaptative_config_gam(len(X_train_gam))

            # Probar CADA lambda en ESTE fold
            lambdas_fallidas_fold = 0
            for lam in lam_grid:
                try:
                    # Ajustamos el modelo GAM
                    gam = LinearGAM(
                        s(0, n_splines=n_splines_cv, spline_order=spline_order),
                        lam=lam
                    ).fit(X_train_gam, y_train_logit)

                    # Predicciones para el modelo con esa lambda
                    pred_logit = gam.predict(X_test)
                    pred_prop = expit(pred_logit)
                    pred_percent = np.clip(pred_prop * 100, 0, 100)

                    mae_gam = np.mean(np.abs(y_test - pred_percent))

                    # Acumular MAE de esta lambda en este fold (para selección)
                    gam_errors_by_lambda[lam].append(mae_gam)

                except Exception as e:
                    # Si falla, registrar NaN
                    lambdas_fallidas_fold += 1
                    gam_errors_by_lambda[lam].append(np.nan)

            # Registro de lambdas fallidas
            if lambdas_fallidas_fold > 0:
                print(f"  GAM: Evaluadas {len(lam_grid)} lambdas ({lambdas_fallidas_fold} fallaron)")
            else:
                print(f"  GAM: Evaluadas {len(lam_grid)} lambdas (todas exitosas)")

        except Exception as e:
            error_detail = f"Fold {i + 1}: {str(e)}"
            print(f"  GAM: Error general - {error_detail}")
            gam_evaluation_errors.append(error_detail)

    #  PASO 2: Selección de LAMBDA (usando MAE)
    if not gam_errors_by_lambda:
        error_msg = "No se pudo evaluar GAM en ningún fold"
        if gam_evaluation_errors:
            error_msg += f". Errores encontrados: {'; '.join(gam_evaluation_errors[:3])}"

        print(f"\n❌ {error_msg}")
        resultados_cv = {
            "lineal": get_metrics(errores["lineal"], test_window=test_window),
            "gam": {"error": error_msg}
        }
        return resultados_cv

    print(f"\n{"=" * 60}")
    print("FASE 2: SELECCIÓN DE HIPERPARÁMETROS (usando MAE)")
    print(f"{"=" * 60}")

    lambda_results = {}
    for lam, errors in sorted(gam_errors_by_lambda.items()):
        errors_arr = np.array(errors)
        valid_errors = errors_arr[~np.isnan(errors_arr)]

        if len(valid_errors) > 0:
            # Media y desviación estándar de los errores
            mean_mae = np.mean(valid_errors)
            std_mae = np.std(valid_errors)

            lambda_results[lam] = {
                "mean_mae": mean_mae,
                "std_mae": std_mae,
                "n_folds": len(valid_errors)
            }
            print(f"  Lambda={lam:8.4f}: MAE={mean_mae:.4f} ± {std_mae:.4f} "
                  f"({len(valid_errors)} folds)")

    if not lambda_results:
        error_msg = "Ninguna lambda produjo resultados válidos en CV"
        print(f"\n❌ {error_msg}")
        resultados_cv = {
            "lineal": get_metrics(errores["lineal"], test_window=test_window),
            "gam": {"error": error_msg}
        }
        return resultados_cv

    # Mejor LAMBDA: la que minimiza MAE
    best_lambda = min(lambda_results.keys(),
                      key=lambda k: lambda_results[k]["mean_mae"])
    best_mae = lambda_results[best_lambda]["mean_mae"]
    best_std = lambda_results[best_lambda]["std_mae"]

    print(f"\n✅ Mejor lambda: {best_lambda:.4f} "
          f"(MAE: {best_mae:.4f} ± {best_std:.4f} en "
          f"{lambda_results[best_lambda]["n_folds"]} folds)")

    # PASO 3: Evaluación del modelo final
    print(f"\n{"=" * 60}")
    print(f"FASE 3: EVALUACIÓN FINAL CON LAMBDA={best_lambda:.4f}")
    print(f"{"=" * 60}")

    folds_exitosos_gam = 0
    for i in range(num_folds):
        train_end = min_train + i
        test_start = train_end
        test_end = test_start + test_window

        df_train = df.iloc[:train_end].copy()
        df_test = df.iloc[test_start:test_end].copy()

        if len(df_train) < 5:
            continue

        try:
            X_train_gam = df_train["periodo_num"].values.reshape(-1, 1)
            y_train_percent = df_train["porcentaje_si"].values
            y_train_prop = y_train_percent / 100.0

            epsilon = 1e-6
            y_train_prop_safe = np.clip(y_train_prop, epsilon, 1 - epsilon)
            y_train_logit = logit(y_train_prop_safe)

            X_test_fold = df_test["periodo_num"].values.reshape(-1, 1)
            y_test_fold = df_test["porcentaje_si"].values

            n_splines_cv, spline_order = adaptative_config_gam(len(X_train_gam))

            gam_final = LinearGAM(
                s(0, n_splines=n_splines_cv, spline_order=spline_order),
                lam=best_lambda
            ).fit(X_train_gam, y_train_logit)

            pred_logit = gam_final.predict(X_test_fold)
            pred_prop = expit(pred_logit)
            pred_percent = np.clip(pred_prop * 100, 0, 100)

            errores_crudos = y_test_fold - pred_percent
            mae_gam = np.mean(np.abs(errores_crudos))
            rmse_gam = np.sqrt(np.mean(errores_crudos ** 2))
            smape_gam = np.mean([smape(y_test_fold[j], pred_percent[j])
                                 for j in range(len(y_test_fold))])

            for err in errores_crudos:
                errores["gam"]["errores_crudos"].append(err)
            for j in range(len(y_test_fold)):
                errores["gam"]["smape"].append(smape(y_test_fold[j], pred_percent[j]))

            folds_exitosos_gam += 1

            print(f"  Fold {i + 1}: MAE={mae_gam:.2f}%, RMSE={rmse_gam:.2f}, "
                  f"SMAPE={smape_gam:.2f}%")
            if test_window > 1:
                for j in range(len(y_test_fold)):
                    print(f"    t+{j + 1}: pred={pred_percent[j]:.2f}%, "
                          f"real={y_test_fold[j]:.2f}%")
            else:
                print(f"    pred={pred_percent[0]:.2f}%, real={y_test_fold[0]:.2f}%")

        except Exception as e:
            error_detail = f"Fold {i + 1}: {str(e)}"
            print(f"  {error_detail}")
            gam_evaluation_errors.append(error_detail)
            for _ in range(test_window):
                errores["gam"]["errores_crudos"].append(np.nan)
                errores["gam"]["smape"].append(np.nan)

    # Verificar si GAM tuvo suficientes folds exitosos
    if folds_exitosos_gam == 0:
        error_msg = f"GAM falló en todos los folds de evaluación final. Errores: {'; '.join(gam_evaluation_errors[:3])}"
        print(f"\n❌ {error_msg}")
        resultados_cv = {
            "lineal": get_metrics(errores["lineal"], test_window=test_window),
            "gam": {"error": error_msg}
        }
        return resultados_cv

    # Resumen final para el log
    resultados_cv = {
        "lineal": get_metrics(errores["lineal"], test_window=test_window),
        "gam": get_metrics(errores["gam"], test_window=test_window)
    }

    if "error" not in resultados_cv["gam"]:
        resultados_cv["gam"]["best_lambda"] = round(float(best_lambda), 4)
        resultados_cv["gam"]["lambda_mae_cv"] = round(float(best_mae), 4)
        resultados_cv["gam"]["lambda_std_cv"] = round(float(best_std), 4)

    # Añadir información de configuración
    resultados_cv["config"] = {
        "total_periodos": n,
        "ventana_test": test_window,
        "ventana_train_min": min_train,
        "num_folds": num_folds
    }

    print(f"\n{"=" * 60}")
    print("RESUMEN VALIDACIÓN CRUZADA")
    print(f"{"=" * 60}")
    print(f"Configuración: {n} períodos, ventana test={test_window}, "
          f"train mín={min_train}")

    for modelo in ["lineal", "gam"]:
        metrics = resultados_cv[modelo]
        if "error" not in metrics:
            print(f"{modelo.upper()}: MAE={metrics["mae_mean"]}±{metrics["mae_std"]}%, "
                  f"RMSE={metrics["rmse_mean"]}±{metrics["rmse_std"]}, "
                  f"SMAPE={metrics["smape_mean"]}±{metrics["smape_std"]}% "
                  f"({metrics["num_folds_validos"]}/{metrics["num_folds_total"]} folds)")
            if modelo == "gam":
                print(f"  Lambda óptima: {metrics["best_lambda"]} "
                      f"(MAE en selección: {metrics["lambda_mae_cv"]}±{metrics["lambda_std_cv"]})")
        else:
            print(f"{modelo.upper()}: {metrics["error"]}")

    return resultados_cv


def get_metrics(errores_dict: dict, test_window: int = 1) -> dict:
    """
    Calcula métricas agregadas de validación cruzada. Toma como argumentos:
    errores_dict: Diccionario con 'errores_crudos' y 'smape'
    test_window: Tamaño de la ventana de predicción (1, 2 o 3)
    Devuelve un diccionario con métricas agregadas y sus desviaciones estándar
    """
    errores_crudos = np.array(errores_dict["errores_crudos"])
    smape_arr = np.array(errores_dict["smape"])

    # Filtrar NaN
    errores_validos = errores_crudos[~np.isnan(errores_crudos)]
    smape_validos = smape_arr[~np.isnan(smape_arr)]

    if len(errores_validos) == 0:
        return {"error": "No hay folds válidos"}

    # Número de folds (cada fold tiene test_window predicciones)
    num_folds = len(errores_validos) // test_window

    # Si no hay suficientes datos para calcular por fold, usar aproximación
    if num_folds < 1:
        num_folds = 1

    # Reorganizar errores por fold
    # Cada fold tiene 'test_window' predicciones consecutivas
    mae_por_fold = []
    rmse_por_fold = []
    smape_por_fold = []

    for i in range(num_folds):
        start_idx = i * test_window
        end_idx = start_idx + test_window

        # Extraer errores de este fold
        errores_fold = errores_validos[start_idx:end_idx]
        smape_fold = smape_validos[start_idx:end_idx]

        if len(errores_fold) > 0:
            # MAE del fold: promedio de errores absolutos
            mae_fold = np.mean(np.abs(errores_fold))
            mae_por_fold.append(mae_fold)

            # RMSE del fold: raíz del promedio de errores al cuadrado
            rmse_fold = np.sqrt(np.mean(errores_fold ** 2))
            rmse_por_fold.append(rmse_fold)

            # SMAPE del fold: promedio
            smape_fold_mean = np.mean(smape_fold)
            smape_por_fold.append(smape_fold_mean)

    # Convertir a arrays para cálculos
    mae_por_fold = np.array(mae_por_fold)
    rmse_por_fold = np.array(rmse_por_fold)
    smape_por_fold = np.array(smape_por_fold)

    # Métricas globales y sus desviaciones estándar
    return {
        "mae_mean": round(float(np.mean(mae_por_fold)), 2),
        "mae_std": round(float(np.std(mae_por_fold)), 2),
        "rmse_mean": round(float(np.mean(rmse_por_fold)), 2),
        "rmse_std": round(float(np.std(rmse_por_fold)), 2),
        "smape_mean": round(float(np.mean(smape_por_fold)), 2),
        "smape_std": round(float(np.std(smape_por_fold)), 2),
        "num_folds_validos": len(mae_por_fold),
        "num_folds_total": num_folds
    }


def get_global_statistics(datos_tendencia: list[dict]) -> dict:
    """Calcula estadísticas globales."""
    total_S = sum(d["conteos"]["S"] for d in datos_tendencia)
    total_I = sum(d["conteos"]["I"] for d in datos_tendencia)
    total_R = sum(d["conteos"]["R"] for d in datos_tendencia)
    total_general = total_S + total_I + total_R

    if total_general > 0:
        porcentaje_S = round((total_S / total_general) * 100, 1)
        porcentaje_I = round((total_I / total_general) * 100, 1)
        porcentaje_R = round((total_R / total_general) * 100, 1)
    else:
        porcentaje_S = porcentaje_I = porcentaje_R = 0

    return {
        "total_general": total_general,
        "total_S": total_S,
        "total_I": total_I,
        "total_R": total_R,
        "porcentaje_S": porcentaje_S,
        "porcentaje_I": porcentaje_I,
        "porcentaje_R": porcentaje_R,
    }


# Vistas JSONResponse para AJAX y relleno de los select
def get_antibioticos(request):
    microorganismo_hospital_id = request.GET.get("microorganismo_id")
    microorganismo = MicroorganismoHospital.objects.get(id=microorganismo_hospital_id)
    grupo_eucast = microorganismo.microorganismo.grupo_eucast

    perfil = PerfilAntibiogramaHospital.objects.filter(
        grupo_eucast=grupo_eucast
    )
    antibio_qs = AntibioticoHospital.objects.filter(
        perfilantibiogramahospital__in=perfil
    ).select_related("antibiotico").order_by("antibiotico__nombre")

    data = [{"id": a.id, "nombre": a.antibiotico.nombre} for a in antibio_qs]
    return JsonResponse(data, safe=False)


def get_mec_resistencia(request):
    micro_id = request.GET.get("microorganismo_id")
    microorganismo = MicroorganismoHospital.objects.get(id=micro_id)

    # Obtener mecanismos base que incluyen al microorganismo y que existan en el hospital
    mecanismos = MecanismoResistenciaHospital.objects.filter(
        mecanismo__grupos_eucast=microorganismo.microorganismo.grupo_eucast,
    ).select_related("mecanismo").order_by("mecanismo__nombre").distinct()

    data = [{"id": m.id, "nombre": m.mecanismo.nombre} for m in mecanismos]
    return JsonResponse(data, safe=False)


def get_sub_mecanismos(request):
    mec_id = request.GET.get("mecanismo_id")
    mecanismo = MecanismoResistenciaHospital.objects.get(id=mec_id)

    subtipos = SubtipoMecanismoResistenciaHospital.objects.filter(
        hospital=mecanismo.hospital,
        subtipo_mecanismo__mecanismo=mecanismo.mecanismo
    ).select_related("subtipo_mecanismo").order_by("subtipo_mecanismo__nombre").distinct()

    data = [{"id": s.id, "nombre": s.subtipo_mecanismo.nombre} for s in subtipos]
    return JsonResponse(data, safe=False)
