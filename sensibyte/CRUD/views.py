import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

# Vistas basadas en clases: https://docs.djangoproject.com/en/5.2/topics/class-based-views/generic-display/
from django.views.generic import DeleteView
from django.views.generic import FormView
from django.views.generic import ListView, DetailView, UpdateView

from Base.decorators import role_required
from Base.models import (AmbitoHospital, ServicioHospital, Registro, ResultadoAntibiotico, Aislado, SexoHospital,
                         TipoMuestraHospital,
                         MicroorganismoHospital, PerfilAntibiogramaHospital, AliasInterpretacionHospital,
                         ReglaInterpretacion, EucastVersion, Antibiotico, Hospital,
                         AntibioticoHospital
                         )
from .forms import (CargarAntibiogramaForm, FiltroRegistroForm, RegistroForm, AisladoFormSet)
from .forms import MecanismoResistenciaForm
from .forms import ResultadoFormSet
from .utils import *


class CargarAntibiogramaView(FormView):
    """Vista de carga de archivos con antibiogramas para el formulario CargarAntibiogramaForm"""
    template_name = "CRUD/cargar_antibiograma.html"  # plantilla
    form_class = CargarAntibiogramaForm  # formulario
    success_url = reverse_lazy("CRUD:cargar_antibiograma")  # redirección de éxito

    # Sobreescribimos el método get_form_kwargs, el método que inyecta kwargs a los formularios,
    # para pasarle el kwarg 'hospital', así podrá filtrar los objetos MicroorganismoHospital del hospital
    # del usuario
    #
    # ref: https://docs.djangoproject.com/en/5.2/ref/class-based-views/mixins-editing/#django.views.generic.edit.FormMixin.get_form_kwargs
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Capturar el hospital del usuario, que tiene un campo hospital asociado
        kwargs["hospital"] = getattr(self.request.user, "hospital", None)
        return kwargs

    # Sobreescribimos el método get_context_data, método que llama a get_form() y añade el resultado al contexto con el
    # nombre 'form', para pasarle campos nuevos no definidos en el form_class. Los campos tienen que ir
    # en forma de lista.
    #
    # ref: https://docs.djangoproject.com/en/5.2/ref/class-based-views/mixins-editing/#django.views.generic.edit.FormMixin.get_context_data
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # pasamos al contexto 2 tipos de campos al formulario: campos_demográficos y campos_opcionales
        context["campos_demograficos"] = [
            "fecha", "microorganismo", "edad", "sexo", "ambito", "servicio", "tipo_muestra"
        ]
        context["campos_opcionales"] = ["nh", "observaciones"]
        return context

    # form_valid: es el método que hay que sobreescribir para aplicar la lógica de negocio. Su objetivo es
    #  redirigir a la dirección de éxito (hay otro método para devolver una respuesta si el formulario es incorrecto
    # llamado form_invalid, pero no es necesario sobreescribirlo, por el momento
    #
    # ref: https://docs.djangoproject.com/en/5.2/ref/class-based-views/mixins-editing/#django.views.generic.edit.FormMixin.form_valid
    def form_valid(self, form):
        import time
        import pandas as pd

        files = self.request.FILES.getlist(
            "file")  # En self.request.FILES se guardan los archivos, se accede a la lista de archivos mediante getlist()

        microorganismo_hospital = form.cleaned_data[
            "microorganismo"]  # obtenemos del campo "microorganismo" del formulario el objeto MicroorganismoHospital
        selected_microorganismo = microorganismo_hospital.microorganismo  # accedemos su campo microorganismo que contiene el
        # objeto Microorganismo

        # Comprobaciones de usuario
        user = self.request.user

        # Si es superusuario no tiene un hospital asociado
        if user.is_superuser:
            hospital = None

        # Si es otro tipo de usuario
        else:
            hospital = getattr(user, "hospital", None)  # accedemos a su atributo hospital
            if hospital is None:  # No puede no tenerlo, si es así redirige con un mensaje de error
                messages.error(self.request, "El usuario no tiene hospital asignado.")
                return redirect("CRUD:cargar_antibiograma")

        # Check de objeto Microoroganismo en el MicroorganismoHospital del usuario
        microorganismo = (MicroorganismoHospital.objects.filter(
            hospital=hospital,
            microorganismo__nombre=selected_microorganismo
        )
                          # Aprovechamos a extraer el GrupoEucast del Microorganismo asociado (lo necesitaremos después)
                          # select_related: en el ORM (Object-Relational Mapper) de Django, este método permite, para relaciones FK o
                          # OneToOne, construir y ejecutar UNA ÚNICA consulta SQL, y cachear en memoria (en Python) los objetos relacionados
                          # que puedan necesitarse posteriormente. De lo contrario, Django ejecutaría tres consultas independientes:
                          # una para MicroorganismoHospital, otra para Microorganismo y otra para GrupoEucast.
                          #
                          # https://docs.djangoproject.com/en/5.2/ref/models/querysets/#django.db.models.query.QuerySet.select_related
                          .select_related("microorganismo__grupo_eucast").first())

        # Si la consulta no devuelve microorganismo -> error, no existe ese microorganismo para ese hospital
        if not microorganismo:
            messages.error(self.request,
                           f"No se encontró el microorganismo '{selected_microorganismo}' para este hospital.")
            return redirect("CRUD:cargar_antibiograma")

        grupo_eucast = microorganismo.microorganismo.grupo_eucast  # GrupoEucast del Microorganismo del MicroorganismoHospital

        # Cada hospital genera su PerfilAntibiogramaHospital. 1 Perfil tiene varios Antibioticos asociados y 1 Antibiotico
        # puede estar asociado a varios Perfiles (relación ManyToMany). De forma análoga a 'select_related', el ORM de Django
        # nos permite utilizar el método 'prefetch_related' para recuperar los objetos relacionados en una única consulta
        #
        # https://docs.djangoproject.com/en/5.2/ref/models/querysets/#prefetch-related
        perfil = PerfilAntibiogramaHospital.objects.filter(
            hospital=hospital,
            grupo_eucast=grupo_eucast
        ).prefetch_related("antibioticos__antibiotico").first()

        # Si no hay perfil definido por el hospital para ese grupo EUCAST, devolvemos un error-> Hay que generar uno previamente
        if not perfil:
            messages.error(self.request,
                           f"No hay un perfil EUCAST definido por el hospital '{hospital}' para el grupo '{grupo_eucast}'.")
            messages.info(self.request,
                          f"Es necesario crear previamente un perfil EUCAST para el grupo '{grupo_eucast}'")
            return redirect("CRUD:cargar_antibiograma")

        # Rrecogemos de la query anterior del perfil todos los objetos AntibioticoHospital y los enlistamos
        antibioticos_permitidos = list(perfil.antibioticos.all())
        print(f"Los antibióticos permitidos son:{antibioticos_permitidos}")

        # Comienza el procesamiento de datos
        # 1. Leer y consolidar archivos
        dfs = self._read_files(files)  # generamos una lista de DataFrames con el método interno _read_files()

        # si dfs es nulo -> mostramos un error
        if not dfs:
            messages.error(self.request, "No se pudo cargar ningún archivo válido.")
            return redirect("CRUD:cargar_antibiograma")

        # concatenamos los datos de la lista de DataFrames
        df = pd.concat(dfs, ignore_index=True)
        print(f"📋 Columnas detectadas en el archivo: {list(df.columns)}")

        # 2. Convertir columnas CMI y halo a numéricas (si se puede) con el método interno
        # convert_mic_mm_column()
        self._convert_mic_mm_column(df)

        # Eliminamos el sufijo "_col" que introduce el formulario
        mapping = {k.replace("_col", ""): v for k, v in self.request.POST.items() if k.endswith("_col")}

        # 3. Inicializamos contadores y cachés de objetos
        contadores = {
            "registros_creados": 0,  # para objetos Registro creados
            "registros_reutilizados": 0,  # para objetos Registro actualizados
            "registros_errores": 0,  # para errores an la creación de objetos Registro
            "aislados_creados": 0,  # para objetos Aislado creados
            "duplicados_omitidos": 0,  # para objetos Aislado duplicados
            "errores_resultados": 0  # para otros errores
        }

        indices_duplicados = []  # inicialización de lista para índices en el DataFrame con los duplicados
        errores_detallados = []  # lista de errores
        timestamp_carga = int(
            time.time() * 1000)  # timestamp del proceso de carga (para la generación de identificadores
                                # de individuo a través de la función gen_automatic_nh_hash()

        # Construimos el caché de objetos específicos del hospital del usuario
        cache = self._build_cache(hospital, antibioticos_permitidos)

        # Precargamos las resistencias intrínsecas
        resistencias_intrinsecas = set(
            # La relación de Antibioticos es ManyToMany-> extraemos la lista de ids con values_list(flat=True)
            microorganismo.microorganismo.resistencia_intrinseca.values_list("id", flat=True)
        )

        # 4. Procesamiento de filas
        #
        # Nota: enumerate con un iterador devuelve una tupla de (contador, valores del iterable)
        # A su vez, pandas.DataFrame.iterrows() también devuelve una tupla (index, row), con lo que
        # finalmente obtenemos: (contador, (index, row)). 'contador' nos sirve para localizar filas
        # en los logs (en base 1, por el argumento 'start' de enumerate)
        for contador_fila, (idx, row) in enumerate(df.iterrows(), start=1):
            try:
                # 4.1 Procesar datos demográficos
                datos_demograficos = self._get_demographic_data(
                    row, mapping, cache, timestamp_carga, contador_fila, microorganismo.id
                )

                # Si no llegan datos_demográficos para la fila: añadir a contadores y el diccionario detallado de errores
                # y continuar con la siguiente fila
                if datos_demograficos is None:
                    contadores["registros_errores"] += 1
                    errores_detallados.append(f"Fila {contador_fila}: Datos demográficos inválidos")
                    continue

                # Obtener o crear objeto Registro para la fila
                registro = self.get_or_create_registro(
                    datos_demograficos, hospital, cache["registros_cache"], contadores
                )

                # 4.2 Procesar los resultados de los antibióticos
                resultados_antibiograma = self._get_antibiogram(
                    row, cache["nombres_ab_dict"], cache["antibioticos_dict"],
                    cache["alias_hospital"], datos_demograficos["version_eucast"],
                    microorganismo, datos_demograficos["edad"], datos_demograficos["sexo_obj"],
                    datos_demograficos["muestra_obj"], resistencias_intrinsecas
                )

                # Si no hay resultados -> advertencia en el log y pasamos a la siguiente fila.
                # No hay información útil para crear un registro
                if not resultados_antibiograma or all(
                        res[0] == "ND" for res in resultados_antibiograma.values()
                        # interpretación es el primer valor de la tupla
                ):
                    print(f"⚠️ Fila {contador_fila}: sin resultados de antibiograma válidos -> omitida")
                    continue  # pasamos a la siguiente fila

                # 4.3 Detectar mecanismos y aplicar resistencias adquiridas
                mec_detectados, sub_detectados, resultados_finales = self._get_arm(
                    row, mapping, resultados_antibiograma,
                    cache["mecanismos"], cache["subtipos"], cache["pos_vals"]
                )

                # 4.4 Verificar duplicados
                if self._is_duplicated(registro, microorganismo, resultados_finales):
                    contadores[
                        "duplicados_omitidos"] += 1  # Si es duplicado se añade al contador específico, y log en consola
                    indices_duplicados.append(idx)
                    print(f"⏭️ Saltando fila {contador_fila} - duplicado exacto")
                    continue  # pasamos a la siguiente fila

                # 4.5 Crear aislado y resultados
                self._create_isolate(
                    registro, hospital, datos_demograficos["version_eucast"],
                    microorganismo, resultados_finales, mec_detectados, sub_detectados,
                    resistencias_intrinsecas
                )

                contadores["aislados_creados"] += 1
                print(f"✅ Aislado creado exitosamente con {len(resultados_finales)} resultados\n")

            except Exception as e:
                contadores["registros_errores"] += 1
                errores_detallados.append(f"Fila {contador_fila}: {str(e)}")
                print(f"❌ ERROR GENERAL en fila {contador_fila}: {str(e)}")
                import traceback
                traceback.print_exc()

        # 5. Limpieza de registros huérfanos
        registros_huerfanos = Registro.objects.filter(aislados__isnull=True)
        count_huerfanos = registros_huerfanos.count()

        if count_huerfanos > 0:
            print(f"\n🧹 Eliminando {count_huerfanos} registros sin aislados...")
            for r in registros_huerfanos:
                print(f"   - Registro {r.id} sin aislados (probablemente sin datos válidos):"
                      f"        * Fecha: {r.fecha}"
                      f"        * Sexo: {r.sexo}"
                      f"        * Edad: {r.edad}")
            registros_huerfanos.delete()
        else:
            print("\n✅ No se encontraron registros huérfanos.")

        # 6. Mostramos mensajes finales en la consola
        self._show_final_messages(contadores, count_huerfanos)
        # print(f"DEBUG: {errores_detallados}")

        return redirect("CRUD:cargar_antibiograma")  # volvemos a esta misma página

    def _read_files(self, files: list):
        """Lee y consolida archivos XLSX/CSV
        Toma como argumento una lista con los archivos en objetos
        InMemoryUploadedFile y devuelve un objeto pandas.Dataframe"""
        dfs = []  # inicializamos una lista
        for file in files:  # accedemos a cada uno de los archivos en bucle
            ext = os.path.splitext(file.name)[-1].lower()  # obtenemos la extensión por splitext() de os.path.
            # la extensión es el último string
            # https://docs.python.org/3.13/library/os.path.html#os.path.splitext
            try:
                # Si la extensión es del tipo archivo de Excel
                if ext in [".xls", ".xlsx"]:
                    # leemos con la función pandas.read_excel()
                    sheets = pd.read_excel(file, sheet_name=None)  # sheet_name=None-> lee todas las hojas para devolver
                    # un diccionario de DataFrames
                    dfs.extend(
                        sheets.values())  # añade a la lista vacía de la variable 'dfs' cada uno de los DataFrames

                # Si la extensión es del tipo archivo CSV
                elif ext == ".csv":
                    # leemos bytes con la función file.read() y los decodificamos usando la codificación 'latin-1'
                    # (se evitan así errores con acentos o símbolos extraños si no es UTF-8)
                    #
                    # (Nota: no he sido capaz de leer de forma exitosa con la función de pandas.read_csv(). Ningún problema
                    # si lo hago desde Python, pero en Django es como si los archivos del campo estuvieran decodificados
                    # con UTF-8 siempre y no encuentro la forma de forzarlo a otra decodificación. Por eso, finalmente los leo
                    # manualmente
                    file_content = file.read().decode("latin-1")  # contenido del texto decodificado

                    csv_string = io.StringIO(file_content)  # stream de texto en memoria

                    # intentamos averiguar el dialecto del csv con el método csv.Sniffer().sniff():
                    # https://docs.python.org/es/3/library/csv.html#csv.Sniffer
                    #
                    # El problema es que algunos CSV llegan separados por ",", otros por ";"; o tienen los campos
                    # separados por comillas. O bien dejo en el formulario un campo para introducir el separador
                    # usado, o bien intento averiguar estas características del archivo pasado
                    dialect = csv.Sniffer().sniff(file_content)

                    # Ahora se intenta leer el contenido con la función de pandas.read_csv() con el separador
                    # y caracter de campo de texto
                    df = pd.read_csv(csv_string, encoding="latin-1",
                                     sep=dialect.delimiter,
                                     quotechar=dialect.quotechar)

                    dfs.append(df)  # a la lista vacía de la variable 'dfs' cada uno de los DataFrames

            # Si hay algún error lo mostramos en la consola para depurar
            # Nota: messanges es el middleware de Django que permite notificaciones flash tras la realización de operaciones:
            # ref: https://docs.djangoproject.com/en/5.2/ref/contrib/messages/
            except Exception as e:
                messages.error(self.request, f"Error leyendo archivo {file.name}: {e}")

        # Devuelve finalmente la lista de DataFrames
        return dfs

    @staticmethod
    def _convert_mic_mm_column(df: pandas.DataFrame) -> None:
        """Convierte columnas CMI a valores numéricos (inplace)"""
        # Recorremos las columnas buscando las que terminen en cmi, _cmi o -cmi / mm, _mm o -mm
        for col in df.columns:
            col_name = col.strip().lower()
            if col_name.endswith((" cmi", "_cmi", "-cmi")):
                print(f"Columna CMI encontrada: {col.strip().lower()}")
                # Utiliza la función numeric_column_transformer() para obtener el valor numérico
                # (si existe, si no devuelve el valor en cadena)
                val = numeric_column_transformer(df[col])
                df[col] = val  # se asigna el pandas.Series devuelto a la columna

            elif col_name.endswith((" mm", "_mm", "-mm")):
                print(f"Columna halo encontrada: {col.strip().lower()}")
                val = numeric_column_transformer(df[col])
                df[col] = val

    @staticmethod
    def _build_cache(hospital: Hospital, antibioticos_permitidos: list[AntibioticoHospital]) -> dict:
        """Construye todos los caches necesarios de una sola vez
        Toma 2 argumentos:
        - Hospital: objeto de la clase Hospital
        - antibioticos_permitidos: una lista de objetos AntibioticoHospital del hospital
        """
        return {
            # diccionarios de objetos de modelos Hospital para el hospital del usuario
            "sexos_cache": build_alias_cache(SexoHospital.objects.filter(hospital=hospital)),
            "ambitos_cache": build_alias_cache(AmbitoHospital.objects.filter(hospital=hospital)),
            "servicios_cache": build_alias_cache(ServicioHospital.objects.filter(hospital=hospital)),
            "muestras_cache": build_alias_cache(TipoMuestraHospital.objects.filter(hospital=hospital)),

            # diccionario de ids de AntibioticoHospital para el hospital del usuario
            "antibioticos_dict": {ab.antibiotico.id: ab for ab in antibioticos_permitidos},
            "nombres_ab_dict": {  # diccionario con listas de abreviaturas y 'alias' para cada uno de los ids de
                # AntibioticoHospital
                ab.antibiotico.id: [normalize_text(ab.antibiotico.abr)] + [normalize_text(a) for a in ab.alias]
                for ab in antibioticos_permitidos
            },
            # lista de objetos AliasInterpretacion del hospital del usuario
            "alias_hospital": list(AliasInterpretacionHospital.objects.filter(hospital=hospital)),
            # lista de objetos MecResValoresPositivosHospital del hospital del usuario
            "pos_vals": list(MecResValoresPositivosHospital.objects.filter(hospital=hospital)),
            # lista de objetos MecanismoResistenciaHospital del hospital del usuario
            "mecanismos": list(MecanismoResistenciaHospital.objects.filter(hospital=hospital)),
            # lista de objetos SubtipoMecanismoResistenciaHospital del hospital del usuario
            "subtipos": list(SubtipoMecanismoResistenciaHospital.objects.filter(hospital=hospital)),

            "registros_cache": {}
        }

    @staticmethod
    def _get_demographic_data(row: pandas.Series,
                              mapping: dict, cache: dict,
                              timestamp_carga: int, contador_fila: int,
                              microorganismo_id: int) -> dict | None:
        """Procesa y valida todos los datos demográficos de un registro. Toma los argumentos requeridos
        para crear un diccionario con los objetos necesarios para formar un objeto de la clase Registro"""

        # 1. Número de Historia
        nh_original = row.get(mapping.get("nh"))  # obtenemos del diccionario mapping el nombre de la columna 'nh'
        # en el archivo y extraemos su valor

        # si no es nulo ni cadena vacía -> codificamos el NH con el algoritmo SHA-256
        if nh_original and not pd.isna(nh_original) and str(nh_original).strip() != "":
            nh_hash = code_nh(nh_original)
        # si es nulo o cadena vacía generamos un hash con la función gen_automatic_nh_hash()
        # pasándole los argumentos apropiados
        else:
            nh_hash = gen_automatic_nh_hash(timestamp_carga, contador_fila, microorganismo_id)

        # 2. Edad
        edad_raw = row.get(
            mapping.get("edad"))  # obtenemos del diccionario mapping el nombre de la columna 'edad' en el
        # archivo y extraemos su valor

        edad = parse_age(edad_raw)  # parseamos el valor a un float

        # 3. Fecha
        fecha_raw = row.get(
            mapping.get("fecha"))  # obtenemos del diccionario mapping el nombre de la columna 'fecha' en el
        # archivo y extraemos su valor

        fecha = parse_fecha(fecha_raw)  # parseamos el valor a un objeto datetime.date

        # 4. Versión EUCAST (para poder generar variantes de antibótico)
        version_eucast = EucastVersion.get_version_from_date(fecha)

        # 5. Objetos para los campos hospital específicos
        sexo_obj = get_from_cache(cache["sexos_cache"], get_str(row, mapping.get("sexo", "")))
        ambito_obj = get_from_cache(cache["ambitos_cache"], get_str(row, mapping.get("ambito", "")))
        servicio_obj = get_from_cache(cache["servicios_cache"], get_str(row, mapping.get("servicio", "")))
        muestra_obj = get_from_cache(cache["muestras_cache"], get_str(row, mapping.get("tipo_muestra", "")))

        # Si no se han obtenido todos los campos, devuelve None
        if not all([fecha, nh_hash, sexo_obj, ambito_obj, servicio_obj, muestra_obj]):
            return None

        # Devuelve un diccionario con los objetos necesarios para crear el Registro
        return {
            "nh_hash": nh_hash,
            "edad": edad,
            "fecha": fecha,
            "version_eucast": version_eucast,
            "sexo_obj": sexo_obj,
            "ambito_obj": ambito_obj,
            "servicio_obj": servicio_obj,
            "muestra_obj": muestra_obj
        }

    @staticmethod
    def get_or_create_registro(datos: dict, hospital: Hospital, registros_cache: dict, contadores: dict):
        """Obtiene o crea un objeto Registro. Usa la caché pasada como argumento para obtenerlo, si no,
        lo crea a partir de los datos pasados al método"""

        # Se construye una tupla que caracterice de forma única un Registro
        registro_key = (
            datos["nh_hash"], datos["fecha"], datos["edad"],
            datos["sexo_obj"].id, datos["ambito_obj"].id,
            datos["servicio_obj"].id, datos["muestra_obj"].id
        )

        # Primero, intentamos acceder con esta tupla al Registro del caché
        registro = registros_cache.get(registro_key)
        # si obtiene Registro, se devuelve
        if registro:
            return registro

        # Si no está en caché, construimos un diccionario con los parámetros que identifican al
        # objeto Registro para consultar en la base de datos. Esto permite usar **kwargs con
        # .get(**query_registro).
        query_registro = {
            "nh_hash": datos["nh_hash"],
            "fecha": datos["fecha"],
            "sexo": datos["sexo_obj"],
            "ambito": datos["ambito_obj"],
            "servicio": datos["servicio_obj"],
            "tipo_muestra": datos["muestra_obj"],
            "hospital": hospital,
        }

        # Para el campo 'edad', si es None usamos 'edad__isnull=True' para que Django busque correctamente
        # objtos Registro donde el campo sea NULL.
        if datos["edad"] is None:
            query_registro["edad__isnull"] = True
        else:
            query_registro["edad"] = datos["edad"]

        try:
            # Itentamos obtener el Registro tras desempaquetar el diccionario como argumentos con nombre (**kwargs)
            registro = Registro.objects.get(**query_registro)  # devolveremos este Registro encontrado
            contadores[
                "registros_reutilizados"] += 1  # lo encontró, luego reutilizamos el registro, añadimos al contador
            print(f"✅ Registro existente encontrado: ID {registro.id}")

        except Registro.DoesNotExist:  # Si el registro NO existe, se crea con el método models.Model.objects.create()

            registro = Registro.objects.create(
                nh_hash=datos["nh_hash"],
                fecha=datos["fecha"],
                sexo=datos["sexo_obj"],
                edad=datos["edad"],
                ambito=datos["ambito_obj"],
                servicio=datos["servicio_obj"],
                tipo_muestra=datos["muestra_obj"],
                hospital=hospital,
            )

            contadores["registros_creados"] += 1  # añadimos al contador como creado
            print(f"🆕 Nuevo registro creado: ID {registro.id}")

        except Registro.MultipleObjectsReturned:  # Si existen varios objetos con estos parámetros,
                                                  # nos quedamos con el primero
            registro = Registro.objects.filter(**query_registro).first()
            contadores["registros_reutilizados"] += 1  # El registro se está reutilizando, añadimos al contador
            print(f"⚠️ Múltiples registros encontrados, usando ID {registro.id}")

        registros_cache[registro_key] = registro  # Importante!! Añadir el Registro al caché
        return registro  # Devuelve el Registro (encontrado o creado)

    def _get_antibiogram(self,
                         row: pandas.Series,
                         nombres_ab_dict: dict[int, list[str]],
                         antibioticos_dict: dict[int, AntibioticoHospital],
                         alias_hospital: list[AliasInterpretacionHospital],
                         version_eucast: EucastVersion,
                         microorganismo: MicroorganismoHospital,
                         edad: float | None,
                         sexo_obj: SexoHospital,
                         muestra_obj: TipoMuestraHospital,
                         resistencias_intrinsecas: set[int]) -> dict[int, tuple[str, float | None, float | None]]:

        """Procesa todos los antibióticos y retorna resultados completos.
        Las claves del diccionario retornado son IDs de objetos Antibiotico mientras que los valores
        son tuplas (interpretacion, cmi, halo).
        """

        resultados_procesados = {} # diccionario almacén de resultados de retorno

        # Por cada número id y lista de alias asociada al id en 'nombres_ab_dict'
        for antibiotico_hospital_id, alias in nombres_ab_dict.items():

            # 1. Verificar si hay datos de interpretación, cmi y halo válidos
            # extraemos los datos del CSV
            col_interp, interpretacion = search_value_in_columns(row, alias)
            col_cmi, cmi_valor = search_mic_in_columns(row, alias)
            halo_col, halo_valor = search_halo_in_columns(row, alias)

            # obtenemos el objeto AntibioticoHospital a partir de su id
            antibiotico_hospital = antibioticos_dict[antibiotico_hospital_id]

            antibiotico_base = antibiotico_hospital.antibiotico # Y el cd Antibiotico padre

            # verificamos si hay datos (interpretación o CMI o halo)
            tiene_datos = not (
                    (pd.isna(interpretacion) or interpretacion is None) and  # nulos en interpretación
                    (pd.isna(cmi_valor) or cmi_valor is None) and  # nulos en cmi_valor
                    (pd.isna(halo_valor) or halo_valor is None)  # nulos en halo_valor
            )  # con que en una de las condiciones no haya nulos, hay False-> not(False) = True-> tiene datos


            # Si no hay datos, NO guardamos nada (ni el base ni las variantes)
            if not tiene_datos:
                print(f"📝 Sin datos para {antibiotico_base.nombre}, se omite completamente")
                continue

            # si hay datos se procesa la interpretación del resultado para obtener su valor estandarizado
            interpretacion_std = self._get_interpretation(interpretacion, alias_hospital)

            # parseamos CMI y halo
            cmi_float, halo_float = self._parse_mic_and_halo(cmi_valor, halo_valor)

            # validación de resultados
            tiene_interpretacion_valida = interpretacion_std in ["S", "R", "I"]
            tiene_cmi_valida = cmi_float is not None
            tiene_halo_valido = halo_float is not None

            # si no tenemos ninguno de los resultados: ni interpretación, cmi o halo, pasamos al siguiente antibiótico
            if not (tiene_interpretacion_valida or tiene_cmi_valida or tiene_halo_valido):
                print(f"⚠️ Datos inválidos para {antibiotico_base.nombre}, se omite")
                continue

            # 2. Aplicar la resistencia intrínseca
            # Buscamos el AntibioticoHospital dentro de set de resistencias intrínsecas
            # Si tiene resistencia intrínseca, marcamos base + variantes como "R"
            if antibiotico_base.id in resistencias_intrinsecas:
                print(  # mensaje al log
                    f"🚫 {microorganismo.microorganismo.nombre} tiene resistencia intrínseca a {antibiotico_base.nombre}")

                # marcamos antibiótico base y variantes como R.
                # Nota: utilizamos objetos Q, que con sintaxis sencilla permiten combinar condiciones en una sola consulta
                # ref: https://docs.djangoproject.com/en/5.2/topics/db/queries/#complex-lookups-with-q-objects
                variantes_relacionadas = Antibiotico.objects.filter(  # realizamos la consulta a la base de datos
                    Q(parent=antibiotico_base) | Q(id=antibiotico_base.id)  # incluye el antibiótico padre y la variante
                )

                for variante in variantes_relacionadas:  # marcamos como "R"
                    resultados_procesados[variante.id] = ("R", cmi_float,
                                                          halo_float)  # incorporamos el resultado al almacén
                    print(f"   -> {variante.nombre} marcado como R (Antibiotico.id: {variante.id})")

                continue  # pasamos al siguiente antibiótico con resistencia intrínseca


            # 3. Guardar el antibiótico BASE con su interpretación original (NO habrá una reinterpretación)
            print(
                f"📌 Guardando antibiótico base: {antibiotico_base.nombre} - Interp: {interpretacion_std}, CMI: {cmi_float}, Halo: {halo_float}")
            resultados_procesados[antibiotico_base.id] = (interpretacion_std, cmi_float, halo_float)

            # 4. Aplicar reglas EUCAST a VARIANTES: obtiene la interpretación de categoría clínica en variantes de antibiótico por
            # dosificación o clínica. Por ejemplo, Amoxicilina-clavulánico posee distintos puntos de corte en función de su
            # su dosificación (oral o intravenosa) y la clínica asociada (ITU no complicada, asociada a ITU, otras)
            resultados_variantes = self._apply_eucast_breakpoints(
                antibiotico_hospital, cmi_float, halo_float,
                version_eucast, microorganismo, edad, sexo_obj, muestra_obj
            )

            # Se agregan sólo las variantes que apliquen (el BASE ya se guardó)
            if resultados_variantes:
                # Filtrar para no sobrescribir el base si viene en resultados_variantes
                for var_id, resultado in resultados_variantes.items():
                    if var_id != antibiotico_base.id:  # Solo agregar variantes, no el base
                        resultados_procesados[var_id] = resultado
                        print(f"   ✅ Variante agregada: ID {var_id} - {resultado[0]}")

        return resultados_procesados


    @staticmethod
    def _parse_mic_and_halo(cmi_valor: str | None, halo_valor: str | None) -> tuple[float | None, float | None]:
        """Parsea CMI y halo"""
        # inicicalizamos variables
        cmi_float = None
        halo_float = None

        try:  # intentamos parsear el valor de CMI
            if cmi_valor is not None:
                cmi_float = parse_mic(cmi_valor)
                print(f"La CMI que tengo es: {cmi_float}")

            # también intentamos pasear el valor del halo
            if halo_valor is not None:
                halo_float = parse_halo(halo_valor)
                print(f"El halo que tengo es: {halo_float}")

        except Exception as e:  # mostramos el error en el log, si lo hay
            print(f"No pude parsear el valor: {e}")

        return cmi_float, halo_float  # devolvemos tupla con los valores float o None para CMI y mm

    @staticmethod
    def _get_interpretation(interpretacion: str | None, alias_hospital: list[AliasInterpretacionHospital]) -> str:
        """Procesa la interpretación usando los alias del hospital.
        Cada hospital define los resultados de categorías de interpretación disponibles
        en sus exportaciones (P.ej: "sensible" puede ser "S" o "sen", etc).
        El método se encarga de devolver una cadena de texto estandarizada: 'S' para sensibles,
        'R' para resistentes e 'I', que puede ser intermedio o sensible a dosis incrementadas
        """
        interpretacion_std = "ND"  # inicializamos como no disponible "ND"

        if interpretacion is not None:  # si interpretacion NO es None
            for alias in alias_hospital:  # por alias del hospital
                std = alias.get_standard_interp(interpretacion)  # obtener el valor de interpretación estándar

                if std:
                    interpretacion_std = std  # se almacena el valor estándar y salimos del bucle
                    break

            # Si la interpretación estándar es "ND", intentar directamente por su valor si se corresponde con una categoría
            if interpretacion_std == "ND" and interpretacion.strip().upper() in ["S", "R", "I"]:
                interpretacion_std = interpretacion.strip().upper()

        return interpretacion_std  # devuelve la cadena de interpretación

    @staticmethod
    def _apply_eucast_breakpoints(antibiotico_hospital: AntibioticoHospital,
                                  cmi: float | None,
                                  halo: float | None,
                                  version_eucast: EucastVersion,
                                  microorganismo: MicroorganismoHospital,
                                  edad: float | None,
                                  sexo_obj: SexoHospital,
                                  muestra_obj: TipoMuestraHospital) -> dict[
        int, tuple[str | None, float | None, float | None]]:
        """Aplica reglas EUCAST y retorna resultados SOLO para las variantes que aplican"""


        resultados = {}
        antibiotico_base = antibiotico_hospital.antibiotico

        # Buscamos SOLO las variantes relacionadas en la base de datos
        variantes_relacionadas = list(  #list[Antibiotico]
            Antibiotico.objects.filter(parent=antibiotico_base)
        )

        if not variantes_relacionadas:
            print(f"ℹ️ No hay variantes para {antibiotico_base.nombre}")
            return resultados  # Diccionario vacío

        # Buscamos reglas aplicables SOLO para las variantes
        reglas_aplicables = ReglaInterpretacion.objects.filter(
            antibiotico__in=variantes_relacionadas,
            version_eucast=version_eucast
        )

        if not reglas_aplicables.exists():  # si no hay reglas asociadas se devuelve el diccionario vacío
            print(f"ℹ️ No hay reglas EUCAST para variantes de {antibiotico_base.nombre} (versión {version_eucast})")
            return resultados  # Diccionario vacío

        # Aplicamos reglas de una en una
        for regla in reglas_aplicables:

            aplica = regla.apply_to(  # comprobamos si la regla aplica a través de su método apply_to()
                antibiotico=regla.antibiotico,
                microorganismo=microorganismo,
                grupo_eucast=microorganismo.microorganismo.grupo_eucast,
                edad=edad,
                sexo=sexo_obj.sexo,
                categoria_muestra=muestra_obj,
                version_eucast=version_eucast
            )
            # si no aplica la regla del bucle, log de descarte en la consola y continuar con a siguiente regla
            if not aplica:
                print(f"❌ Regla descartada: {regla.antibiotico.nombre} ({regla.version_eucast})")
                continue

            # si la regla aplica obtenemos la interpretación con su método interpret()
            print(f"✅ Regla aplicada correctamente: {regla.antibiotico.nombre}")
            print(f"   CMI: {cmi}, Halo: {halo}")

            # aplica la regla con CMI y halo
            interp_regla = regla.interpret(cmi=cmi, halo=halo)

            # Guardamos la variante con su interpretación
            resultados[regla.antibiotico.id] = (interp_regla, cmi,
                                                halo)  # incorporamos los resultados de interpretación
                                                       # al dicccionario contenedor
            print(f"   Interpretación resultante: {interp_regla}")

        return resultados  # devolvemos el diccionario

    @staticmethod
    def _get_arm(row: pandas.Series, mapping: dict,
                 resultados_procesados: dict[int, tuple[str | None, float | None, float | None]],
                 mecanismos: list[MecanismoResistenciaHospital], subtipos: list[SubtipoMecanismoResistenciaHospital],
                 pos_vals: list[MecResValoresPositivosHospital]) -> tuple[
        set[MecanismoResistenciaHospital],
        set[SubtipoMecanismoResistenciaHospital],
        dict[int, tuple[str | None, float | None, float | None]]
    ]:
        """Detecta mecanismos y aplica resistencias adquiridas.
        Devuelve una tupla con sets de los objetos MecanismoResistenciaHospital y
        SubtipoMecanismoResistenciaHospital,y un diccionario con los ids de los antibióticos
        y tuplas de interpretación actualizados
        """

        # detectamos los mecanismos y subtipos de mecanismos asociados al registro de fila
        mech_detectados, sub_detectados = detect_arm(
            row, mapping, mecanismos, subtipos, pos_vals
        )

        # obtenemos los ids de antibióticos a los que afecta la resistencia adquirida
        # unión de conjuntos con el operador |=
        antibioticos_resistentes_ids = set(
            MecanismoResistenciaHospital.objects
            .filter(id__in=[m.id for m in mech_detectados])
            .values_list("resistencia_adquirida__id", flat=True)
        )
        antibioticos_resistentes_ids |= set(  # unión de conjuntos
            SubtipoMecanismoResistenciaHospital.objects
            .filter(id__in=[s.id for s in sub_detectados])
            .values_list("resistencia_adquirida__id", flat=True)
        )

        # copia de resultados finales
        resultados_finales = dict(resultados_procesados)

        # interpretación final de los resultados obtenidos
        for id in antibioticos_resistentes_ids:  # para cada id en el conjunto antibioticos_resistentes_ids
            if id in resultados_finales:  # si el id está en el diccionario de resultados_finales

                # sólo modificamos si la interpretación actual no es ND/NA ni ya es resistente
                interp_actual, cmi_actual, halo_actual = resultados_finales[id]
                if interp_actual not in ["NA", "ND"] and interp_actual != "R":
                    print(f"🟠 Aplicando resistencia adquirida: {interp_actual} -> R")
                    resultados_finales[id] = ("R", cmi_actual, halo_actual)  # conservamos los valores de CMI y mm

        return mech_detectados, sub_detectados, resultados_finales  # devuelve la tupla de resultados

    @staticmethod
    def _is_duplicated(registro: Registro, microorganismo: MicroorganismoHospital,
                       resultados_finales:
                       dict[int, tuple[str | None, float | None, float | None]]
                       ):
        """Verifica si ya existe un aislado idéntico (comparando interpretación, CMI y halo)"""

        # buscamos en la base de datos el Aislado asociado al Registro pasado como argumento
        aislados_existentes = Aislado.objects.filter(
            registro=registro,
            microorganismo=microorganismo
        ).prefetch_related("resultados__antibiotico__antibiotico")  # prefetch del Antibiotico asociado al Aislado

        # normalizamos los resultados nuevos (redondear a 3 decimales para comparación)
        resultados_normalized = {
            ab_id: (
                interp,
                round(float(cmi), 3) if cmi is not None else None,
                round(float(halo), 3) if halo is not None else None
            )
            for ab_id, (interp, cmi, halo) in resultados_finales.items()
        }

        # recorremos los objetos Aislado extraídos de la base de datos
        for a_existente in aislados_existentes:

            # normalizamos los resultados numéricos de ResultadoAntibiotico
            res_existentes = {
                r.antibiotico.antibiotico.id: (
                    r.interpretacion,
                    round(float(r.cmi), 3) if r.cmi is not None else None,
                    round(float(r.halo), 3) if r.halo is not None else None
                )
                for r in a_existente.resultados.all()
                # Nota: para ResultadoAntibiotico hay un FK a Aislado con relación "resultados"
            }

            print(f"  Comparando con aislado {a_existente.id}:")
            print(f"    Existente: {res_existentes}")
            print(f"    Nuevo:     {resultados_normalized}")

            # Si los resultados son idénticos -> ES UN DUPLICADO -> devuelve True
            if res_existentes == resultados_normalized:
                print(f"  ❌ DUPLICADO DETECTADO")
                return True

        return False  # si no son idénticos devuelve FALSE

    @staticmethod
    def _create_isolate(registro: Registro, hospital: Hospital, version_eucast: EucastVersion,
                        microorganismo: MicroorganismoHospital,
                        resultados_finales: dict[int, tuple[str | None, float | None, float | None]],
                        mech_detectados: set[MecanismoResistenciaHospital],
                        sub_detectados: set[SubtipoMecanismoResistenciaHospital],
                        resistencias_intrinsecas: set[int]):

        """Crea el objeto Aislado con todos sus resultados (interpretación, CMI y halo)"""
        aislado = Aislado.objects.create(
            registro=registro,
            hospital=hospital,
            version_eucast=version_eucast,
            microorganismo=microorganismo
        )

        # Asignamos mecanismos de resistencia detectados
        aislado.mecanismos_resistencia.set(mech_detectados)
        aislado.subtipos_resistencia.set(sub_detectados)

        # Crea los resultados
        # 1. Busca entre los resultados finales el Antibiotico base
        for id, (interp, cmi, halo) in resultados_finales.items():
            try:
                antibiotico_obj = Antibiotico.objects.get(pk=id)
            except Antibiotico.DoesNotExist:
                print(f"⚠️ Antibiótico id {id} no existe, se omite")
                continue

            # 2. Extrae o crea el AntibioticoHospital asociado al Antibiotico
            ab_hosp, created = AntibioticoHospital.objects.get_or_create(
                antibiotico=antibiotico_obj,
                hospital=hospital
            )

            if created:
                print(f"🆕 AntibioticoHospital creado para {antibiotico_obj.nombre}")

            # 3. Verifica la resistencia intrínseca
            interp_to_save = "R" if id in resistencias_intrinsecas else interp

            # 4. Verificación de resultados: NO guardamos resultados completamente vacíos
            # Si la interpretación es None o "ND", Y no hay CMI ni halo, lo omitimos
            if interp_to_save in ["ND", None] and cmi is None and halo is None:
                print(f"⚠️ Resultado vacío para {antibiotico_obj.nombre}, se omite")
                continue

            # 5. Crea el objeto ResultadoAntibiotico
            print(
                f"💾 Guardando resultado: {antibiotico_obj.nombre} - Interp: {interp_to_save}, CMI: {cmi}, Halo: {halo}")

            ResultadoAntibiotico.objects.create(
                aislado=aislado,
                antibiotico=ab_hosp,
                interpretacion=interp_to_save,
                cmi=cmi,
                halo=halo
            )

    def _show_final_messages(self, contadores: dict, count_huerfanos: int):
        """Muestra todos los mensajes finales de resultado"""
        if contadores["registros_creados"]:
            messages.success(self.request,
                             f"{contadores["registros_creados"] - count_huerfanos} registros nuevos creados.")
        if contadores["registros_reutilizados"]:
            messages.info(self.request, f"{contadores["registros_reutilizados"]} registros reutilizados.")
        if contadores["registros_errores"]:
            messages.error(self.request,
                           f"{contadores["registros_errores"]} filas no se pudieron cargar debido a errores.")
        if contadores["aislados_creados"]:
            messages.success(self.request, f"{contadores["aislados_creados"]} aislados creados correctamente.")
        if contadores["duplicados_omitidos"]:
            messages.warning(self.request,
                             f"{contadores["duplicados_omitidos"]} aislados ignorados por duplicados exactos.")
        if contadores["errores_resultados"]:
            messages.warning(self.request, f"{contadores["errores_resultados"]} resultados de antibiograma inválidos.")


