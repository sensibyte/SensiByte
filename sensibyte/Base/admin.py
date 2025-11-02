# admin.py: configuraciones de la interfaz de administración de Django para los modelos de la aplicación.
# Sólo se incluyen en este archivo para los modelos a nivel de HOSPITAL
#
# Cualquier modelo puede ser llamado como clase "Modelo"Admin y heredar de admin.ModelAdmin para ello
# Los atributos más habituales son:
#
# Para la lista de registros:
#
# list_display - Columnas a mostrar
# list_filter - Filtros laterales
# search_fields - Campos buscables
# list_editable - Campos editables en la lista
# list_per_page - Registros por página
# ordering - Ordenación por defecto
#
# Para la edición del formulario
#
# form - Formulario a mostrar (sobreescribe el que saldría por defecto)
# fields - Campos a mostrar (y su orden)
# exclude - Campos a ocultar
# readonly_fields - Campos de sólo lectura
# autocomplete_fields - Autocompletar para FK
# filter_horizontal / filter_vertical - Selector para ManyToMany
#
# https://docs.djangoproject.com/en/5.2/ref/contrib/admin/

from .forms import (
    AntibioticoHospitalForm, MicroorganismoHospitalForm, SexoHospitalForm, AmbitoHospitalForm, ServicioHospitalForm,
    MecanismoResistenciaHospitalForm, TipoMuestraHospitalForm, SubtipoMecanismoResistenciaHospitalForm,
    AliasInterpretacionHospitalForm, MecResValoresPositivosHospitalForm
)
from .global_admin import *
from .mixins import HospitalFilterAdminMixin
from .models import (
    AntibioticoHospital, MicroorganismoHospital, PerfilAntibiogramaHospital,
    MecanismoResistenciaHospital, SubtipoMecanismoResistenciaHospital,
    AmbitoHospital, ServicioHospital, SexoHospital, CategoriaMuestraHospital,
    TipoMuestraHospital, Registro, AliasInterpretacionHospital, MecResValoresPositivosHospital
)


# Admin Registro
# Este panel de Registros sólo estará disponible para administradores, no para otro rol
@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ["hospital", "fecha", "edad", "sexo", "ambito", "servicio", "tipo_muestra"]


# Admin AntibioticoHospital
@admin.register(AntibioticoHospital)
class AntibioticoHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = AntibioticoHospitalForm
    autocomplete_fields = ["antibiotico"]
    list_display = ["hospital", "antibiotico", "get_alias"]
    search_fields = ["antibiotico__nombre"]
    list_filter = ["antibiotico__familia_antibiotico"]

    def get_search_results(self, request, queryset, search_term):
        """
        Sobrescribe get_search_results para aplicar un filtro adicional:
        sólo muestra los AntibioticoHospital cuyo antibiótico asociado no sea una variante.

        Referencias:
        - https://docs.djangoproject.com/en/stable/ref/contrib/admin/#django.contrib.admin.ModelAdmin.get_search_results
        - https://stackoverflow.com/questions/64571673/how-to-override-django-get-search-results-method-in-modeladmin-while-keeping-fi
        """
        queryset = queryset.filter(antibiotico__es_variante=False)
        # Llamamos al método super para que aplique la búsqueda sobre el queryset filtrado.
        return super().get_search_results(request, queryset, search_term)


# Admin MicroorganismoHospital
@admin.register(MicroorganismoHospital)
class MicroorganismoHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = MicroorganismoHospitalForm
    list_display = ["hospital", "microorganismo", "get_alias"]
    list_filter = ["microorganismo__grupo_eucast"]
    search_fields = ["microorganismo__nombre"]
    autocomplete_fields = ["microorganismo"]


@admin.register(PerfilAntibiogramaHospital)
class PerfilAntibiogramaHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    list_display = ["hospital", "grupo_eucast", "get_antibioticos"]
    autocomplete_fields = ["grupo_eucast", "antibioticos"]

    def get_antibioticos(self, obj):
        """Devuelve los antibióticos que pueda tener un perfil de un hospital"""
        return ", ".join([ab.antibiotico.nombre for ab in obj.antibioticos.all()])

    get_antibioticos.short_description = "Antibióticos"


# Admin MecanismoResistenciaHospital
@admin.register(MecanismoResistenciaHospital)
class MecanismoResistenciaHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = MecanismoResistenciaHospitalForm
    list_display = ["mecanismo", "hospital", "get_alias"]
    search_fields = ["mecanismo__nombre", "alias"]
    autocomplete_fields = ["mecanismo"]


# Admin SubtipoMecanismoResistenciaHospital
@admin.register(SubtipoMecanismoResistenciaHospital)
class SubtipoMecanismoResistenciaHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = SubtipoMecanismoResistenciaHospitalForm
    list_display = ["subtipo_mecanismo", "hospital", "get_alias"]
    search_fields = ["subtipo_mecanismo__nombre", "alias"]
    autocomplete_fields = ["subtipo_mecanismo"]


# Admin AmbitoHospital
@admin.register(AmbitoHospital)
class AmbitoHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = AmbitoHospitalForm
    list_display = ["hospital", "ambito", "get_alias", "ignorar_informes"]
    list_filter = ["ignorar_informes"]
    search_fields = ["ambito__nombre"]
    autocomplete_fields = ["ambito"]


# Admin ServicioHospital
@admin.register(ServicioHospital)
class ServicioHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = ServicioHospitalForm
    list_display = ["hospital", "servicio", "get_alias", "ignorar_informes"]
    list_filter = ["ignorar_informes"]
    search_fields = ["servicio__nombre"]
    autocomplete_fields = ["servicio"]


# Admin SexoHospital
@admin.register(SexoHospital)
class SexoHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = SexoHospitalForm
    list_display = ["hospital", "sexo", "get_alias", "ignorar_informes"]
    list_filter = ["ignorar_informes"]
    search_fields = ["sexo__descripcion", "sexo__codigo"]
    autocomplete_fields = ["sexo"]


# Admin CategoriaMuestraHospital
@admin.register(CategoriaMuestraHospital)
class CategoriaMuestraHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    list_display = ["hospital", "nombre", "ignorar_minimo", "ignorar_informes"]
    list_filter = ["ignorar_informes", "ignorar_minimo"]
    search_fields = ["nombre"]


# Admin TipoMuestraHospital
@admin.register(TipoMuestraHospital)
class TipoMuestraHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = TipoMuestraHospitalForm
    list_display = ["hospital", "tipo_muestra__nombre", "get_alias"]
    list_filter = ["hospital", "categoria"]
    search_fields = ["tipo_muestra__nombre"]


# Admin AliasInterpretacionHospital
@admin.register(AliasInterpretacionHospital)
class AliasInterpretacionHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = AliasInterpretacionHospitalForm
    list_display = ["hospital", "get_alias", "interpretacion"]


# Admin MecResValoresPositivosHospital
@admin.register(MecResValoresPositivosHospital)
class MecResValoresPositivosHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    form = MecResValoresPositivosHospitalForm
    list_display = ["hospital", "get_alias"]
