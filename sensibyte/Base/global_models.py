# global_models.py: definiciones de los modelos de Django. Los modelos representan las tablas de la base de datos
# Sólo se incluyen los modelos a nivel GENERAL, NO los específicos de cada HOSPITAL
#
# Ver models.py para más información

# Para prevenir problemas de importación circular.
# ref: https://medium.com/@k.a.fedorov/type-annotations-and-circular-imports-0a8014cd243b
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Base.models import MicroorganismoHospital, TipoMuestraHospital

from datetime import date

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


# Modelo Hospital
class Hospital(models.Model):
    """ Modelo de clase Hospital.
    Define el hospital al que pertenecerán los usuarios."""
    nombre = models.CharField(max_length=200, unique=True)
    codigo = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)

    def _validar_logo(self):
        """Para evitar que se suban imágenes pesadas, límite de 2MB. Para .png es suficiente
        Se utiliza como argumento para el parámetro "validators" del ImageField"""
        if self.size > 2 * 1024 * 1024:
            raise ValidationError("El tamaño máximo permitido del logo es de 2 MB")

    logo = models.ImageField(upload_to="hospitales/logos/",
                             blank=True, null=True,
                             validators=[_validar_logo])

    def __str__(self):
        return self.nombre

    def logo_preview(self):
        """Muestra una vista previa del logo en el panel admin"""
        if self.logo:
            return f'<img src="{self.logo.url}" width="80" height="80" style="object-fit:contain;border:1px solid #ccc;">'
        return "(sin logo)"

    logo_preview.short_description = "Logo"
    logo_preview.allow_tags = True  # opcional, para compatibilidad con Django<4

    class Meta:
        verbose_name_plural = "Hospitales"  # en plural para visualizaciones


# Modelo Usuario, heredando de AbstractUser incluido en Django
class Usuario(AbstractUser):
    """
    Clase abstracta con las definiciones de tipos de usuarios
    y sus roles. Se asocia a un objeto de la clase Hospital
    a través de un campo ForeignKey
    """
    ROLES = [
        ("admin", "Administrador"),
        ("microbiologo", "Microbiólogo"),
        ("clinico", "Clínico"),
        ("tecnico", "Técnico"),
    ]
    rol = models.CharField(max_length=12, choices=ROLES,
                           default="tecnico")
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT,
                                 related_name="usuarios", null=True, blank=True)

    def __str__(self):
        # un superusuario no tiene hospital asociado
        return f"{self.username} ({self.hospital.nombre if self.hospital else 'SuperUsuario'})"


# Modelo Antibiotico
class ClaseAntibiotico(models.Model):
    """ Modelo que define la clase de un antibiótico. Por ejemplo:
    beta-lactámico"""
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre


# Modelo FamiliaAntibiotico
class FamiliaAntibiotico(models.Model):
    """ Modelo que define la familia del antibiótico.
    Se relaciona con la clase de antibiótico a través de un FK
    en su campo "clase".
    Por ejemplo: la ampicilina pertenece a la familia de las penicilinas,
    de la clase de los beta-lactámicos. """
    nombre = models.CharField(max_length=50, unique=True)
    clase = models.ForeignKey(ClaseAntibiotico, on_delete=models.PROTECT)

    def __str__(self):
        return self.nombre


# Modelo Espectro
# De momento anulo este modelo. En realidad, incluso
# antibióticos como vancomicina pueden tener excepciones
# en gram negativos. Por otro lado, La resistencia intrínseca
# la estoy acomodando en el campo correspondiente en microorganismo
# class Espectro(models.Model):
#    """ Modelo que define el espectro de acción de un antibiótico
#    (simplificado): gram positivos (gp), gram negativos (gn), anaerobios (ana)
#    y bacterias atípicas (aty) """
#    gp = models.BooleanField(default=False)
#    gn = models.BooleanField(default=False)
#    ana = models.BooleanField(default=False)
#    aty = models.BooleanField(default=False)

#    def __str__(self):
#        spctr = []
#        if self.gp: spctr.append("Gram Positivos")
#        if self.gn: spctr.append("Gram Negativos")
#        if self.ana: spctr.append("Anaerobios")
#        if self.aty: spctr.append("Atípicos")
#        return ", ".join(spctr) if spctr else "Sin espectro definido"