@login_required
def search_antibiotics(request):
    """Función de vista de resultados de objetos AntibioticoHospital para AJAX"""
    term = request.GET.get("q", "")
    hospital = request.user.hospital  # La vista tiene el decorador de login requerido -> habrá un hospital asociado por
                                      # usuario

    # Obtenemos los objetos AntibioticoHospital del hospital del usuario
    # recogiendo los nombres del Antibiotico asociado
    antibioticos = AntibioticoHospital.objects.filter(
        hospital=hospital,
        antibiotico__nombre__icontains=term,
        antibiotico__es_variante=False
    ).select_related("antibiotico").order_by("antibiotico__nombre")[:20]

    # formamos el JSON con la id del AntibioticoHospital y el nombre del
    # Antibiotico asociado
    results = [
        {"id": a.id, "text": a.antibiotico.nombre}
        for a in antibioticos
    ]

    # Enviamos la respuesta como JsonResponse en la clave 'results'
    return JsonResponse({"results": results})


# Aplica un decorador de autorización a las peticiones GET de la vista basada en clases.
# ref: https://docs.djangoproject.com/en/5.2/topics/class-based-views/intro/#decorating-the-class
@method_decorator(role_required("microbiologo"), name="get")
class ListarRegistrosView(ListView):
    """ListView de Django para los objetos Registro"""
    model = Registro
    template_name = "CRUD/lista_registros.html"
    context_object_name = "registros"
    paginate_by = 25

    # Sobreescribimos el método get_queryset, método que devuelve el queryset de la vista para añadirle
    # el filtro de objetos Registro por hospital del usuario
    #
    # ref: https://docs.djangoproject.com/en/5.2/topics/class-based-views/generic-display/#dynamic-filtering
    def get_queryset(self):
        hospital = self.request.user.hospital
        queryset = Registro.objects.filter(hospital=hospital).distinct()

        # Formulario de filtros de la vista
        form = FiltroRegistroForm(self.request.GET, hospital=hospital)

        # Cuando se envían nuevas selecciones en el formulario, se filtran resultados con las siguientes querys
        if form.is_valid():
            fecha_inicio = form.cleaned_data.get("fecha_inicio")
            fecha_fin = form.cleaned_data.get("fecha_fin")
            microorganismo = form.cleaned_data.get("microorganismo")
            mecanismo = form.cleaned_data.get("mecanismo")
            antibioticos = form.cleaned_data.get("antibiotico")  # ← puede haber varios

            if fecha_inicio:
                queryset = queryset.filter(fecha__gte=fecha_inicio)  # mayor o igual a la fecha inicio
            if fecha_fin:
                queryset = queryset.filter(fecha__lte=fecha_fin)  # menor o igual a la fecha fin
            if microorganismo:
                queryset = queryset.filter(aislados__microorganismo=microorganismo)  # microorganismo
            if mecanismo:
                queryset = queryset.filter(aislados__mecanismos_resistencia=mecanismo)  # mecanismo de resistencia

            # Si antibióticos en los datos procesados: filtro de registros con aislados RESISTENTES a los antibióticos seleccionados
            if antibioticos:
                queryset = queryset.filter(
                    aislados__resultados__antibiotico__in=antibioticos,
                    aislados__resultados__interpretacion="R"
                )

            # Guardamos los filtros en la sesión
            filtros_serializables = {
                "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else None,
                "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
                "microorganismo": microorganismo.id if microorganismo else None,
                "mecanismo": mecanismo.id if mecanismo else None,
            }
            self.request.session["filtros_activos"] = filtros_serializables

        else:
            # Si no hay GET o el formulario es inválido -> limpiamos los filtros previos
            self.request.session["filtros_activos"] = {}

        # Se devuelve la query re-filtrada con los filtros del formulario
        return queryset.distinct().prefetch_related(
            "aislados__resultados__antibiotico__antibiotico",
            "aislados__microorganismo",
            "aislados__mecanismos_resistencia__mecanismo",
            "aislados__subtipos_resistencia__subtipo_mecanismo",
        )

    # Sobreescribimos el método get_context_data() que el el encargado de tomar el contexto
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Añadimos al contexto el formulario y le pasamos el hospital para inicializarlo
        context["form"] = FiltroRegistroForm(self.request.GET or None,
                                             hospital=self.request.user.hospital)
        return context


