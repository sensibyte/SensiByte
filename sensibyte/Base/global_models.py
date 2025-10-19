# global_models.py: definiciones de los modelos de Django. Los modelos representan las tablas de la base de datos
# Sólo se incluyen los modelos a nivel GENERAL, NO los específicos de cada HOSPITAL
#
# Ver models.py para más información

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
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre


# Modelo FamiliaAntibiotico
class FamiliaAntibiotico(models.Model):
    """ Modelo que define la familia del antibiótico.
    Se relaciona con la clase de antibiótico a través de un FK
    en su campo "clase".
    Por ejemplo: la ampicilina pertenece a la familia de las penicilinas,
    de la clase de los betalactámicos. """
    nombre = models.CharField(max_length=50, unique=True)
    clase = models.ForeignKey(ClaseAntibiotico, on_delete=models.PROTECT)

    def __str__(self):
        return self.nombre


# Modelo Espectro
class Espectro(models.Model):
    """ Modelo que define el espectro de acción de un antibiótico
    (simplificado): gram positivos (gp), gram negativos (gn), anaerobios (ana)
    y bacterias atípicas (aty) """
    gp = models.BooleanField(default=False)
    gn = models.BooleanField(default=False)
    ana = models.BooleanField(default=False)
    aty = models.BooleanField(default=False)

    def __str__(self):
        spctr = []
        if self.gp: spctr.append("Gram Positivos")
        if self.gn: spctr.append("Gram Negativos")
        if self.ana: spctr.append("Anaerobios")
        if self.aty: spctr.append("Atípicos")
        return ", ".join(spctr) if spctr else "Sin espectro definido"


# Modelo Antibiotico
class Antibiotico(models.Model):
    """ Modelo que define un Antibiotico.
    Campos:
        nombre (string): nombre del antibiótico
        abr (string): abreviatura del antibiótico
        familia_antibiotico: FK de FamiliaAntibiotico
        espectro: FK de Espectro
    Este modelo es heredable por el modelo AntibioticoHospital propio de un Hospital
    """
    nombre = models.CharField(max_length=50, unique=True)
    abr = models.CharField(max_length=5, unique=True)
    familia_antibiotico = models.ForeignKey(FamiliaAntibiotico, on_delete=models.PROTECT)
    espectro = models.ForeignKey(Espectro, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.nombre} ({self.familia_antibiotico} / {self.familia_antibiotico.clase})"


# Modelo GrupoEucast
class GrupoEucast(models.Model):
    """ Modelo que define el grupo de EUCAST al que pertenece un microorganismo
    Por ejemplo: E. coli pertenece a Enterobacterales """
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre


# Modelo Microorganismo
class Microorganismo(models.Model):
    """ Modelo que define un microorganismo. Se relaciona con varios Antibioticos en
    su campo "resistencia_intrinseca" mediante un ManyToMany, y establece una relación
    varios a uno con "grupo_eucast". """
    MTYPE_CHOICES = [
        ("gp", "Gram positivo"),
        ("gn", "Gram negativo"),
        ("ana", "Anaerobio"),
        ("aty", "Atípico"),
    ]

    nombre = models.CharField(max_length=100)
    grupo_eucast = models.ForeignKey(GrupoEucast, on_delete=models.PROTECT)
    familia = models.CharField(max_length=100)
    mtype = models.CharField(max_length=4, choices=MTYPE_CHOICES)
    resistencia_intrinseca = models.ManyToManyField(Antibiotico, blank=True)

    @property  # Decorador de propiedades. De esta forma se puede acceder a una propiedad personalizada
    # de una instancia de un objeto de esta clase con '.'
    def lista_resistencia_intrinseca(self):
        return list(self.resistencia_intrinseca.values_list("nombre", flat=True))

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

    def __str__(self):
        return self.nombre


# Modelo SubtipoMecanismoResistencia
class SubtipoMecanismoResistencia(models.Model):
    """ Modelo que define un sutipo de mecanismo de resistencia. El subtipo está relacionado
    con un mecanismo de resistencia mediante ForeignKey en el campo mecanismo.
    Por ejemplo: un subtipo de un mecanismo de resistencia BLEE sería un gen CTX-M"""
    nombre = models.CharField(max_length=100)
    mecanismo = models.ForeignKey(MecanismoResistencia, on_delete=models.CASCADE, related_name="subtipos")

    def __str__(self):
        return self.nombre


# Modelo Ambito
class Ambito(models.Model):
    """ Modelo que define un Ámbito en el que se recogió una muestra concreta"""
    nombre = models.CharField(max_length=100, unique=True)

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
    codigo = models.CharField(max_length=10, unique=True)
    descripcion = models.CharField(max_length=50)

    def __str__(self):
        return self.descripcion


# Modelo TipoMuestra
class TipoMuestra(models.Model):
    """ Modelo que define el Tipo de Muestra de un registro concreto"""
    nombre = models.CharField(max_length=50, unique=True)
    clasificacion = models.CharField(max_length=15)
    codigo_loinc = models.CharField(max_length=15)

    def __str__(self):
        return self.nombre


# Modelo EucastVersion
class EucastVersion(models.Model):
    """ Modelo que define metadatos de una versión de EUCAST"""
    year = models.PositiveIntegerField()
    version = models.CharField(max_length=10)
    fecha_publicacion = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year"]
        verbose_name = "Versión EUCAST"
        verbose_name_plural = "Versiones EUCAST"

    def __str__(self):
        return f"EUCAST {self.year} (version: {self.version})"

    @classmethod
    def get_version_from_date(cls, fecha: date):
        """Devuelve la versión EUCAST vigente en una fecha"""
        return (
            cls.objects
            .filter(fecha_publicacion__lte=fecha)
            .filter(models.Q(fecha_fin__gte=fecha) | models.Q(fecha_fin__isnull=True))
            .order_by("-fecha_publicacion")
            .first()
        )


