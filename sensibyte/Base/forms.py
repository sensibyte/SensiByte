# forms.py: contiene las clases que definen los formularios del panel de Administración.
# En este caso, para la app Base, se declaran los formularios en base a los modelos de la aplicación, de forma directa
# mediante la clase ModelForm, que puede desplegar todos sus campos llamando a "__all__"
# Se utilizará el mixin JSONAliasMixin para heredar el metodo clean_alias y el widget JSONListWidget
#
# https://docs.djangoproject.com/en/5.2/ref/forms/models/

from django import forms
from .models import (
    AliasInterpretacionHospital, MecResValoresPositivosHospital,
    SubtipoMecanismoResistenciaHospital, MicroorganismoHospital,
    MecanismoResistenciaHospital, TipoMuestraHospital,
    AntibioticoHospital, SexoHospital, AmbitoHospital, ServicioHospital
)
from .mixins import JSONAliasMixin


# Formulario de Antibiotico
class AntibioticoHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = AntibioticoHospital
        fields = "__all__"  # todos los campos, de esta forma acortamos la generación de lista de campos


# Formulario de Microorganismo
class MicroorganismoHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = MicroorganismoHospital
        fields = "__all__"


# Formulario Sexo
class SexoHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = SexoHospital
        fields = "__all__"


# Formulario de Ambito
class AmbitoHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = AmbitoHospital
        fields = "__all__"


# Formulario de Servicio
class ServicioHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = ServicioHospital
        fields = "__all__"


# Formulario TipoMuestraHospital
class TipoMuestraHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = TipoMuestraHospital
        fields = "__all__"


# Formulario MecanismoResistencia
class MecanismoResistenciaHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = MecanismoResistenciaHospital
        fields = "__all__"


# Formulario MecResValoresPositivosHospital
class MecResValoresPositivosHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = MecResValoresPositivosHospital
        fields = "__all__"


# Formulario SubtipoMecanismoResistenciaHospital
class SubtipoMecanismoResistenciaHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = SubtipoMecanismoResistenciaHospital
        fields = "__all__"


# Formulario AliasInterpretacionHospital
class AliasInterpretacionHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = AliasInterpretacionHospital
        fields = "__all__"