def apply_filters_to_queryset(queryset, filtros: dict) -> QuerySet[Registro, Registro]:
    """Función auxiliar para la vista de función eliminar_registros_batch.
    Genera un QuerySet en base a los filtros del formulario FiltroRegistroForm
    para obtener los objetos Registros a eliminar si se selecciona la opción de
    eliminar todos los elementos filtrados """

    # Recupera los valores del diccionario
    fecha_inicio = filtros.get("fecha_inicio")
    fecha_fin = filtros.get("fecha_fin")
    microorganismo = filtros.get("microorganismo")
    mecanismo = filtros.get("mecanismo")

    if fecha_inicio:
        try:
            fecha_inicio = datetime.fromisoformat(fecha_inicio).date()
            queryset = queryset.filter(fecha__gte=fecha_inicio)
        except ValueError:
            pass

    if fecha_fin:
        try:
            fecha_fin = datetime.fromisoformat(fecha_fin).date()
            queryset = queryset.filter(fecha__lte=fecha_fin)
        except ValueError:
            pass

    if microorganismo:
        # filtra por id del MicroorganismoHospital
        queryset = queryset.filter(aislados__microorganismo__id=microorganismo)

    if mecanismo:
        # filtra por id del MecanismoResistenciaHospital
        queryset = queryset.filter(aislados__mecanismos_resistencia__id=mecanismo)

    # Evita duplicados cuando hay relaciones ManyToMany
    return queryset.distinct()


