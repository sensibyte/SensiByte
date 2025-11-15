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
from django.contrib import messages
from django.db import transaction
from django.db.models import Q

from .forms import (
    AntibioticoHospitalForm, MicroorganismoHospitalForm, SexoHospitalForm, AmbitoHospitalForm, ServicioHospitalForm,
    MecanismoResistenciaHospitalForm, TipoMuestraHospitalForm, SubtipoMecanismoResistenciaHospitalForm,
    AliasInterpretacionHospitalForm, MecResValoresPositivosHospitalForm
)
from .global_admin import *
from .mixins import HospitalFilterAdminMixin
from .models import (
    AntibioticoHospital, MicroorganismoHospital, PerfilAntibiogramaHospital, PerfilAntibioticoHospital,
    MecanismoResistenciaHospital, SubtipoMecanismoResistenciaHospital,
    AmbitoHospital, ServicioHospital, SexoHospital, CategoriaMuestraHospital,
    TipoMuestraHospital, AliasInterpretacionHospital, MecResValoresPositivosHospital
)

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
        if request.user.hospital:
            queryset = queryset.filter(antibiotico__es_variante=False)
            # Llamamos al método super para que aplique la búsqueda sobre el queryset filtrado.
            return super().get_search_results(request, queryset, search_term)
        else:
            # si es el superusuario puede ver tanto variantes como no variantes
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
    search_fields = ["hospital__nombre", "grupo_eucast__nombre"]
    actions = ["rellenar_antibioticos"]

    def get_antibioticos(self, obj):
        """Devuelve los antibióticos que pueda tener un perfil de un hospital"""
        return ", ".join([ab.antibiotico.nombre for ab in obj.antibioticos.all()])

    # Acción de creación de registro de perfil de antibióticos asociados
    @admin.action(description="Rellenar antibióticos para este perfil")
    @transaction.atomic
    def rellenar_antibioticos(self, request, queryset):
        for perfil in queryset:
            grupo = perfil.grupo_eucast
            hospital = perfil.hospital

            # La implementación anterior no filtraba qué AntibioticoHospital incluir, necesitamos
            # filtrar por los propios del grupo EUCAST que tienen reglas de interpretación. Así evitamos introducir,
            # por ejemplo, 'Penicilina' en el perfil de 'Enterobacterales'
            # Busca antibióticos válidos: según las reglas de interpretación
            antibioticos_validos = Antibiotico.objects.filter(
                Q(breakpoint_rules__grupo_eucast=grupo) |
                Q(breakpoint_rules__condiciones_taxonomicas__incluye__grupo_eucast=grupo)
            ).distinct()

            # Buscamos los antibióticos del hospital
            antibios_hosp = AntibioticoHospital.objects.filter(
                hospital=hospital,
                antibiotico__in=antibioticos_validos
            )

            creados = 0

            # Creamos si no lo están ya
            for a in antibios_hosp:
                obj, created = PerfilAntibioticoHospital.objects.get_or_create(
                    hospital=hospital,
                    perfil=perfil,
                    antibiotico_hospital=a
                )
                if created:
                    creados += 1

            messages.success(request, f"{perfil}: añadidos {creados} antibióticos válidos.")

    get_antibioticos.short_description = "Antibióticos"

@admin.register(PerfilAntibioticoHospital)
class PerfilAntibioticoHospitalAdmin(HospitalFilterAdminMixin, admin.ModelAdmin):
    list_display = ["perfil", "antibiotico_hospital", "mostrar_en_informes"]
    list_filter = ["mostrar_en_informes", "perfil__hospital", "perfil__grupo_eucast"]
    search_fields = ["perfil__grupo_eucast__nombre", "antibiotico_hospital__antibiotico__nombre"]
    autocomplete_fields = ["perfil", "antibiotico_hospital"]

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
