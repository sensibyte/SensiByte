# models.py: definiciones de los modelos de Django. Los modelos representan las tablas de la base de datos.
# Sólo se incluyen los modelos a nivel de HOSPITAL.
#
# Los modelos heredan de la clase models.Model, que pueden tener distintos tipos de campos (columnas de la tabla).
# Campos habituales son:
#
# CharField - Texto corto
# TextField - Texto largo
# JSONField - Datos en formato JSON (listas de alias)
# PositiveSmallIntegerField - Números enteros positivos pequeños
# FloatField - Números decimales
# DateTimeField - Fecha y hora
# BooleanField - Booleano
#
# Existen otros campos que establecen relaciones entre modelos:
#
# ForeignKey - Relación varios a 1 (por ejemplo: varios Libros de 1 Autor)
# ManyToManyField - Relación varios a varios (por ejemplo: varios Estudiantes que asisten a varias Clases)
# OneToOneField - Relación 1 a 1 (por ejemplo: un Paciente una HistoriaClinica)
#
# Además, podemos hacer uso de los metadatos usando la clase Meta para la configuración del modelo
#
# verbose_name - Nombre legible del modelo (en singular)
# verbose_name_plural - Nombre legible del modelo en plural
# ordering - Orden por defecto de los registros (puede ser descendente con "-")
# unique_together - Establece una restricción que asegura que la combinación de campos sea única (un objeto por Hospital)
#
# También podemos sobreescribir métodos mágicos como:
#
# __str__() - Define cómo se muestra el objeto cuando lo imprimes
#
# Y construir métodos de clase que no necesiten instancia para ser llamados mediante el decorador @classmethod
# (pasan entonces cls como primer argumento, no self)
#
# https://docs.djangoproject.com/en/5.2/ref/models/


from .global_models import *
from .mixins import AliasMixin
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import QuerySet


# Puesto que pueden tener distintos alias, la mayor parte
# de los modelos específicos de Hospital heredan de AliasMixin

# Modelo AntibioticoHospital
class AntibioticoHospital(AliasMixin, models.Model):
    """ Modelo que define un Antibiotico asociado a un Hospital.
    Se relaciona con el Antibiotico a través de un FK
    en su campo "antibiotico" y con el Hospital con otro FK en
    su campo "hospital". Posee un campo 'integer' para el ordenamiento
    de objetos en los informes. Hereda de AliasMixin para construir su
    "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="antibioticos_hospital")
    antibiotico = models.ForeignKey(Antibiotico, on_delete=models.CASCADE, related_name="antibioticos")
    orden_informe = models.IntegerField(default=0, help_text="Orden en el que aparecerá en los informes")

    class Meta:
        unique_together = ["hospital", "antibiotico"]  # combinación única por hospital
        verbose_name = "Antibiótico"
        verbose_name_plural = "1. Antibióticos"  # Esta es una argucia para ordenar el panel de Administrador
        # a través de las cadenas en plural. Ojo: estar atento cuando crezca
        # la aplicación porque si hay otro sitio en el que tenga que mostrar
        # el plural asociado a este modelo pondrá "1. Antibióticos", si bien
        # normalmente no voy a usar más que uno de ellos y los formularios
        # pueden sobreescribir el label del input

    def __str__(self):
        return f"{self.antibiotico.nombre}"  # Nombre del Antibiotico

    @classmethod
    def base_only(cls)->QuerySet['AntibioticoHospital']:
        """Devuelve los objetos AntibioticoHospital cuyo padre no es una variante"""
        return cls.objects.filter(antibiotico__es_variante=False)


# Modelo MicroorganismoHospital
class MicroorganismoHospital(AliasMixin, models.Model):
    """ Modelo que define un Microorganismo asociado a un Hospital.
    Se relaciona con el Microorganismo a través de un FK
    en su campo "microorganismo" y con el Hospital con otro FK en
    su campo "hospital". Hereda de AliasMixin para construir su
    "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="microorganismos_hospital")
    microorganismo = models.ForeignKey(Microorganismo, on_delete=models.CASCADE, related_name="microorganismos")

    class Meta:
        unique_together = ["hospital", "microorganismo"]  # combinación única por hospital
        verbose_name = "Microorganismo"
        verbose_name_plural = "2. Microorganismos"

    def __str__(self):
        return self.microorganismo.nombre  # Nombre del Microorganismo