@require_POST
def eliminar_registros_batch(request):
    """Función de vista encargada de eliminar Registros, en función de la opción seleccionada"""
    modo = request.POST.get("modo")
    ids = request.POST.getlist("registro_ids")
    hospital = getattr(request.user, "hospital", None)

    if not hospital:
        messages.error(request, "No se pudo determinar el hospital del usuario.")
        return redirect("CRUD:listar_registros")  # fallback en caso de error

    # Filtramos siempre por hospital del usuario
    registros_base = Registro.objects.filter(hospital=hospital)

    if modo == "pagina":
        registros = registros_base.filter(id__in=ids)

    elif modo == "todos":
        filtros = request.session.get("filtros_activos", {})
        registros = apply_filters_to_queryset(registros_base,
                                              filtros)  # aplicamos la función apply_filters_to_queryset()

    else:
        registros = Registro.objects.none()  # ningún Registro

    total = registros.count()

    if total > 0:
        ids_to_delete = list(registros.values_list("id", flat=True))
        Registro.objects.filter(id__in=ids_to_delete).delete()  # Eliminamos los Registros por su id
        messages.success(request, f"Se eliminaron {total} registros del hospital {hospital.nombre}.")
    else:
        messages.info(request, "No se encontraron registros para eliminar.")

    return redirect("CRUD:listar_registros")