# Modelo Antibiotico
class Antibiotico(models.Model):
    """ Modelo que define un Antibiotico.
    Campos:
        - nombre (string): nombre del antibiótico
        - abr (string): abreviatura del antibiótico
        - cid (string): código PubMed CID del antibiótico: https://pubchem.ncbi.nlm.nih.gov/
        - familia_antibiotico: FK de FamiliaAntibiotico
        - atc (JSONField): códigos ATC asociados al antibiótico: https://www.atccode.com/
        - atc_group1 (string): subgrupo farmacológico (3er nivel de codificación ATC) definido por WHOCC
        - atc_group2 (string): subgrupo químico (4º nivel de codificación ATC) definido por WHOCC
        - loinc (JSONField): códigos LOINC asociados al antibiótico: https://loinc.org/wp-login.php?redirect_to=https%3A%2F%2Floinc.org%2Fsearch%2F&reauth=1
        (requiere abrirse una cuenta, gratuita. Dependiendo del método utilizado hay distintos códigos asociados. También se puede googlear)
        - es_variante (bool): si el antibiótico es variante de un Antibiotico padre
        - parent: FK a sí mismo, es el antibiótico padre de una variante
        - via_administracion (string): la vía de administración de una variante
        - indicacion_clinica (string): indicación clínica de una variante
    Este modelo es heredable por el modelo AntibioticoHospital propio de un Hospital
    """
    nombre = models.CharField(max_length=90, unique=True)
    abr = models.CharField(max_length=5, unique=True)
    cid = models.CharField(max_length=20, blank=True)
    familia_antibiotico = models.ForeignKey(FamiliaAntibiotico, on_delete=models.PROTECT)
    # espectro = models.ForeignKey(Espectro, on_delete=models.PROTECT)
    atc = models.JSONField(default=list, blank=True)
    atc_group1 = models.CharField(max_length=80, blank=True)
    atc_group2 = models.CharField(max_length=80, blank=True)
    loinc = models.JSONField(default=list, blank=True)

    # Para las variantes por vía de administración o indicación clínica
    es_variante = models.BooleanField(default=False)
    parent = models.ForeignKey("Antibiotico", null=True, blank=True, on_delete=models.CASCADE)
    ADMIN_VIA = [
        ("iv", "IV"),
        ("oral", "Oral"),
    ]
    CLINICAL_IND = [
        ("ncITU", "Sólo ITU no complicada"),
        ("ioITU", "Infección originada en el tracto urinario"),
        ("menin", "Meningitis"),
        ("neumo", "Neumonía"),
        ("cneum", "Neumonía de adquisición comunitaria"),
        ("inppb", "Infección de piel y partes blandas"),
        ("endme", "Endocarditis y meningitis"),
        ("otrnm", "Otras indicaciones no meningitis"),
        ("otnem", "Otras indicaciones no endocarditis y meningitis"),
        ("otrnm", "Otras indicaciones no neumonía"),
        ("sitem", "Infección sistémica"),
        ("otras", "Otras indicaciones"),
    ]
    via_administracion = models.CharField(max_length=12, choices=ADMIN_VIA,  # restringimos las opciones
                                          blank=True)
    indicacion_clinica = models.CharField(max_length=12, choices=CLINICAL_IND,  # restringimos las opciones
                                          blank=True)

    def __str__(self):
        return f"{self.nombre} ({self.familia_antibiotico} / {self.familia_antibiotico.clase})"


# Modelo GrupoEucast
class GrupoEucast(models.Model):
    """ Modelo que define el grupo de EUCAST al que pertenece un microorganismo
    Por ejemplo: E. coli pertenece a Enterobacterales """
    nombre = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Grupo EUCAST"
        verbose_name_plural = "Grupos EUCAST"

    def __str__(self):
        return self.nombre