# Modelo PerfilAntibiogramaHospital
class PerfilAntibiogramaHospital(models.Model):
    """ Modelo que define un Perfil de antibiograma asociado a un Hospital.
    Esto es un conjunto de Antibioticos que se asocian a un Grupo de Eucast.
    Se relaciona con el GrupoEucast a través de un FK en su campo "grupo_eucast",
    con los Antibioticos a través de un ManyToMany con AntibioticoHospital y
    con el Hospital con otro FK en su campo "hospital".
    Hereda de AliasMixin para construir su "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="perfiles_antibiograma")
    grupo_eucast = models.ForeignKey(GrupoEucast, on_delete=models.CASCADE, related_name="perfiles")
    antibioticos = models.ManyToManyField(AntibioticoHospital)

    class Meta:
        unique_together = ["hospital", "grupo_eucast"]  # combinación única por hospital
        verbose_name = "Perfil de antibiograma"
        verbose_name_plural = "2. Perfiles de antibiograma"

    def __str__(self):  # Mediante esta construcción podemos ver el Hospital y Grupo Eucast al que pertenece el perfil
        return f"Perfil EUCAST de {self.hospital.codigo} para {self.grupo_eucast.nombre}"


# Modelo MecanismoResistenciaHospital
class MecanismoResistenciaHospital(AliasMixin, models.Model):
    """ Modelo que define un MecanismoResistencia asociado a un Hospital.
    Se relaciona con el MecanismoResistencia a través de un FK
    en su campo "mecanismo" y con el Hospital con otro FK en
    su campo "hospital". Además, incluye un campo de resistencias adquiridas
    que se relacionan con Antibioticos a través de un ManyToMany para marcar
    resistencias que se producen por este mecanismo de resistencia (esto puede
    ser muy dependiente de hospital para ciertos tipos de mecanismos, por lo que
    dejo aquí y no en el propio modelo MecanismoResistencia).
    Hereda de AliasMixin para construir su "alias"."""
    hospital = models.ForeignKey("Base.Hospital", on_delete=models.CASCADE, related_name="mecanismos_hospital")
    mecanismo = models.ForeignKey(MecanismoResistencia, on_delete=models.CASCADE, related_name="mecanismos")
    resistencia_adquirida = models.ManyToManyField(Antibiotico, blank=True, related_name="mecanismos_hospital")

    class Meta:
        unique_together = ["hospital", "mecanismo"]  # combinación única por hospital
        verbose_name = "Perfil de antibiograma"
        verbose_name_plural = "2. Mecanismos de resistencia"

    def __str__(self):
        return f"{self.mecanismo.nombre}"  # Nombre del mecanismo de resistencia


# Modelo SubtipoMecanismoResistenciaHospital
class SubtipoMecanismoResistenciaHospital(AliasMixin, models.Model):
    """ Modelo que define un SubtipoMecanismoResistencia asociado a un Hospital.
    Se relaciona con el SubtipoMecanismoResistencia a través de un FK
    en su campo "subtipo_mecanismo" y con el Hospital con otro FK en
    su campo "hospital". Hereda de AliasMixin para construir su
    "alias"."""
    hospital = models.ForeignKey("Base.Hospital", on_delete=models.CASCADE, related_name="subtipos_mecanismos_hospital")
    subtipo_mecanismo = models.ForeignKey(SubtipoMecanismoResistencia, on_delete=models.CASCADE,
                                          related_name="subtipos_mecanismos")
    resistencia_adquirida = models.ManyToManyField(Antibiotico, blank=True, related_name="subtipos_mecanismos_hospital")

    class Meta:
        unique_together = ["hospital", "subtipo_mecanismo"]  # combinación única por hospital
        verbose_name = "Subtipo Mecanismo de Resistencia"
        verbose_name_plural = "2. Subtipos Mecanismo de Resistencia"

    def __str__(self):
        return f"{self.subtipo_mecanismo.nombre}"  # Nombre del subtipo de mecanismo de resistencia


# Modelo AmbitoHospital
class AmbitoHospital(AliasMixin, models.Model):
    """ Modelo que define un Ámbito asociado a un Hospital.
    Se relaciona con el Ambito a través de un FK
    en su campo "ambito" y con el Hospital con otro FK en
    su campo "hospital". Dispone de un bit para marcar si
    se mostrarán sus resultados en informes a la hora de filtrar
    objetos relacionados en la queryset.
    Hereda de AliasMixin para construir su "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="ambitos_hospital")
    ambito = models.ForeignKey(Ambito, on_delete=models.CASCADE, related_name="ambitos")
    ignorar_informes = models.BooleanField(default=False)

    class Meta:
        unique_together = ["hospital", "ambito"]  # combinación única por hospital
        verbose_name = "Ámbito"
        verbose_name_plural = "2. Ámbitos"

    def __str__(self):
        return self.ambito.nombre  # Nombre del ámbito