@method_decorator(role_required("microbiologo"), name="get")
class RegistroDetailView(DetailView):
    """DetailView de Django para un objeto Registro"""
    model = Registro
    template_name = "CRUD/registro_ver.html"
    context_object_name = "registro"

    # En ListView trabajamos con un conjunto de resultados (Queryset), sin embargo, en una DetailView
    # solo trabajamos con 1 objeto (Registro). El método a sobreescribir es get_object(). De este modo
    # extraemos información de objetos asociados el hospital del usuario.
    def get_object(self, queryset=None):
        user = self.request.user

        registro = get_object_or_404(  # obtiene un objeto o lanza Http404 si no existe
            Registro.objects.select_related(  # relaciones FK
                "hospital", "servicio", "tipo_muestra"
            ).prefetch_related(  # relaciones inversas o ManyToMany
                "aislados__microorganismo",
                "aislados__resultados__antibiotico",
                "aislados__mecanismos_resistencia",
                "aislados__subtipos_resistencia__subtipo_mecanismo",
            ),
            pk=self.kwargs["pk"],
            hospital=user.hospital,
        )

        return registro

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # añadimos los aislados al contexto
        context["aislados"] = self.object.aislados.all()

        return context


@method_decorator(role_required("microbiologo"), name="dispatch")
class RegistroUpdateView(UpdateView):
    """UpdateView de Django para objetos Registro"""
    model = Registro
    form_class = RegistroForm
    template_name = "CRUD/registro_form.html"
    context_object_name = "registro"

    def get_object(self, queryset=None):
        user = self.request.user
        return get_object_or_404(
            Registro.objects.select_related(
                "hospital", "servicio", "tipo_muestra"
            ).prefetch_related(
                "aislados__microorganismo",
                "aislados__mecanismos_resistencia__mecanismo",
                "aislados__subtipos_resistencia__subtipo_mecanismo",
                "aislados__resultados__antibiotico",
            ),
            pk=self.kwargs["pk"],
            hospital=user.hospital,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Si es un POST, reconstruimos el formulario y formset con los datos enviados
        if self.request.method == "POST":
            context["form"] = self.form_class(self.request.POST, instance=self.object)

            # Utilizamos un inline formset para editar los objetos Aislado
            context["formset"] = AisladoFormSet(self.request.POST, instance=self.object)

        # Carga inicial de la vista: mostramos los datos actuales del objeto
        else:
            context["form"] = self.form_class(instance=self.object)
            context["formset"] = AisladoFormSet(instance=self.object)

        return context

    def form_valid(self, form):
        # obtenemos el contexto para acceder al formset
        context = self.get_context_data()
        formset = context["formset"]
        hospital = self.request.user.hospital

        # validamos el form y el formset antes de guardar
        if form.is_valid() and formset.is_valid():
            try:
                # La transacción atómica permite que si algo falla, no se guarde nada
                # ref: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
                with transaction.atomic():

                    # Form
                    registro = form.save(commit=False)
                    registro.hospital = hospital  # asignamos el hospital del usuario al registro
                    registro.save()

                    # Formset
                    aislados = formset.save(commit=False)
                    for aislado in aislados:
                        aislado.registro = registro
                        aislado.save()

                        # crea el antibiograma base si no tiene resultados
                        if not ResultadoAntibiotico.objects.filter(aislado=aislado).exists():
                            grupo = aislado.microorganismo.microorganismo.grupo_eucast  # extraer el grupo EUCAST del Aislado

                            try:
                                perfil = PerfilAntibiogramaHospital.objects.get(  # Obtener el PerfilAntibiograma
                                    hospital=hospital,
                                    grupo_eucast=grupo
                                )

                                resultados = [
                                    ResultadoAntibiotico(
                                        aislado=aislado,
                                        antibiotico=ab,
                                        interpretacion="ND",
                                    )
                                    for ab in perfil.antibioticos.all()
                                ]
                                # Crea resultados en bloque
                                ResultadoAntibiotico.objects.bulk_create(resultados)

                            except PerfilAntibiogramaHospital.DoesNotExist:  # si no existe el perfil manda el mensaje al usuario
                                messages.warning(
                                    self.request,
                                    f"No hay perfil EUCAST definido para el grupo '{grupo.nombre}' en el hospital '{hospital.codigo}'"
                                )

                    # Guardar eliminaciones del formset
                    for obj in formset.deleted_objects:
                        obj.delete()

                    # Mensaje de éxito
                    messages.success(self.request, "Registro actualizado correctamente.")
                    return redirect("CRUD:listar_registros")  # Volvemos al listado de objetos Registro

            except Exception as e:  # Mensajes de excepción
                messages.error(self.request, f"Error al guardar: {str(e)}")

        # si no son válidos ambos: form y formset -> renderizamos la página de nuevo con errores
        messages.error(self.request, "Revisa los errores del formulario.")
        return self.render_to_response(self.get_context_data(form=form, formset=formset))


def editar_resultados_antibiotico(request, aislado_id: int):
    """Función de vista para editar el antibiograma de un aislado"""
    aislado = get_object_or_404(Aislado, pk=aislado_id)
    queryset = ResultadoAntibiotico.objects.filter(aislado=aislado)

    if request.method == "POST":
        formset = ResultadoFormSet(request.POST, queryset=queryset)

        if formset.is_valid():
            formset.save()
            messages.success(request, "Antibiograma actualizado correctamente.")
            return redirect("CRUD:registro_editar", pk=aislado.registro.id)  # Nos devuelve a la página anterior
        else:
            # for i, form in enumerate(formset):
            #    if form.errors:
            #        print(f"Form {i} errors:", form.errors)
            messages.error(request, "Corrige los errores en el formulario.")
    else:
        formset = ResultadoFormSet(queryset=queryset)

    return render(request, "CRUD/editar_resultados_antibiotico.html", {
        "aislado": aislado,
        "formset": formset,
    })


def editar_mecanismos_resistencia(request, aislado_id: int):
    """Función de vista para editar los mecanismos de resistencia de un aislado"""
    aislado = get_object_or_404(Aislado, pk=aislado_id)

    if request.method == "POST":

        form = MecanismoResistenciaForm(request.POST,  # formulario ModelForm
                                        instance=aislado, aislado=aislado)

        if form.is_valid():
            form.save()
            messages.success(request, "Mecanismos de resistencia actualizados.")
            return redirect("CRUD:registro_editar", pk=aislado.registro.id)  # Nos devuelve a la página anterior
        else:
            messages.error(request, "Corrige los errores en el formulario.")
    else:
        form = MecanismoResistenciaForm(instance=aislado, aislado=aislado)

    return render(request, "CRUD/editar_mecanismos_resistencia.html", {
        "form": form,
        "aislado": aislado,
    })


class RegistroDeleteView(DeleteView):
    """DeleteView de Django para objetos Registro"""
    model = Registro
    template_name = "CRUD/registro_confirm_delete.html"

    def get_queryset(self):
        # Filtramos los registros del hospital del usuario
        return Registro.objects.filter(hospital=self.request.user.hospital)

    def get_success_url(self):
        messages.success(self.request,
                         f"El registro del {self.object.fecha.strftime("%d/%m/%Y")} se eliminó correctamente.")
        return reverse_lazy("CRUD:listar_registros")