# Modelo BreakpointRule
class BreakpointRule(models.Model):
    """Modelo que define una regla de interpretación para un antibiótico concreto en un grupo EUCAST (o microorganismo) concreto
    Establece múltiples relaciones:
    - antibiotico: FK a Antibiotico
    - grupo_eucast: FK a GrupoEucast
    - microorganismo: FK a Microorganismo
    - categorias_muestra: ManyToMany a TipoMuestra
    - sexo: FK a Sexo
    - version_eucast: FK a EucastVersion
    Servirá para poder reinterpretar un Antibiotico en base a un resultado CMI para una versión concreta de EUCAST.

    3 métodos importantes:
    - apply_to -> bool: Devuelve en boolean True o False en base a una serie de comprobaciones en cascada.
    - interpret -> CharField: Devuelve una categoria de interpretación clínica en base a los puntos de corte de CMI
    - get_applicable_rules -> BreakpointRule: Devuelve todas las reglas EUCAST aplicables a un aislado y antibiótico concreto
    """

    antibiotico = models.ForeignKey(Antibiotico, on_delete=models.CASCADE, related_name="breakpoint_rules")
    grupo_eucast = models.ForeignKey(GrupoEucast, null=True, blank=True, on_delete=models.CASCADE,
                                     related_name="breakpoint_rules")
    microorganismo = models.ForeignKey(Microorganismo, null=True, blank=True, on_delete=models.CASCADE,
                                       related_name="breakpoint_rules")

    categorias_muestra = models.ManyToManyField(TipoMuestra, blank=True, related_name="breakpoint_rules")

    edad_min = models.PositiveSmallIntegerField(null=True, blank=True)
    edad_max = models.PositiveSmallIntegerField(null=True, blank=True)
    sexo = models.ForeignKey(Sexo, null=True, blank=True, on_delete=models.PROTECT)

    s_cmi_max = models.FloatField(null=True, blank=True,
                                  verbose_name="CMI máxima para Sensible (≤)",
                                  help_text="Valores CMI ≤ este valor se interpretan como Sensible")

    r_cmi_min = models.FloatField(null=True, blank=True,
                                  verbose_name="CMI mínima para Resistente (>)",
                                  help_text="Valores CMI > este valor se interpretan como Resistente")

    version_eucast = models.ForeignKey(EucastVersion, on_delete=models.PROTECT, related_name="breakpoint_rules")

    comentario = models.TextField(blank=True)

    class Meta:
        unique_together = ["antibiotico", "version_eucast"] # conjunto único antibiótico por versión de EUCAST
        verbose_name = "Regla de interpretación EUCAST"
        verbose_name_plural = "Reglas de interpretación EUCAST"


    def apply_to(self, *, antibiotico, microorganismo, grupo_eucast=None, edad=None, sexo=None,
                 categoria_muestra=None, version_eucast=None) -> bool:
        """ Determina si una regla aplica a un caso. Devuelve un boolean. """

        # Versión Eucast
        if version_eucast and self.version_eucast != version_eucast:
            return False

        # Antibiótico
        if self.antibiotico != antibiotico:
            return False

        # Microorganismo o grupo EUCAST
        if self.microorganismo and self.microorganismo != microorganismo:
            return False
        if self.grupo_eucast and grupo_eucast and self.grupo_eucast != grupo_eucast:
            return False

        # Categoría de muestra
        if self.categorias_muestra.exists():
            if not categoria_muestra or categoria_muestra not in self.categorias_muestra.all():
                return False

        # Edad
        if self.edad_min is not None and (edad is None or edad < self.edad_min):
            return False
        if self.edad_max is not None and (edad is None or edad > self.edad_max):
            return False

        # Sexo
        if self.sexo and sexo and self.sexo != sexo:
            return False

        return True

    def interpret(self, cmi: float | None) -> str:
        """Interpreta en base al valor de CMI """
        if cmi is None:
            return "ND"
        if self.s_cmi_max is not None and cmi <= self.s_cmi_max:
            return "S"
        elif self.r_cmi_min is not None and cmi > self.r_cmi_min:
            return "R"
        elif self.s_cmi_max is not None and self.r_cmi_min is not None and self.s_cmi_max < cmi < self.r_cmi_min:
            return "I"
        return "ND"

    @classmethod
    def get_applicable_rules(cls, antibiotico, microorganismo, grupo_eucast, edad, sexo,
                             categoria_muestra, version_eucast):
        """ Devuelve todas las reglas EUCAST aplicables a un aislado y antibiótico concreto """
        antibiotico = antibiotico
        microorganismo = microorganismo
        grupo_eucast = grupo_eucast
        edad = edad
        sexo = sexo
        categoria_muestra = categoria_muestra
        version = version_eucast

        posibles = cls.objects.filter(antibiotico=antibiotico)

        if version:
            posibles = posibles.filter(version_eucast=version)

        aplicables = [
            regla for regla in posibles
            if regla.apply_to(
                antibiotico=antibiotico,
                microorganismo=microorganismo,
                grupo_eucast=grupo_eucast,
                edad=edad,
                sexo=sexo,
                categoria_muestra=categoria_muestra,
                version_eucast=version,
            )
        ]
        return aplicables

    def __str__(self):
        parts = [self.antibiotico.nombre]
        if self.microorganismo:
            parts.append(f"({self.microorganismo.nombre})")
        elif self.grupo_eucast:
            parts.append(f"[{self.grupo_eucast.nombre}]")
        return f"{" ".join(parts)} - EUCAST {self.version_eucast.year}"
