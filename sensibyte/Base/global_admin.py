# global_admin.py: configuraciones de la interfaz de administración de Django para los modelos de la aplicación.
# Sólo se incluyen en este archivo para los modelos a nivel GENERAL (NO los específicos por Hospital con "alias")
# No es necesario pasarle un form, ya lo genera él solo a partir de los campos que tiene el modelo llamandolo ModeloAdmin
#
# Ver admin.py para más información
#

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.safestring import mark_safe

from .models import (
    Hospital, Usuario, ClaseAntibiotico, FamiliaAntibiotico, Espectro, Antibiotico,
    GrupoEucast, Microorganismo, MecanismoResistencia, SubtipoMecanismoResistencia,
    Ambito, Servicio, Sexo, TipoMuestra, EucastVersion, BreakpointRule
)


# Admin Hospital
# Se restringirá su visualización, edición y eliminación a través del manejador de Grupos incorporado en Django
@admin.register(Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = ["nombre", "logo_preview"]
    readonly_fields = ["logo_preview"]
    search_fields = ["nombre"]

    def logo_preview(self, obj):
        """Para enseñar el logotipo del hospital en la tabla del listado, si se carga alguno en el formulario"""
        if obj.logo:
            html = f'<img src="{obj.logo.url}" width="100" height="100" style="object-fit:contain;border:1px solid #ccc;">'
            return mark_safe(html)
        # Si no se cargó imagen de logo, simplemente poner la frase (sin logo) en la celda
        return "(sin logo)"

    logo_preview.short_description = "Vista previa"


# Admin Usuario
# Se restringirá su visualización, edición y eliminación a través del manejador de Grupos incorporado en Django
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ["username", "email", "hospital", "is_staff", "is_superuser"]
    list_filter = ["hospital", "is_staff", "is_superuser"]
    fieldsets = UserAdmin.fieldsets + (
        ["Información hospitalaria", {"fields": ["hospital", "rol"]}],
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ["Información hospitalaria", {"fields": ["hospital", "rol"]}],
    )


# Admin ClaseAntibiotico
@admin.register(ClaseAntibiotico)
class ClaseAntibioticoAdmin(admin.ModelAdmin):
    list_display = ["nombre"]
    search_fields = ["nombre"]


# Admin FamiliaAntibiotico
@admin.register(FamiliaAntibiotico)
class FamiliaAntibioticoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "clase"]
    search_fields = ["nombre"]
    autocomplete_fields = ["clase"]


# Admin Espectro
@admin.register(Espectro)
class EspectroAdmin(admin.ModelAdmin):
    list_display = ["gp", "gn", "ana", "aty"]
    list_filter = ["gp", "gn", "ana", "aty"]
    search_fields = ["id"]


# Admin Antibiotico global
@admin.register(Antibiotico)
class AntibioticoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "abr", "familia_antibiotico"]
    list_filter = ["familia_antibiotico"]
    search_fields = ["nombre", "abr"]
    autocomplete_fields = ["familia_antibiotico", "espectro"]


# Admin GrupoEucast
@admin.register(GrupoEucast)
class GrupoEucastAdmin(admin.ModelAdmin):
    list_display = ["nombre"]
    search_fields = ["nombre"]


# Admin Microorganismo global
@admin.register(Microorganismo)
class MicroorganismoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "grupo_eucast", "mtype"]
    list_filter = ["grupo_eucast", "mtype"]
    search_fields = ["nombre"]
    autocomplete_fields = ["grupo_eucast", "resistencia_intrinseca"]
    filter_horizontal = ["resistencia_intrinseca"]


# Admin MecanismoResistencia global
@admin.register(MecanismoResistencia)
class MecanismoResistenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre"]
    search_fields = ["nombre"]
    filter_horizontal = ["grupos_eucast"]


# Admin SubtipoMecanismoResistencia global
@admin.register(SubtipoMecanismoResistencia)
class SubtipoMecanismoResistenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "mecanismo"]
    search_fields = ["nombre"]
    autocomplete_fields = ["mecanismo"]


# Admin Ambito
@admin.register(Ambito)
class AmbitoAdmin(admin.ModelAdmin):
    list_display = ["nombre"]
    search_fields = ["nombre"]


# Admin Servicio
@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ["nombre", ]
    search_fields = ["nombre"]


# Admin Sexo
@admin.register(Sexo)
class SexoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descripcion"]
    search_fields = ["codigo", "descripcion"]


# Admin TipoMuestra
@admin.register(TipoMuestra)
class TipoMuestraAdmin(admin.ModelAdmin):
    list_display = ["clasificacion", "nombre", "codigo_loinc"]
    search_fields = ["nombre", "clasificacion", "codigo_loinc"]


# Admin EucastVersion
@admin.register(EucastVersion)
class EucastVersionAdmin(admin.ModelAdmin):
    list_display = ["year", "version", "descripcion"]
    search_fields = ["year"]


# Admin BreakpointRule
@admin.register(BreakpointRule)
class BreakpointRuleAdmin(admin.ModelAdmin):
    list_display = ["antibiotico", "version_eucast"]
    search_fields = ["antibiotico", "version_eucast"]