# Modelo Microorganismo
class Microorganismo(models.Model):
    """ Modelo que define un microorganismo. Se relaciona con varios Antibioticos en
    su campo "resistencia_intrinseca" mediante un ManyToMany, y establece una relación
    varios a uno con "grupo_eucast".
    Campos:
        - nombre (string): nombre oficial del microorganismo
        - grupo_eucast: FK a GrupoEucast
        - ftype (string): tipo de forma del microorganismo (cocos, bacilos)
        - mtype (string): tipo de microorganismo
        - reino (string): categoría taxonómica de reino
        - phylum (string): categoría taxonómica de filo (phylum)
        - clase (string): categoría taxonómica de clase
        - orden (string): categoría taxonómica de orden
        - familia (string): categoría taxonómica de familia
        - genero (string): categoría taxonómica de género
        - especie (string): categoría taxonómica de especie
        - tolerancia_oxigeno (string): nivel de tolerancia al oxígeno
        - lpsn (string): código LPSN: https://lpsn.dsmz.de/
        - lpsn_parent (string): código LPSN padre
        - lpsn_renamed_to (string): código LPSN del taxón actual (por ejemplo, para Enterobacter aaerogenes,
        (775928) ahora es Klebsiella aerogenes (777146)
        - gbif: código GBIF: https://www.gbif.org/
        - gbif_parent (string): código GBIF padre
        - gbif_renamed_to (string): código GBIF del taxón actual (por ejemplo, para Enterobacter aaerogenes,
        (3221992) ahora es Klebsiella aerogenes (9281703)
        - snomed (JSONField): códigos SNOMED asociados: https://snomedsns.es/. Puede haber distintos en función
        de mecanismos de resistencia
        - resistencia_intrinseca: ManyToMany a Antibiotico. Es la resistencia intrínseca del microorganismo, que
        supone automáticamente una definición de categoría clínica 'R' de interpretación para ese Antibiotico
    Este modelo es heredable por el modelo MicroorganismoHospital propio de un Hospital"""
    MTYPE_CHOICES = [
        ("gp", "Gram positivo"),
        ("gn", "Gram negativo"),
        ("ana", "Anaerobio"),
        ("aty", "Atípico"),
    ]
    FTYPE_CHOICES = [
        ("c", "Cocos"),
        ("b", "Bacilos"),
    ]

    nombre = models.CharField(max_length=100)
    grupo_eucast = models.ForeignKey(GrupoEucast, on_delete=models.PROTECT)
    ftype = models.CharField(max_length=4, choices=FTYPE_CHOICES)
    mtype = models.CharField(max_length=4, choices=MTYPE_CHOICES)
    reino = models.CharField(max_length=100, blank=True)
    phylum = models.CharField(max_length=100, blank=True)
    clase = models.CharField(max_length=100, blank=True)
    orden = models.CharField(max_length=100, blank=True)
    familia = models.CharField(max_length=100, blank=True)
    genero = models.CharField(max_length=100, blank=True)
    especie = models.CharField(max_length=100, blank=True)
    tolerancia_oxigeno = models.CharField(max_length=100, blank=True)
    lpsn = models.CharField(max_length=100, blank=True)
    lpsn_parent = models.CharField(max_length=100, blank=True)
    lpsn_renamed_to = models.CharField(max_length=100, blank=True)
    gbif = models.CharField(max_length=100, blank=True)
    gbif_parent = models.CharField(max_length=100, blank=True)
    gbif_renamed_to = models.CharField(max_length=100, blank=True)
    snomed = models.JSONField(default=list, blank=True)
    resistencia_intrinseca = models.ManyToManyField(Antibiotico, blank=True)

    @property  # Decorador de propiedades. De esta forma se puede acceder a una propiedad personalizada
    # de una instancia de un objeto de esta clase con '.'
    def lista_resistencia_intrinseca(self) -> list[str]:
        """ Devuelve una lista con los nombres de los Antibiotico a los que es resistente el microorganismo"""
        return list(self.resistencia_intrinseca.values_list("nombre", flat=True))

    @property
    def lista_ids_resistencia_intrinseca(self) -> list[Antibiotico]:
        """Devuelve los IDs de Antibiotico a los que tiene resistencia intrínseca el microorganismo,
        incluyendo sus variantes"""
        from django.db.models import Q

        # lista de IDs base de resistencias intrínsecas ('values_lista(x, flat=True)' devuelve una lista)
        base_ids = list(self.resistencia_intrinseca.values_list('id', flat=True))

        if not base_ids:  # si no tiene resistencia intrínseca a ningún antibiótico, como E. coli
            return []  # devuelve una lista vacía

        # Obtenemos los IDs de padres y variantes hijos
        ids_completos = list(
            Antibiotico.objects.filter(
                Q(id__in=base_ids) | Q(parent__id__in=base_ids)
            ).values_list('id', flat=True)
        )

        return ids_completos

    def __str__(self):
        return self.nombre


# Modelo MecanismoResistencia
class MecanismoResistencia(models.Model):
    """Modelo que define un mecanismo de resistencia. El mecanismo de resistencia está
    ligado a un grupo EUCAST mediante el campo grupos_eucast en relación ManyToMany.
    Por ejemplo: un mecanismo de resistencia sería una BLEE"""
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    grupos_eucast = models.ManyToManyField(GrupoEucast)
    microorganismos = models.ManyToManyField(Microorganismo, blank=True)

    class Meta:
        verbose_name = "Mecanismo de resistencia"
        verbose_name_plural = "Mecanismos de resistencia"

    def __str__(self):
        return self.nombre


