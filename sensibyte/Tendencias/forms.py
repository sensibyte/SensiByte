from datetime import date

from dateutil.relativedelta import relativedelta
from django import forms

from Base.global_models import SubtipoMecanismoResistencia
from Base.models import (AntibioticoHospital, SexoHospital, AmbitoHospital, ServicioHospital, CategoriaMuestraHospital,
                         MicroorganismoHospital, EucastVersion, MecanismoResistenciaHospital)


# Formulario de reinterpretación de resultados
class ReinterpretacionForm(forms.Form):
    fecha_inicio = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    fecha_fin = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    version_eucast = forms.ModelChoiceField(
        queryset=EucastVersion.objects.all(),
        widget=forms.Select(attrs={"class": "form-control"})
    )
    microorganismo = forms.ModelChoiceField(
        queryset=MicroorganismoHospital.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"})
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)

        if hospital:
            # Filtrar microorganismos y antibióticos por hospital
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(
                hospital=hospital
            ).select_related("microorganismo").order_by("microorganismo__nombre")

        # Establecer valores por defecto de fechas
        if not self.data.get("fecha_fin"):
            self.initial["fecha_fin"] = date.today()
        if not self.data.get("fecha_inicio"):
            self.initial["fecha_inicio"] = date.today() - relativedelta(years=3)  # 3 años atrás

    def clean(self):
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get("fecha_inicio")
        fecha_fin = cleaned_data.get("fecha_fin")
        version_eucast = cleaned_data.get("version_eucast")

        # Validar fechas
        if fecha_inicio and fecha_fin:
            if fecha_inicio >= fecha_fin:
                raise forms.ValidationError(
                    "La fecha de inicio debe ser anterior a la fecha de fin."
                )

            diferencia = (fecha_fin - fecha_inicio).days
            if diferencia > 1825:  # 5 años
                raise forms.ValidationError(
                    "El rango de fechas no puede superar los 5 años."
                )

            if diferencia < 30:  # menos de un mes
                raise forms.ValidationError(
                    "El rango de fechas debe ser de al menos 30 días."
                )

            if fecha_fin.year >= version_eucast.anyo:
                raise forms.ValidationError(
                    f"Ajusta el periodo de finalización al 31 de diciembre del año {fecha_fin.year - 1}"
                )

# Formulario de análisis de tendencia a lo largo del tiempo
class TendenciasForm(forms.Form):
    """
    Formulario para seleccionar parámetros de análisis de tendencias.
    """

    fecha_inicio = forms.DateField(
        label="Fecha de inicio",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
        help_text="Fecha inicial del periodo a analizar"
    )

    fecha_fin = forms.DateField(
        label="Fecha de fin",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
        help_text="Fecha final del periodo a analizar"
    )

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

    version_eucast = forms.ModelChoiceField(
        queryset=EucastVersion.objects.all().order_by("-anyo"),
        label="Versión EUCAST de referencia",
        widget=forms.Select(attrs={"class": "form-control"}),
        help_text="Todos los datos se interpretarán según esta versión para comparabilidad"
    )

    microorganismo = forms.ModelChoiceField(
        queryset=MicroorganismoHospital.objects.none(),
        label="Microorganismo",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    antibiotico = forms.ModelChoiceField( # Si queremos ver la tendencia por un antibiótico concreto
        queryset=AntibioticoHospital.objects.none(),
        label="Antibiótico",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    mec_resistencia = forms.ModelChoiceField( # Si queremos ver la tendencia por algún tipo de resistencia específica
        queryset=MecanismoResistenciaHospital.objects.none(),
        label="Mecanismo de resistencia",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    sub_mec_resistencia = forms.ModelChoiceField(
        queryset=SubtipoMecanismoResistencia.objects.none(),
        label="Subtipo mecanismo de resistencia",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    AGRUPACION_CHOICES = [
        ("trimestre", "Por trimestre"),
        ("semestre", "Por semestre"),
        ("anyo", "Por año"),
    ]

    agrupacion = forms.ChoiceField(
        choices=AGRUPACION_CHOICES,
        label="Agrupación temporal",
        initial="trimestre",
        widget=forms.Select(attrs={"class": "form-control"}),
        help_text="Cómo agrupar los datos en el tiempo"
    )

    def __init__(self, *args, hospital=None, **kwargs):
        super().__init__(*args, **kwargs)

        if hospital:
            # Filtrar microorganismos y antibióticos por hospital
            self.fields["microorganismo"].queryset = MicroorganismoHospital.objects.filter(
                hospital=hospital
            ).select_related("microorganismo").order_by("microorganismo__nombre")

            self.fields["sexo"].queryset = SexoHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["ambito"].queryset = AmbitoHospital.objects.filter(hospital=hospital, ignorar_informes=False)
            self.fields["servicio"].queryset = ServicioHospital.objects.filter(hospital=hospital,
                                                                               ignorar_informes=False)
            self.fields["tipo_muestra"].queryset = CategoriaMuestraHospital.objects.filter(hospital=hospital,
                                                                                           ignorar_informes=False)

        # Establecer valores por defecto de fechas
        if not self.data.get("fecha_fin"):
            self.initial["fecha_fin"] = date.today()
        if not self.data.get("fecha_inicio"):
            self.initial["fecha_inicio"] = date.today() - relativedelta(years=3)  # 3 años atrás

    def clean(self):
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get("fecha_inicio")
        fecha_fin = cleaned_data.get("fecha_fin")
        edad_min = cleaned_data.get("edad_min")
        edad_max = cleaned_data.get("edad_max")

        # Validar fechas
        if fecha_inicio and fecha_fin:
            if fecha_inicio >= fecha_fin:
                raise forms.ValidationError(
                    "La fecha de inicio debe ser anterior a la fecha de fin."
                )

            # Validar que el rango (por ejemplo, máximo 25 años)
            # Puede ser computacionalmente costoso, pero es posible que modele de forma adecuada
            diferencia = (fecha_fin - fecha_inicio).days
            if diferencia > 9125:  # 25 años
                raise forms.ValidationError(
                    "El rango de fechas no puede superar los 25 años."
                )

            if diferencia < 30:  # menos de un mes
                raise forms.ValidationError(
                    "El rango de fechas debe ser de al menos 30 días."
                )

        # Validar edades
        if edad_min is not None and edad_max is not None and edad_min > edad_max:
            raise forms.ValidationError("La edad mínima no puede ser mayor que la edad máxima.")

        return cleaned_data
