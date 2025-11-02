# Configuración a nivel de Aplicación.

import json
import os

from django.apps import AppConfig


class BaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "Base"  # referencia para las llamadas Base:


    def ready(self):
        # Se ejecuta una vez al iniciar Django; útil para registrar señales (signals)
        # u otros aspectos para el arranque de la aplicación

        # Utilizaremos este método para precargar objetos genéricos (no hospital específicos)
        print("🚀 Lanzando app Base")

        # Evitar que se ejecute durante las migraciones
        # Fuente: https://stackoverflow.com/questions/5269810/explicitly-set-mysql-table-storage-engine-using-south-and-django
        # (respuesta de Eron Villareal, añado shell)
        import sys
        if "migrate" in sys.argv or "makemigrations" in sys.argv or "shell" in sys.argv:
            return

        try:
            # Cargamos los modelos
            from .models import (Sexo, ClaseAntibiotico, FamiliaAntibiotico,
                                 GrupoEucast, Antibiotico, Microorganismo, Servicio,
                                 Ambito, MecanismoResistencia, SubtipoMecanismoResistencia,
                                 TipoMuestra, EucastVersion, CondicionTaxonReglaInterpretacion,
                                 ReglaInterpretacion)
        except Exception as e:
            print(f"❌ No se pudieron importar los modelos: {e}")
            return

        try:
            # Empezamos las cargas. Tenemos en la carpeta fixtures los json preconfigurados para
            # poder crear objetos de distintas clases, vamos de uno en uno cargándolos

            # Sexo
            # Obtenemos la ruta al arhivo json
            # Fuente: https://stackoverflow.com/questions/28135490/django-os-path-dirname-file
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "sexos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path): # si no existe el archivo -> salimos del proceso de carga para revisar
                print("⚠️  No existe el archivo JSON")
                return

            # Si existe cargamos el json en un contexto controlado con with
            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f) # carga del json

            print(f"👫 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                # Extraemos las claves
                codigo = item.get("codigo")
                descripcion = item.get("descripcion")
                
                # Comprobamos si existe el objeto Sexo por su descripcion o no para crearlo si no
                if codigo and not Sexo.objects.filter(codigo__iexact=codigo).exists():
                    Sexo.objects.create(codigo=codigo, descripcion=descripcion)
                    print(f"👫 Creada clase sexo: {descripcion}")
            
            # A partir de aquí procedemos de forma análoga a la precarga de objetos Sexo
            # A tener en cuenta: 
            # - Algunas claves tienen valores en lista que hacen referencia a ManyToManyField. Habrá que extraer esos 
            # objetos de su modelo padre para poder asignárselos
            # - De igual forma, habrá referencias a ForeignKey, y habrá que extraer primero el objeto de su modelo padre
            # para poder asignarlo
            # Clases antibióticas
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "clases_antibioticos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"💊 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                if nombre and not ClaseAntibiotico.objects.filter(nombre__iexact=nombre).exists():
                    ClaseAntibiotico.objects.create(nombre=nombre)
                    print(f"💊 Creada clase antibiótica: {nombre}")

            # Familias antibióticas
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "familias_antibioticos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🏷️ JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                clase_nombre = item.get("clase")
                if not nombre or not clase_nombre:
                    continue

                # Buscamos la ClaseAntibiotico asociada por nombre, en este caso, es un ForeignKey para 
                # FamiliaAntibiotico en su campo clase
                clase = ClaseAntibiotico.objects.filter(nombre__iexact=clase_nombre).first()
                # Si no lo encontramos salimos del proceso de carga para revisar el json
                if not clase:
                    print(f"⚠️ Clase '{clase_nombre}' no encontrada para familia '{nombre}'")
                    continue

                if not FamiliaAntibiotico.objects.filter(nombre__iexact=nombre).exists():
                    FamiliaAntibiotico.objects.create(nombre=nombre, clase=clase)
                    print(f"🏷️  Creada familia antibiótica: {nombre} -> clase {clase.nombre}")

            # Grupos EUCAST
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "grupos_eucast.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"👪 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                if nombre and not GrupoEucast.objects.filter(nombre__iexact=nombre).exists():
                    GrupoEucast.objects.create(nombre=nombre)
                    print(f"👪 Creado grupo EUCAST: {nombre}")

            # Antibióticos
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "antibioticos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"💊 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                abr = item.get("abr")
                cid = item.get("cid", "")
                atc = item.get("atc", [])
                atc_group1 = item.get("atc_group1", "")
                atc_group2 = item.get("atc_group2", "")
                loinc = item.get("loinc", [])
                familia_nombre = item.get("familia_antibiotico")

                es_variante = item.get("es_variante", False)
                parent_nombre = item.get("parent", None)
                via_administracion = item.get("via_administracion", "")
                indicacion_clinica = item.get("indicacion_clinica", "")

                if not nombre or not familia_nombre:
                    continue

                # Buscamos la familia asociada por nombre
                familia = FamiliaAntibiotico.objects.filter(nombre__iexact=familia_nombre).first()
                if not familia:
                    print(f"⚠️ Familia '{familia_nombre}' no encontrada para antibiótico '{nombre}'")
                    continue
                
                # Ojo, tenemos para variantes una referencia a sí mismo en el campo parent, hay que buscarlo
                parent = None
                if parent_nombre:
                    parent = Antibiotico.objects.filter(nombre__iexact=parent_nombre).first()
                    if not parent:
                        print(f"⚠️ Antibiótico padre '{parent_nombre}' no encontrado para '{nombre}'")
                        return # si no encuentra el parent es posible que no se haya creado aún, revisar el jsno

                if not Antibiotico.objects.filter(nombre__iexact=nombre).exists():
                    Antibiotico.objects.create(
                        nombre=nombre,
                        abr=abr,
                        cid=cid,
                        atc=atc,
                        atc_group1=atc_group1,
                        atc_group2=atc_group2,
                        loinc=loinc,
                        familia_antibiotico=familia,
                        es_variante=es_variante,
                        parent=parent,
                        via_administracion=via_administracion,
                        indicacion_clinica=indicacion_clinica
                    )
                    print(f"💊  Creado antibiótica: {nombre} -> familia {familia.nombre}")

            # Microorganismos
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "microorganismos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")
            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON de microorganismos")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🦠 JSON cargado, {len(data)} microorganismos encontrados")

            for item in data:
                nombre = item.get("nombre")
                grupo_nombre = item.get("grupo_eucast")
                resistencia_nombres = item.get("resistencia_intrinseca", []) # puesto que son listas, fallback de lista 
                                                                             # vacía []

                if not nombre or not grupo_nombre:
                    print(f"⚠️  Microorganismo sin nombre o grupo_eucast: {item}")
                    continue

                grupo = GrupoEucast.objects.filter(nombre__iexact=grupo_nombre).first()
                if not grupo:
                    print(f"⚠️ Grupo EUCAST '{grupo_nombre}' no encontrado para '{nombre}'")
                    continue

                # Creamos el microorganismo si no existe por su nombre
                if not Microorganismo.objects.filter(nombre__iexact=nombre).exists():
                    micro = Microorganismo.objects.create(
                        nombre=nombre,
                        grupo_eucast=grupo,
                        ftype=item.get("ftype", ""),
                        mtype=item.get("mtype", ""),
                        reino=item.get("reino", ""),
                        phylum=item.get("phylum", ""),
                        clase=item.get("clase", ""),
                        orden=item.get("orden", ""),
                        familia=item.get("familia", ""),
                        genero=item.get("genero", ""),
                        especie=item.get("especie", ""),
                        tolerancia_oxigeno=item.get("tolerancia_oxigeno", ""),
                        lpsn=item.get("lpsn", ""),
                        lpsn_parent=item.get("lpsn_parent", ""),
                        lpsn_renamed_to=item.get("lpsn_renamed_to", ""),
                        gbif=item.get("gbif", ""),
                        gbif_parent=item.get("gbif_parent", ""),
                        gbif_renamed_to=item.get("gbif_renamed_to", ""),
                        snomed=item.get("snomed", []),
                    )

                    # Asignamos los antibióticos de resistencia intrínseca
                    antibioticos = Antibiotico.objects.filter(nombre__in=resistencia_nombres)
                    micro.resistencia_intrinseca.set(antibioticos)
                    print(f"🧫 {nombre}: añadidos {antibioticos.count()} antibióticos de resistencia intrínseca")
                    print(f"✅ Microorganismo creado: {nombre} -> grupo {grupo.nombre}")

            # Ámbitos
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "ambitos.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🚑 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                if nombre and not Ambito.objects.filter(nombre__iexact=nombre).exists():
                    Ambito.objects.create(nombre=nombre)
                    print(f"🚑 Creado ámbito: {nombre}")

            # Servicios
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "servicios.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🏥 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                if nombre and not Servicio.objects.filter(nombre__iexact=nombre).exists():
                    Servicio.objects.create(nombre=nombre)
                    print(f"🏥 Creado servicio: {nombre}")

            # Mecanismos de resistencia
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "mecanismos_resistencia.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")
            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON de mecanismos de resistencia")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🧬 JSON cargado, {len(data)} mecanismos de resistencia encontrados")

            for item in data:
                nombre = item.get("nombre")
                descripcion = item.get("descripcion")
                grupos_nombres = item.get("grupos_eucast", [])
                microorganismos_nombres = item.get("microorganismos", [])
                if not nombre:
                    print(f"⚠️  Mecanismo de resistencia sin nombre: {item}")
                    continue

                # Creamos el microorganismo si no existe
                if not MecanismoResistencia.objects.filter(nombre__iexact=nombre).exists():
                    mec_res = MecanismoResistencia.objects.create(
                        nombre=nombre,
                        descripcion=descripcion
                    )

                    # Asignamos grupos Eucast y microorganismos
                    grupos_eucast = GrupoEucast.objects.filter(nombre__in=grupos_nombres)
                    mec_res.grupos_eucast.set(grupos_eucast)
                    microorganismos = Microorganismo.objects.filter(nombre__in=microorganismos_nombres)
                    mec_res.microorganismos.set(microorganismos)

                    print(f"🧬 {nombre}: añadidos {grupos_eucast.count()} grupos EUCAST")
                    print(f"🧬 {nombre}: añadidos {microorganismos.count()} microorganismos")
                    print(f"✅ Mecanismo de resistencia creado: {nombre}")

            # Subtipos mecanismos de resistencia
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "sutipos_mecanismo_resistencia.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"⚕️ JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                mecanismo_nombre = item.get("mecanismo")
                if not nombre or not mecanismo_nombre:
                    continue

                # Buscar el mecanismo asociado por nombre
                mecanismo = MecanismoResistencia.objects.filter(nombre__iexact=mecanismo_nombre).first()
                if not mecanismo:
                    print(f"⚠️ Mecanismo '{mecanismo_nombre}' no encontrada para familia '{nombre}'")
                    continue

                if not SubtipoMecanismoResistencia.objects.filter(nombre__iexact=nombre).exists():
                    SubtipoMecanismoResistencia.objects.create(nombre=nombre, mecanismo=mecanismo)
                    print(f"️⚕️ Creado subtipo mecanismo de resistencia: {nombre} -> mecanismo {mecanismo.nombre}")

            # Tipos de muestras
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "tipos_muestras.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"💉 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                nombre = item.get("nombre")
                snomed = item.get("snomed")
                codigos_loinc = item.get("loinc", [])

                if not nombre:
                    continue

                if not TipoMuestra.objects.filter(nombre__iexact=nombre).exists():
                    TipoMuestra.objects.create(
                        nombre=nombre,
                        snomed=snomed,
                        codigos_loinc=codigos_loinc
                    )
                    print(f"💉  Creada muestra: {nombre}")

            # Versiones EUCAST
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "versiones_eucast.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"📘 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                anyo = item.get("anyo")
                version = item.get("version")
                fecha_inicio = item.get("fecha_inicio")
                fecha_fin = item.get("fecha_fin")
                if anyo and not EucastVersion.objects.filter(anyo=anyo).exists():
                    EucastVersion.objects.create(
                        anyo=anyo,
                        version=version,
                        fecha_inicio=fecha_inicio,
                        fecha_fin=fecha_fin
                    )
                    print(f"📘 Creada versión EUCAST: {anyo}")

            # Condiciones taxón
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "condicion_taxon.json"
            )

            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"🦠 JSON cargado, {len(data)} elementos encontrados")

            for item in data:
                scope = item.get("scope")
                incluye_nombres = item.get("incluye", [])
                excluye_nombres = item.get("excluye", [])
                descripcion = item.get("descripcion")

                if scope and descripcion and not CondicionTaxonReglaInterpretacion.objects.filter(
                        scope=scope,
                        descripcion=descripcion,
                ).exists():
                    cond = CondicionTaxonReglaInterpretacion.objects.create(
                        scope=scope,
                        descripcion=descripcion,
                    )
                    incluye = Microorganismo.objects.filter(nombre__in=incluye_nombres)
                    excluye = Microorganismo.objects.filter(nombre__in=excluye_nombres)
                    cond.incluye.set(incluye)
                    cond.excluye.set(excluye)
                    print(f"📘 Creada condición taxonómica: {descripcion}")

            # Condiciones taxón
            fixtures_path = os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "reglas_interpretacion.json"
            )
            print(f"📄 Buscando JSON en: {fixtures_path}")

            if not os.path.exists(fixtures_path):
                print("⚠️  No existe el archivo JSON")
                return

            with open(fixtures_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(f"📘 JSON cargado, {len(data)} elementos encontrados")

            from django.db import transaction
            with transaction.atomic():
                for item in data:
                    antibiotico_nombre = item.get("antibiotico")
                    grupo_eucast_nombre = item.get("grupo_eucast")
                    condiciones_taxonomicas_nombres = item.get("condiciones_taxonomicas", [])
                    categorias_muestra_nombres = item.get("categorias_muestra", [])
                    edad_min = item.get("edad_min")
                    edad_max = item.get("edad_max")
                    sexo_nombre = item.get("sexo")
                    s_cmi_max = item.get("s_cmi_max")
                    r_cmi_min = item.get("r_cmi_min")
                    s_halo_min = item.get("s_halo_min")
                    r_halo_max = item.get("r_halo_max")
                    version_eucast_nombre = item.get("version_eucast")
                    comentario = item.get("comentario", "")

                    antibiotico = Antibiotico.objects.filter(nombre__iexact=antibiotico_nombre).first()
                    grupo_eucast = GrupoEucast.objects.filter(nombre__iexact=grupo_eucast_nombre).first()
                    sexo = Sexo.objects.filter(descripcion__iexact=sexo_nombre).first()
                    version_eucast = EucastVersion.objects.filter(version__iexact=version_eucast_nombre).first()

                    if not (antibiotico and grupo_eucast and version_eucast):
                        print(f"⚠️  Faltan datos esenciales para {antibiotico_nombre}")
                        continue

                    condiciones_taxonomicas = CondicionTaxonReglaInterpretacion.objects.filter(
                        descripcion__in=condiciones_taxonomicas_nombres
                    )

                    reglas_existentes = ReglaInterpretacion.objects.filter(
                        antibiotico=antibiotico,
                        grupo_eucast=grupo_eucast,
                        version_eucast=version_eucast
                    )

                    existe = any(
                        set(regla.condiciones_taxonomicas.values_list("id", flat=True)) ==
                        set(condiciones_taxonomicas.values_list("id", flat=True))
                        for regla in reglas_existentes
                    )

                    if existe:
                        continue

                    regla = ReglaInterpretacion.objects.create(
                        antibiotico=antibiotico,
                        grupo_eucast=grupo_eucast,
                        edad_min=edad_min,
                        edad_max=edad_max,
                        sexo=sexo,
                        s_cmi_max=s_cmi_max,
                        r_cmi_min=r_cmi_min,
                        s_halo_min=s_halo_min,
                        r_halo_max=r_halo_max,
                        version_eucast=version_eucast,
                        comentario=comentario
                    )
                    regla.condiciones_taxonomicas.set(condiciones_taxonomicas)
                    regla.categorias_muestra.set(TipoMuestra.objects.filter(nombre__in=categorias_muestra_nombres))

                    print(f"📘 Creada regla EUCAST {version_eucast.version} para {antibiotico.nombre}")

            print("✅ Carga de datos iniciales finalizada")

        except Exception as e:
            print(f"❌ Error cargando datos iniciales: {e}")
            import traceback
            traceback.print_exc()
