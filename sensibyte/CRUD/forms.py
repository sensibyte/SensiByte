from typing import Any

from django import forms
from django.forms import inlineformset_factory, modelformset_factory, BaseInlineFormSet, Select

from Base.models import (ResultadoAntibiotico, MicroorganismoHospital, SubtipoMecanismoResistenciaHospital,
                         MecanismoResistenciaHospital, AntibioticoHospital, Registro, Aislado)


class CargarAntibiogramaForm(forms.Form):
    """Formulario de carga de archivos con datos de antibiograma
    Se sobreescribe el método de inicialización para incluir sólo
    los objetos MicroorganismoHospital del hospital del usuario"""

    # El campo de microorganismo es el único que requiero consultar en la base de datos,
    # el resto los puedo pasar por el contexto
    microorganismo = forms.ModelChoiceField(
        queryset=MicroorganismoHospital.objects.none(),
        required=True,  # siempre debe elegirse el microorganismo para el que se hace la carga
        label="Microorganismo"
    )

    def __init__(self, *args, hospital=None, **kwargs):  # incorporamos el hospital como argumento
        super().__init__(*args, **kwargs)
        if hospital:  # si hay hospital, es usuario, filtra los microorganismos de ese hospital para generar el campo
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(hospital=hospital)


class FiltroRegistroForm(forms.Form):
    """ Formulario de filtros para la vista del listado de objetos Registro.
    Se sobreescribe el método de inicialización para incluir solo objetos MicroorganismoHospital,
    MecanismoResistenciaHospital y AntibioticoHospital del hospital del usuario"""
    fecha_inicio = forms.DateField(required=False,
                                   widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    fecha_fin = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    microorganismo = forms.ModelChoiceField(queryset=MicroorganismoHospital.objects.none(), required=False,
                                            label="Microorganismo", widget=forms.Select(attrs={"class": "form-select"}))
    mecanismo = forms.ModelChoiceField(queryset=MecanismoResistenciaHospital.objects.none(), required=False,
                                       label="Mecanismo de resistencia",
                                       widget=forms.Select(attrs={"class": "form-select"}))
    antibiotico = forms.ModelMultipleChoiceField(
        queryset=AntibioticoHospital.objects.none(),
        required=False,
        label="Resistente a los antibióticos",
        widget=forms.SelectMultiple(attrs={
            "class": "form-select select2-antibioticos",
            "data-placeholder": "Buscar antibióticos..."
        })
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital: # obtenemos los objetos por el hospital del usuario
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(hospital=hospital)
            self.fields["mecanismo"].queryset = MecanismoResistenciaHospital.objects.filter(hospital=hospital)
            self.fields["antibiotico"].queryset = AntibioticoHospital.objects.filter(
                hospital=hospital,
                antibiotico__es_variante=False,  # solo antibióticos base, no variantes
            ).select_related("antibiotico").order_by("antibiotico__nombre")


class RegistroForm(forms.ModelForm):
    """Formulario para los objetos Registro de la clase ModelForm"""

    class Meta:
        model = Registro
        fields = ["fecha", "edad", "sexo", "ambito", "servicio", "tipo_muestra"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "edad": forms.NumberInput(attrs={"class": "form-control"}),
            "sexo": forms.Select(attrs={"class": "form-select"}),
            "ambito": forms.Select(attrs={"class": "form-select"}),
            "servicio": forms.Select(attrs={"class": "form-select"}),
            "tipo_muestra": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        hospital = kwargs.pop("hospital", None)
        super().__init__(*args, **kwargs)

        if hospital:
            # Si hay hospital extraemos los servicos y tipos de muestra del hospital del usuario
            self.fields["servicio"].queryset = hospital.servicios_hospital.all()
            self.fields["tipo_muestra"].queryset = hospital.categorias_muestra_hospital.all()

        # para el campo de fecha, inicializar el texto en formato Y-m-d
        if self.instance and self.instance.pk and self.instance.fecha:
            self.initial["fecha"] = self.instance.fecha.strftime("%Y-%m-%d")


class AisladoBaseFormSet(BaseInlineFormSet):
    """Sobreescribimos el método clean().
    ref: https://docs.djangoproject.com/en/5.2/topics/forms/modelforms/#overriding-methods-on-an-inlineformset"""
    def clean(self):
        super().clean() # llamamos primero al método principal

        valid_forms = 0 # inicializamos el número de formularios

        for form in self.forms:

            # ignorar si el usuario no cambió el formulario o se ha marcado para borrar
            if not form.has_changed():
                continue
            if self.can_delete and self._should_delete_form(form):
                continue

            # para formularios que cambiaron desde su inicialización (modificación por usuario)
            # y NO son válidos -> levantar una excepción de validación
            if form.has_changed() and not form.is_valid():
                cleaned_data = getattr(form, "cleaned_data", {})

                # buscamos en el formulario si algún campo tiene datos parciales, es decir, no es cadena vacía ni
                # corresponde al campo especial 'DELETE' para algún campo
                has_data = any(
                    value for key, value in cleaned_data.items()
                    if key != "DELETE" and value not in [None, ""]
                )
                # tiene datos parciales
                if has_data:
                    raise forms.ValidationError("Hay un aislado con datos incompletos.")

            # si el formulario es válido
            if form.is_valid():
                valid_forms += 1


class AisladoForm(forms.ModelForm):
    class Meta:
        model = Aislado
        fields = ["microorganismo"]
        widgets = {
            "microorganismo": Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        hospital = kwargs.pop("hospital", None)
        super().__init__(*args, **kwargs)

        if hospital:
            # Filtrar sólo los microorganismos del hospital actual
            self.fields["microorganismo"].queryset = hospital.microorganismos_hospital.all()


# Aislado formset para la vista UpdateView.
# ref: https://docs.djangoproject.com/en/5.2/topics/forms/modelforms/#inline-formsets
AisladoFormSet = inlineformset_factory(
    Registro,
    Aislado,
    form=AisladoForm,
    formset=AisladoBaseFormSet,
    extra=0,
    can_delete=True
)

# ResultadoAntibiotico formset para la vista de edición de antibiograma
ResultadoFormSet = modelformset_factory(
    ResultadoAntibiotico,
    fields=["interpretacion", "cmi"],  # NO se incluye 'antibiotico' (no se edita)
    extra=0,
    can_delete=True,
    widgets={
        "interpretacion": forms.Select(attrs={"class": "form-select"}),
        "cmi": forms.NumberInput(attrs={"class": "form-control"}),
    }
)


class MecanismoResistenciaForm(forms.ModelForm):
    """Formulario para editar mecanismos de resistencia de un Aislado de la clase ModelForm"""

    class Meta:
        model = Aislado
        fields = ["mecanismos_resistencia", "subtipos_resistencia"]
        widgets = {
            "mecanismos_resistencia": forms.CheckboxSelectMultiple,
            "subtipos_resistencia": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        aislado: Aislado | None = kwargs.pop("aislado", None)
        super().__init__(*args, **kwargs)

        fields: dict[str, Any] = self.fields  # tipado de fields

        if aislado:
            hospital = getattr(aislado.registro, "hospital", None) # extraemos el hospital del Registro del Aislado
            if hospital:
                # Solo mostrar mecanismos del hospital
                fields["mecanismos_resistencia"].queryset = MecanismoResistenciaHospital.objects.filter(
                    hospital=hospital
                )
                # Subtipos que pertenecen a los mecanismos del hospital
                fields["subtipos_resistencia"].queryset = SubtipoMecanismoResistenciaHospital.objects.filter(
                    hospital=hospital
                )
