from django import forms
from django.core.exceptions import ValidationError

from Base.models import (SexoHospital, MicroorganismoHospital, AmbitoHospital, ServicioHospital, CategoriaMuestraHospital)

class FiltroResistenciaForm(forms.Form):
    """Formulario de filtros para la vista de explorar resistencias"""
    microorganismo = forms.ModelChoiceField(
        queryset=MicroorganismoHospital.objects.none(),
        required=True,
        label="Microorganismo",
        error_messages={
            "required": "Debes seleccionar un microorganismo.",
        }
    )
    fecha_inicio = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    fecha_fin = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    edad_min = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    edad_max = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    sexo = forms.ModelMultipleChoiceField(
        queryset=SexoHospital.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )
    ambito = forms.ModelMultipleChoiceField(
        queryset=AmbitoHospital.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )
    servicio = forms.ModelMultipleChoiceField(
        queryset=ServicioHospital.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )
    tipo_muestra = forms.ModelMultipleChoiceField(
        queryset=CategoriaMuestraHospital.objects.none(),
        required=False,
        label="Categoría de muestra",
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )
    unificar_sei_con_sensibles = forms.BooleanField(
        label="Unificar SEI con S",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    considerar_variantes = forms.BooleanField(
        label="Considerar sólo variantes",
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital:
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(hospital=hospital)
            self.fields["sexo"].queryset = SexoHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["ambito"].queryset = AmbitoHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["servicio"].queryset = ServicioHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["tipo_muestra"].queryset = CategoriaMuestraHospital.objects.filter(hospital=hospital, ignorar_informes=False)

    # sobreescribimos el método clean() para evitar inconsistencias en los filtros y pasar mensajes en español apropiados
    def clean(self):
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get("fecha_inicio")
        fecha_fin = cleaned_data.get("fecha_fin")
        edad_min = cleaned_data.get("edad_min")
        edad_max = cleaned_data.get("edad_max")

        # Validar fechas
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise forms.ValidationError("La fecha de inicio no puede ser mayor que la fecha fin.")

        # Validar edades
        if edad_min is not None and edad_max is not None and edad_min > edad_max:
            raise forms.ValidationError("La edad mínima no puede ser mayor que la edad máxima.")

        return cleaned_data


class InformePredefinidoResistenciaForm(forms.Form):
    """Formulario de filtros para la vista de generación de informe predefinido
    en formato PDF"""
    # Replica en cierto modo el formulario de la vista del explorador
    microorganismo = forms.ModelChoiceField(
        queryset=MicroorganismoHospital.objects.none(),
        required=True,
        label="Microorganismo",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "required": "Debes seleccionar un microorganismo.",
        }
    )

    fecha_inicial = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    fecha_final = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))

    servicio = forms.ModelChoiceField(
        queryset=ServicioHospital.objects.none(),
        required=False,
        empty_label="Todos los servicios",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    categoria_muestra = forms.ModelChoiceField(
        CategoriaMuestraHospital.objects.none(),
        required=False,
        empty_label="Todos los tipos de muestra",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    unificar_sei_con_sensibles = forms.BooleanField(
        label="Unificar SEI con S",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    considerar_variantes = forms.BooleanField(
        label="Considerar sólo variantes",
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    # si se desea comparar con el periodo anterior se ejecutan los test de diferencia de proporciones
    comparar_con_periodo_anterior = forms.BooleanField(
        required=False,
        initial=True,
        label="Comparar con el periodo anterior (mostrar tendencias)",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Muestra flechas ↑/↓ si hay cambios estadísticamente significativos"
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)
        if hospital:
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(hospital=hospital)
            self.fields["servicio"].queryset = ServicioHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["categoria_muestra"].queryset = CategoriaMuestraHospital.objects.filter(hospital=hospital, ignorar_informes=False)

    def clean(self):
        cleaned_data = super().clean()
        fecha_inicial = cleaned_data.get("fecha_inicial")
        fecha_final = cleaned_data.get("fecha_final")

        if fecha_inicial and fecha_final and fecha_inicial > fecha_final:
            raise ValidationError("La fecha de inicio no puede ser mayor que la fecha fin.")

        return cleaned_data