# Modelo SubtipoMecanismoResistencia
class SubtipoMecanismoResistencia(models.Model):
    """ Modelo que define un sutipo de mecanismo de resistencia. El subtipo está relacionado
    con un mecanismo de resistencia mediante ForeignKey en el campo mecanismo.
    Por ejemplo: un subtipo de un mecanismo de resistencia BLEE sería un gen CTX-M"""
    nombre = models.CharField(max_length=100)
    mecanismo = models.ForeignKey(MecanismoResistencia, on_delete=models.CASCADE, related_name="subtipos")

    class Meta:
        verbose_name = "Subtipo de mecanismo de resistencia"
        verbose_name_plural = "Subtipos de mecanismo de resistencia"

    def __str__(self):
        return self.nombre


# Modelo Ambito
class Ambito(models.Model):
    """ Modelo que define un Ámbito en el que se recogió una muestra concreta"""
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Ámbito"
        verbose_name_plural = "Ámbitos"

    def __str__(self):
        return self.nombre


# Modelo Servicio
class Servicio(models.Model):
    """ Modelo que define un Servicio en el que se recogió una muestra concreta"""
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre


# Modelo Sexo
class Sexo(models.Model):
    """ Modelo que define el Sexo del paciente de una muestra concreta"""
    codigo = models.CharField(max_length=10, unique=True)  # código o abreviatura
    descripcion = models.CharField(max_length=50)  # nombre completo

    def __str__(self):
        return self.descripcion


# Modelo TipoMuestra
class TipoMuestra(models.Model):
    """ Modelo que define el Tipo de Muestra de un registro concreto
    Los códigos snomed y loinc están disponibles en la SEIMC:
    https://seimc.org/wp-content/uploads/2025/06/seimc-catalogoMicrobiologia-LOINC-Pruebas-20250601.xlsx
    El código snomed es para el tipo de muestra propiamente dicho (sistema). Los códigos loinc son pruebas
    asociadas para ese tipo de muestra según el catálogo de la SEIMC.
    """
    nombre = models.CharField(max_length=50, unique=True)
    snomed = models.CharField(max_length=15, blank=True)
    codigos_loinc = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Tipo de muestra"
        verbose_name_plural = "Tipos de muestra"

    def __str__(self):
        return self.nombre


# Modelo EucastVersion
class EucastVersion(models.Model):
    """ Modelo que define metadatos de una versión de EUCAST
    Campos:
    - anyo (integer): año
    - version (string): versión de EUCAST
    - fecha_inicio (date): fecha de inicio de vigencia de la versión
    - fecha_fin (date): fecha final de vigencia de la versión
    - descripcion (string): descripción y comentarios
    """
    anyo = models.PositiveIntegerField(verbose_name="año")
    version = models.CharField(max_length=10)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    descripcion = models.TextField(blank=True)

    class Meta:
        ordering = ["-anyo"]  # los ordenamos en orden descendente por año
        verbose_name = "Versión EUCAST"
        verbose_name_plural = "Versiones EUCAST"

    def __str__(self):
        return f"EUCAST {self.anyo} (version: {self.version})"

    @classmethod
    def get_version_from_date(cls, fecha: date) -> "EucastVersion | None":
        """Devuelve la última versión EUCAST vigente para una fecha pasada como argumento"""
        # tan solo ejecuta la query para obtener el objeto por rango de fecha
        return (
            cls.objects
            .filter(fecha_inicio__lte=fecha)
            # EucastVersion cuya fecha de fin de vigencia sea superior al valor 'fecha' del argumento o Nulo
            .filter(models.Q(fecha_fin__gte=fecha) | models.Q(fecha_fin__isnull=True))
            .order_by("-fecha_inicio")  # importante para obtener la última versión
            .first()
        )