# Modelo ServicioHospital
class ServicioHospital(AliasMixin, models.Model):
    """ Modelo que define un Servicio asociado a un Hospital.
    Se relaciona con el Servicio a través de un FK
    en su campo "servicio" y con el Hospital con otro FK en
    su campo "hospital". Dispone de un bit para marcar si
    se mostrarán sus resultados en informes a la hora de filtrar
    objetos relacionados en la queryset.
    Hereda de AliasMixin para construir su "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="servicios_hospital")
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE, related_name="servicios")
    ignorar_informes = models.BooleanField(default=False)

    class Meta:
        unique_together = ["hospital", "servicio"]  # combinación única por hospital

    def __str__(self):
        return self.servicio.nombre  # nombre del servicio


# Modelo SexoHospital
class SexoHospital(AliasMixin, models.Model):
    """ Modelo que define un Ámbito asociado a un Hospital.
        Se relaciona con el Ambito a través de un FK
        en su campo "ambito" y con el Hospital con otro FK en
        su campo "hospital". Dispone de un bit para marcar si
        se mostrarán sus resultados en informes a la hora de filtrar
        objetos relacionados en la queryset.
        Hereda de AliasMixin para construir su "alias"."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="sexos_hospital")
    sexo = models.ForeignKey(Sexo, on_delete=models.CASCADE, related_name="sexos")
    ignorar_informes = models.BooleanField(default=False)

    class Meta:
        unique_together = ["hospital", "sexo"]  # combinación única por hospital

    def __str__(self):
        return self.sexo.descripcion  # descripción del tipo de sexo asociado


# Modelo CategoriaMuestraHospital
class CategoriaMuestraHospital(models.Model):
    """ Modelo que define una categoría de muestra asociado a un Hospital.
    De esta forma se permitirá la agrupación de distintos tipos de muestra
    en una sola categoría para la generación de informes.
    Se relaciona con el Hospital con un FK en
    su campo "hospital". Dispone de dos bits:
    - ignorar_minimo: Si igualmente queremos que muestre resultado de sensibilidad
        a pesar de que su recuento sea < 30
    - ignorar_informes: Si queremos que se filtre la queryset excluyendo los objetos
        de esta categoría de muestra (por ejemplo, las muestras de controles epidemiológicos. """
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="categorias_muestra_hospital")
    nombre = models.CharField(max_length=50)
    ignorar_minimo = models.BooleanField(default=False)
    ignorar_informes = models.BooleanField(default=False)

    class Meta:
        unique_together = ["hospital", "nombre"]  # combinación única por hospital

    def __str__(self):
        return self.nombre


