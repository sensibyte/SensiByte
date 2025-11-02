# forms.py: contiene las clases que definen los formularios del panel de Administración.
# En este caso, para la app Base, se declaran los formularios en base a los modelos de la aplicación, de forma directa
# mediante la clase ModelForm, que puede desplegar todos sus campos llamando a "__all__"
# Se utilizará el mixin JSONAliasMixin para heredar el metodo clean_alias y el widget JSONListWidget
#
# https://docs.djangoproject.com/en/5.2/ref/forms/models/

from django import forms

from .mixins import JSONAliasMixin
from .models import (
    AliasInterpretacionHospital, MecResValoresPositivosHospital,
    SubtipoMecanismoResistenciaHospital, MicroorganismoHospital,
    MecanismoResistenciaHospital, TipoMuestraHospital,
    AntibioticoHospital, SexoHospital, AmbitoHospital, ServicioHospital,
    Antibiotico, Microorganismo, TipoMuestra
)
from .widgets import JSONListWidget


class AntibioticoForm(forms.ModelForm):
    # Para los campos JSONField utilizaremos el widget personalizado
    # JSONListWidget, que permite visualizar de forma más limpia la lista
    # del JSON de la base de datos y guarda de forma segura el resultado
    # que se le pase
    atc = forms.JSONField(
        required=False,
        widget=JSONListWidget(attrs={"rows": 4, "cols": 60}),
    )
    loinc = forms.JSONField(
        required=False,
        widget=JSONListWidget(attrs={"rows": 4, "cols": 60}),
    )
    class Meta:
        model = Antibiotico
        fields = "__all__" # todos los campos, de esta forma acortamos la generación de campos

    def clean_loinc(self):
        # tomamos el valor que viene del formulario
        data = self.cleaned_data.get("loinc")
        return data or [] # si está vacío, es None (False) -> devuelve una lista vacía para el JSONField en la BBDD

    def clean_atc(self):
        data = self.cleaned_data.get("atc")
        return data or []

# En estos modelos globales procedemos de forma análoga a AntibioticoForm
class MicroorganismoForm(forms.ModelForm):
    snomed = forms.JSONField(
        required=False,
        widget=JSONListWidget(attrs={"rows": 4, "cols": 60}),
    )
    class Meta:
        model = Microorganismo
        fields = "__all__"

    def clean_snomed(self):
        data = self.cleaned_data.get("snomed")
        return data or []

class TipoMuestraForm(forms.ModelForm):
    codigos_loinc = forms.JSONField(
        required=False,
        widget=JSONListWidget(attrs={"rows": 4, "cols": 60}),
    )
    class Meta:
        model = TipoMuestra
        fields = "__all__"

    def clean_codigos_loinc(self):
        data = self.cleaned_data.get("codigos_loinc")
        return data or []

# Formulario de Antibiotico
# A partir de esta línea tenemos los formularios asociados a los modelos hospital específicos
# En este caso heredamos de JSONAliasMixin, asociado a modelos con Alias para permitir la
# visualización y guardado de datos de forma análoga a JSONLstWidget
class AntibioticoHospitalForm(JSONAliasMixin, forms.ModelForm):
    class Meta:
        model = AntibioticoHospital
        fields = "__all__"


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