# Modelo CondicionTaxonReglaInterpretacion
class CondicionTaxonReglaInterpretacion(models.Model):
    """
    Condición taxonómica que puede usarse en una regla de interpretación ReglaInterpretacion.
    Campos:
        - scope: nivel sobre el que se evalúa (grupo EUCAST, familia, género, especie, personalizado).
        - valor: texto identificador del taxón (puede ser a niveles de grupo EUCAST o taxonónicos de familia,
        género o especie: "Morganellaceae", "Klebsiella", "Escherichia coli").
        - incluye / excluye: listas explícitas de Microorganismo para casos donde se quiera enumerar.
    Posee el método apply_to() para comprobar si una ReglaInterpretacion aplica a un Microorganismo
    """
    SCOPE_CHOICES = [
        ("grupo", "Grupo EUCAST"),
        ("familia", "Familia"),
        ("genero", "Género"),
        ("especie", "Especie"),
        ("personalizado", "Lista personalizada"),
    ]

    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, help_text="Nivel taxonómico al que afecta la regla")
    incluye = models.ManyToManyField("Microorganismo", blank=True, related_name="taxon_incluido_en")
    excluye = models.ManyToManyField("Microorganismo", blank=True, related_name="taxon_excluido_en")
    descripcion = models.CharField(max_length=200, unique=True, default="regla condicional")

    class Meta:
        verbose_name = "Condición taxonómica para reglas EUCAST"
        verbose_name_plural = "Condiciones taxonómicas para reglas EUCAST"

    def apply_to(self, microorganismo: Microorganismo) -> bool:
        """
        Devuelve True si esta condición aplica al microorganismo.
        Lógica:
        - Si el microorganismo está en excluye -> False.
        - Si hay incluye y no está -> False.
        - Si scope es 'personalizado', se evalúan sólo las listas.
        - Para otros scopes, se comparan atributos del microorganismo
          (familia, genero, especie, grupo EUCAST) con los de los incluidos/excluidos.
        """

        # 1 Excluir si está explícitamente en la lista 'excluye'
        if self.excluye.filter(pk=microorganismo.pk).exists():
            print(f"❌ Descartado porque el microorganismo está en la lista de excluidos")
            return False

        # 2. Si hay lista de incluye y no está incluido -> no aplica (False)
        if self.incluye.exists() and not self.incluye.filter(pk=microorganismo.pk).exists():
            print(f"❌ Descartado porque el microorganismo no está en la lista de incluidos")
            return False

        # 3. Si es personalizado -> ver si está en la lista incluye (existe?)
        if self.scope == "personalizado":
            incluido = self.incluye.filter(pk=microorganismo.pk).exists()
            print(f"✔️ Incluido en lista personalizada") if incluido else print(f"❌ No incluido en lista personalizada")
            return incluido

        # 4. Evaluación jerárquica de inclusión por scope
        for inc in self.incluye.all():
            # Vamos a ir de lo más restrictivo (especie) a lo más genérico (grupo EUCAST)
            # mediante bloques if/elif
            # Comparamos los nombres del microorganismo incluido frente al del microorganismo del argumento
            if self.scope == "especie":
                if inc.nombre.lower() == microorganismo.nombre.lower():
                    print(f"✔️ Incluido por especie")
                    return True  # si coinciden, aplica

            elif self.scope == "genero":
                if inc.genero and inc.genero.lower() == microorganismo.genero.lower():
                    print(f"✔️ Incluido por género")
                    return True

            elif self.scope == "familia":
                if inc.familia and inc.familia.lower() == microorganismo.familia.lower():
                    print(f"✔️ Incluido por familia")
                    return True

            elif self.scope == "grupo":
                # accedemos a los campos del grupo EUCAST
                if (
                        getattr(inc, "grupo_eucast", None)  # extraemos el grupo_eucast del microorganismo incluido
                        and getattr(microorganismo, "grupo_eucast",
                                    None)  # extraemos el grupo_eucast del microorganismo
                        # del argumento
                        and inc.grupo_eucast.nombre.lower() == microorganismo.grupo_eucast.nombre.lower()  # verificamos
                ):
                    print(f"✔️ Incluido por grupo EUCAST")
                    return True  # si coinciden los grupos, aplica

        # 5. Evaluación jerárquica de exclusión por scope
        for exc in self.excluye.all():
            # No tiene verificación de scope: algunas reglas en EUCAST incluyen a especies y excluyen a un nivel
            # superior, por lo que no puedo depender del valor del scope, tiene que inferirse al vuelo.
            # Procede de forma análoga al bloque de inclusiones
            if exc.nombre.lower() == microorganismo.nombre.lower():
                print(f"❌ Descartado porque el microorganismo está en lista de excluidos")
                return False
            elif exc.genero and exc.genero.lower() == microorganismo.genero.lower():
                print(f"❌ Descartado porque el género está en lista de excluidos")
                return False
            elif exc.familia and exc.familia.lower() == microorganismo.familia.lower():
                print(f"❌ Descartado porque la familia está en lista de excluidos")
                return False
            elif (
                    getattr(exc, "grupo_eucast", None)
                    and getattr(microorganismo, "grupo_eucast", None)
                    and exc.grupo_eucast.nombre.lower() == microorganismo.grupo_eucast.nombre.lower()
            ):
                print(f"❌ Descartado porque el grupo EUCAST está en lista de excluidos")
                return False
        print(f"✔️ No hubo descarte por ningún motivo")
        return True  # si al final no hay exclusión

    def __str__(self):
        return self.descripcion

    """
    # Ejemplo: aplica a E. coli, P. mirabilis y Klebsiella spp excepto K. aerogenes
    ecoli = Microorganismo.objects.get(nombre="Escherichia coli")
    pmirabilis = Microorganismo.objects.get(nombre="Proteus mirabilis")
    klebsiellas = Microorganismo.objects.filter(genero="Klebsiella")
    kaerogenes = Microorganismo.objects.get(nombre="Klebsiella aerogenes")
    
    cond = CondicionTaxonReglaInterpretacion.objects.create(scope="personalizado")
    cond.incluye.add(ecoli, pmirabilis, *klebsiellas)
    cond.excluye.add(kaerogenes)
    """