# Modelo TipoMuestraHospital
class TipoMuestraHospital(AliasMixin, models.Model):
    """ Modelo que define un Tipo de Muestra asociado a un Hospital.
    Se relaciona con el TipoMuestra a través de un FK
    en su campo "tipo_muestra", con el Hospital con otro FK en
    su campo "hospital" y con CategoriaMuestraHospital a través de otro FK en
    su campo "categoria". Hereda de AliasMixin para construir su 'alias'."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="tipos_muestra_hospital")
    categoria = models.ForeignKey(CategoriaMuestraHospital, on_delete=models.CASCADE,
                                  related_name="tipos_muestra_hospital")
    tipo_muestra = models.ForeignKey(TipoMuestra, on_delete=models.CASCADE, related_name="tipos_muestra")

    class Meta:
        unique_together = ["hospital", "tipo_muestra"]  # combinación única por hospital

    def __str__(self):
        return self.tipo_muestra.nombre  # nombre del tipo de muestra


# Modelo MecResValoresPositivosHospital
class MecResValoresPositivosHospital(AliasMixin, models.Model):
    """ Modelo que define de qué forma se marcan los mecanismos de resistencia en el
    antibiograma (si esas columnas existieran). Hereda de AliasMixin para construir estos "alias".
    Por ejemplo, es habitual encontrar la columna Esbl pero puede ser "Positivo", "+", etc.
    dependiendo del Hospital. """
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="mecres_pos_hospital")


# Modelo Registro
class Registro(models.Model):
    """ Modelo que define un Registro importado de la BBDD del Hospital.
    Se relaciona con factores epidemiológicos mediante FKs. Además, incluye
    el código encriptado del identificador del paciente en el campo 'nh_hash'"""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="registros")
    fecha = models.DateField()
    nh_hash = models.CharField(max_length=64)  # Identificador del paciente
    edad = models.PositiveSmallIntegerField(null=True, blank=True)

    sexo = models.ForeignKey(SexoHospital, on_delete=models.PROTECT)  # PROTECT: impedirá borrar el FK padre asociado
    # mientras haya registros asociados a él.
    ambito = models.ForeignKey(AmbitoHospital, on_delete=models.PROTECT)
    servicio = models.ForeignKey(ServicioHospital, on_delete=models.PROTECT)
    tipo_muestra = models.ForeignKey(TipoMuestraHospital, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.fecha} | {self.nh_hash}"


# Modelo Aislado
class Aislado(models.Model):
    """ Modelo que define un Aislado importado de la BBDD del Hospital.
    Se relaciona con el Registro a partir de un FK. Otras relaciones FKs
    apuntan al MicroorganismoHospital y EucastVersion, mientras que se
    relaciona con los mecanismos y subtipos de mecanismos de resistencia
    mediante relaciones ManyToMany."""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="aislados")
    registro = models.ForeignKey(Registro, on_delete=models.CASCADE, related_name="aislados")

    microorganismo = models.ForeignKey(MicroorganismoHospital, on_delete=models.PROTECT)
    version_eucast = models.ForeignKey(EucastVersion,
                                       on_delete=models.SET_NULL, null=True, blank=True) # SET_NULL: pasa nulo si se
                                                                                         # borra el FK padre asociado

    mecanismos_resistencia = models.ManyToManyField(MecanismoResistenciaHospital, blank=True)
    subtipos_resistencia = models.ManyToManyField(SubtipoMecanismoResistenciaHospital, blank=True)

    def __str__(self):
        mecanismos = ", ".join([m.mecanismo.nombre for m in self.mecanismos_resistencia.all()])
        return f"{self.microorganismo}" + (f" ({mecanismos})" if mecanismos else "")

    @property
    def resultados_no_variantes(self)-> QuerySet["ResultadoAntibiotico"]:
        """Devuelve un queryset de ResultadoAntibioticos del Aislado
        que vienen de Antibioticos base, no variantes"""
        return self.resultados.filter(
            antibiotico__antibiotico__es_variante=False
        ).select_related("antibiotico", "antibiotico__antibiotico").order_by("id")

    @property
    def resultados_variantes(self) -> QuerySet["ResultadoAntibiotico"]:
        """Devuelve un queryset de ResultadoAntibioticos del Aislado
        que vienen de Antibioticos variantes, no base"""
        return self.resultados.filter(
            antibiotico__antibiotico__es_variante=True
        ).select_related("antibiotico", "antibiotico__antibiotico").order_by("id")


# Modelo ResultadoAntibiotico
class ResultadoAntibiotico(models.Model):
    """ Modelo que define un Resultado para un Antibiotico importado de la BBDD del Hospital.
    Se relaciona con el Aislado y Antibiotico mediante sendos FKs. Incluye la interpretación
    de la categoría clínica mediante un string de máximo de 2 caracteres; la CMI, anulable,
    por número decimal; y el halo de forma análoga a la CMI """
    aislado = models.ForeignKey(Aislado, on_delete=models.CASCADE, related_name="resultados")
    antibiotico = models.ForeignKey(AntibioticoHospital, on_delete=models.PROTECT)

    INTERPRETACION_CHOICES = [
        ("S", "Sensible"),
        ("I", "Intermedio"),
        ("R", "Resistente"),
        ("ND", "No Determinado"),
        ("NA", "No Aplica")
    ]

    interpretacion = models.CharField(max_length=2, choices=INTERPRETACION_CHOICES)
    cmi = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True) # número decimal, anulable
    halo = models.PositiveSmallIntegerField(validators=[MinValueValidator(0),
                                                        MaxValueValidator(50)]
                                            , null=True, blank=True, verbose_name="Diámetro (mm)")

    class Meta:
        unique_together = ["aislado", "antibiotico"] # combinación única por hospital
        indexes = [ # Crea un índice en la base de datos para intentar acelerar las consultas
            models.Index(fields=["antibiotico"]),
            models.Index(fields=["aislado"]),
        ]

    def __str__(self):
        return f"{self.antibiotico} -> {self.interpretacion} ({self.cmi or self.halo or "CMI ND"})"

# Modelo AliasInterpretacion
class AliasInterpretacionHospital(AliasMixin, models.Model):
    """ Modelo que define la categoría de interpretación que utiliza un Hospital. Hereda de AliasMixin
     para construir estos "alias", y los asocia a una categoría preestablecida de interpretación.
     De esta forma cada hospital puede crear sus claves de interpretación personalizadas"""
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="alias_interpretacion_hospital")
    interpretacion = models.CharField(max_length=2, choices=ResultadoAntibiotico.INTERPRETACION_CHOICES)

    class Meta:
        verbose_name = "Valor de interpretación"
        verbose_name_plural = "Valores de interpretaciones"

    def get_standard_interp(self, valor):
        """ Devuelve la interpretación estándar ("S", "I", "R", "ND") según el valor recibido."""
        valor = valor.strip().upper() # formateamos el valor
        if self.match_alias(valor): # buscamos si está entre los alias
            return self.interpretacion # si está, devolvemos la interpretación asociada
        return None

# Modelo ReinterpretacionAntibiotico
class ReinterpretacionAntibiotico(models.Model):
    """ Modelo que define la reinterpretación de un Resultado para un Antibiotico en base a una
    versión de EUCAST. Se relaciona con el resultado padre de ResultadoAntibiotico mediante un FK
    que lo apunta en el campo "resultado_original", y con la versión EUCAST que le aplica en el
    campo "version_eucast". Añade de forma automática un timestamp de cuándo se realizó la
    reinterpretación en el campo "fecha_reinterpretacion"."""
    resultado_original = models.ForeignKey(ResultadoAntibiotico, on_delete=models.CASCADE,
                                           related_name="reinterpretaciones")
    version_eucast = models.ForeignKey(EucastVersion, on_delete=models.PROTECT)
    interpretacion_nueva = models.CharField(max_length=2, choices=ResultadoAntibiotico.INTERPRETACION_CHOICES)
    fecha_reinterpretacion = models.DateTimeField(auto_now_add=True) # Timestamp automático

    class Meta:
        unique_together = ["resultado_original",
                           "version_eucast"] # Se obliga a eliminar una reinterpretación antes de generar una
                                             # nueva, ya que no puede haber 2 reinterpretaciones para una
                                             # misma versión EUCAST

        verbose_name = "Reinterpretación EUCAST"
        verbose_name_plural = "Reinterpretaciones EUCAST"

    def __str__(self): # Así queda resuelto a primera vista si hubo cambio con la nueva interpretación
        return f"{self.resultado_original} -> {self.interpretacion_nueva} ({self.version_eucast})"