# Modelo ReglaInterpretacion
class ReglaInterpretacion(models.Model):
    """Modelo que define una regla de interpretación para un Antibiotico concreto en un GrupoEucast (o microorganismo) concreto
    Establece múltiples relaciones:
    - antibiotico: FK a Antibiotico
    - grupo_eucast: FK a GrupoEucast
    - condiciones_taxonomicas: ManyToMany a CondicionTaxonReglaInterpretacion (1 regla -> N condiciones taxonómicas)
    - categorias_muestra: ManyToMany a
    - categorias_muestra: ManyToMany a TipoMuestra
    - sexo: FK a Sexo
    - version_eucast: FK a EucastVersion
    Servirá para poder reinterpretar un Antibiotico en base a un resultado CMI para una versión concreta de EUCAST.
    - s_cmi_max (float): CMI máxima para categoría S
    - r_cmi_min (float): CMI mínima para categoría R (>) (poner el número que sale en las tablas EUCAST)
    - s_halo_min (integer): halo mínimo para categoría S
    - r_halo_max (integer): halo máximo para categoría R (<) (poner el número que sale en las tablas EUCAST)
    - version_eucast: FK a EucastVersion
    - comentario (string): campo libre para observaciones

    3 métodos importantes:
    - apply_to -> bool: Devuelve en boolean True o False en base a una serie de comprobaciones en cascada.
    - interpret -> CharField: Devuelve una categoria de interpretación clínica en base a los puntos de corte de CMI
    - get_applicable_rules -> BreakpointRule: Devuelve todas las reglas EUCAST aplicables a un aislado y antibiótico concreto
    """

    antibiotico = models.ForeignKey(Antibiotico, on_delete=models.CASCADE, related_name="breakpoint_rules")
    grupo_eucast = models.ForeignKey(GrupoEucast, null=True, blank=True, on_delete=models.CASCADE,
                                     related_name="breakpoint_rules")

    condiciones_taxonomicas = models.ManyToManyField(CondicionTaxonReglaInterpretacion, blank=True,
                                                     related_name="breakpoint_rules",
                                                     help_text="Condiciones taxonómicas asociadas")

    categorias_muestra = models.ManyToManyField(TipoMuestra, blank=True, related_name="breakpoint_rules",
                                                help_text="Muestras asociadas")

    edad_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Edad mínima (años)")
    edad_max = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Edad máxima (años)")
    sexo = models.ForeignKey(Sexo, null=True, blank=True, on_delete=models.PROTECT)

    s_cmi_max = models.FloatField(null=True, blank=True,
                                  verbose_name="CMI máxima para Sensible (≤)",
                                  help_text="Valores CMI ≤ este valor se interpretan como Sensible")

    r_cmi_min = models.FloatField(null=True, blank=True,
                                  verbose_name="CMI mínima para Resistente (>)",
                                  help_text="Valores CMI > este valor se interpretan como Resistente")

    s_halo_min = models.PositiveSmallIntegerField(null=True, blank=True,
                                                  verbose_name="Halo mínimo para Sensible (≥)",
                                                  help_text="Diámetro en mm >= S")
    r_halo_max = models.PositiveSmallIntegerField(null=True, blank=True,
                                                  verbose_name="Halo máximo para Resistente (<)",
                                                  help_text="Diámetro en mm < R")

    version_eucast = models.ForeignKey(EucastVersion, on_delete=models.PROTECT, related_name="breakpoint_rules")

    comentario = models.TextField(blank=True)

    class Meta:
        verbose_name = "Regla de interpretación EUCAST"
        verbose_name_plural = "Reglas de interpretación EUCAST"

    def apply_to(self, *,
                 antibiotico: Antibiotico,
                 microorganismo: MicroorganismoHospital,
                 grupo_eucast: GrupoEucast | None = None,
                 edad: float | None = None,
                 sexo: Sexo | None = None,
                 categoria_muestra: TipoMuestraHospital | None = None,
                 version_eucast: EucastVersion | None = None) -> bool:
        """
        Determina si una regla en particular aplica a los parámetros pasados.
        Imprime en consola paso a paso por qué una regla se aplica o se descarta.
        Nota: el asterisco (*) es un keyword-only separator: obliga a que los argumentos
        que vienen después se pasen como argumentos nombrados (keyword arguments), no posicionales
        """
        print("=======================================")
        print(f"Verificando regla: {self}")
        print(f"Parámetros: antibiótico={antibiotico}, micro={microorganismo}, "
              f"grupo_eucast={grupo_eucast}, edad={edad}, sexo={sexo}, "
              f"categoria_muestra={categoria_muestra}, version_eucast={version_eucast}")

        # Si la versión EUCAST pasada y la versión EUCAST de la regla es distinta -> se descarta
        if version_eucast and self.version_eucast != version_eucast:
            print(f"❌ Descarta por versión EUCAST: {self.version_eucast} != {version_eucast}")
            return False

        # Si el Antibiotico pasado y el de la regla es distinto -> se descarta
        if self.antibiotico != antibiotico:
            print(f"❌ Descarta por antibiótico: {self.antibiotico} != {antibiotico}")
            return False

        # Si el GrupoEucast pasado y el de la regla es distinto -> se descarta
        if self.grupo_eucast and grupo_eucast and self.grupo_eucast != grupo_eucast:
            print(f"❌ Descarta por grupo EUCAST: {self.grupo_eucast} != {grupo_eucast}")
            return False

        # Comprobaciones para condiciones taxonómicas
        # Enlistamos las condiciones de la regla
        condiciones = list(self.condiciones_taxonomicas.all())

        # si está asociado a condiciones
        if condiciones:
            aplica_por_taxon = False  # inicializamos la variable a False por defecto
            for cond in condiciones:
                # si el microorganismo está en la lista excluye de la condición -> descartamos la condición
                if cond.excluye.filter(pk=microorganismo.microorganismo.pk).exists(): # pasar el id del objeto Microorganismo
                    print(f"❌ Descarta por condición excluye: {cond}")
                    return False
                # si el microorganismo está en la lista incluye de la condición -> aceptamos la condición y salimos del
                # bucle for
                if cond.incluye.exists():
                    if cond.incluye.filter(pk=microorganismo.microorganismo.pk).exists(): # pasar el id del objeto Microorganismo
                        aplica_por_taxon = True
                        print(f"✔️ El microorganismo está en la lista de incluidos de la condición")
                        break
                    else:
                        continue
                # si no hay lista de incluidos o la hay pero el microorganismo no está incluido, aplicamos el método
                # apply_to() de CondicionTaxonReglaInterpretacion-> si devuelve True aceptamos la condición y salimos
                # del bucle
                if cond.apply_to(microorganismo.microorganismo): # pasar el id del objeto Microorganismo
                    aplica_por_taxon = True
                    break

            # Si finalmente no aplica, queda descartada la regla
            if not aplica_por_taxon:
                print("❌ Descarta por no cumplir condiciones taxonómicas")
                return False

        # Comprobaciones para edad
        # se comprueba que hay edad mínima en la regla y la edad pasada no es inferior a la mínima
        if self.edad_min is not None and (edad is None or edad < self.edad_min):
            print(f"❌ Descarta por edad < edad_min: {edad} < {self.edad_min}")
            return False
        # se comprueba que hay edad máxima en la regla y la edad pasada no es superior a la máxima
        if self.edad_max is not None and (edad is None or edad > self.edad_max):
            print(f"❌ Descarta por edad > edad_max: {edad} > {self.edad_max}")
            return False

        # Comprobaciones por sexo
        # se comprueba que los objetos sexo pasados sean los mismos
        if self.sexo and sexo and self.sexo != sexo:
            print(f"❌ Descarta por sexo: {self.sexo} != {sexo}")
            return False

        # Comprobaciones por categoria de muestra (objeto TipoMuestra)
        # Si la regla tiene asociados objetos TipoMuestra
        if self.categorias_muestra.exists():

            # Obtenemos una lista con los IDs de TipoMuestra asociados a la regla
            ids_tipo_muestra_regla = list(self.categorias_muestra.values_list("id", flat=True))
            print(f"IDs regla: {ids_tipo_muestra_regla}")

            # Si no hay tipo de muestra en los argumentos
            if not categoria_muestra:
                print("❌ Descarta por categoría de muestra sin especificar ")
                return False

            # Convertimos el parámetro recibido a ID de TipoMuestra (a partir del FK a TipoMuestra de TipoMuestraHospital)
            id_tipo_muestra_param = categoria_muestra.tipo_muestra.id
            print(f"ID tipo de muestra pasada: {id_tipo_muestra_param}")

            # Verificamos si está en la lista de IDs de TipoMuestra asociados a la regla
            if id_tipo_muestra_param not in ids_tipo_muestra_regla:
                print("❌ Descarta por categoría de muestra no incluida en la regla")
                return False

        # Si no se llegó a descartar finalmente, devolver True -> aplica
        print(f"✅ Regla aplicada correctamente: {self}")
        return True

    def interpret(self, *, cmi: float | None = None, halo: float | None = None) -> str:
        """
        Interpreta un valor (CMI o halo) según los puntos de corte definidos.
        - Prioriza la CMI, cuando se pasa.
        - Si ninguno está presente devuelve "ND" (no disponible).

        Notas: el asterisco (*) es un keyword-only separator: obliga a que 'cmi' y 'halo'
        se pasen como argumentos nombrados (keyword arguments), no posicionales. Son parámetros opcionales:
        '| None = None' permite que puedan omitirse o ser None.
        """
        if cmi is None and halo is None:
            return "ND"

        if cmi is not None:
            # S
            if self.s_cmi_max is not None and cmi <= self.s_cmi_max:
                return "S"
            # R. Multiplico por 2 porque son diluciones seriadas en base 2. r_cmi_min es >, no ≥
            if self.r_cmi_min is not None and cmi > 2 * self.r_cmi_min:
                return "R"
            # I (entre S y R, si ambos están definidos)
            if self.s_cmi_max is not None and self.r_cmi_min is not None and self.s_cmi_max < cmi < 2 * self.r_cmi_min:
                return "I"
            return "ND"

        # Interpretación por halo si no hay CMI. De forma análoga a cmi, pero no hay que multiplicar en base 2 esta vez
        if halo is not None:
            if self.s_halo_min is not None and halo >= self.s_halo_min:
                return "S"
            if self.r_halo_max is not None and halo < self.r_halo_max:
                return "R"
            if self.s_halo_min is not None and self.r_halo_max is not None and self.r_halo_max <= halo < self.s_halo_min:
                return "I"
            return "ND"

        return "ND"  # fallback

    @classmethod
    def get_applicable_rules(cls, microorganismo: Microorganismo) -> list["ReglaInterpretacion"]:
        """
        Devuelve todas las reglas aplicables a un microorganismo dado.
        Tiene en cuenta las condiciones taxonómicas y los factores clínicos
        (edad, sexo, tipo de muestra, etc) si están definidos.
        """

        # Primero extraemos las reglas
        reglas = cls.objects.all()

        # Si hay condiciones taxonómicas, las filtramos aquí:
        aplicables = []  # inicializamos una lista
        for regla in reglas:  # iteramos por las reglas
            condiciones = regla.condiciones_taxonomicas.all()  # extraemos las condiciones taxonómicas de la regla

            # Si no existen condiciones-> la regla aplica (no hay restricciones)
            if not condiciones.exists():
                aplicables.append(regla)  # añadimos la regla y pasamos a la siguiente
                continue

            # Si existen condiciones las verificamos. Si alguna condición aplica -> la regla aplica, la añadimos
            # y salimos del bucle de condiciones a por la siguiente regla
            for cond in condiciones:
                if cond.apply_to(microorganismo):
                    aplicables.append(regla)
                    break

        return aplicables  # devolvemos la lista de ReglaInterpretacion que aplican

    def __str__(self):
        return f"{self.antibiotico} — EUCAST {self.version_eucast} ({self.condiciones_taxonomicas.count()} condiciones)"
