from django.db import models
from django.db.models import QuerySet

from .widgets import JSONListWidget
from django import forms

# Puesto que en cada base de datos puede haber sinónimos para el mismo
# concepto, podemos crear un Mixin que pueda aplicarse a distintos objetos
# configurables por hospital. La clave está en el atributo "alias", que
# incluye una lista de strings en formato JSON con los distintos sinónimos
# para la instancia del objeto en cuestión.
class AliasMixin(models.Model):
    """ Mixin para formularios de modelos del panel de configuración de
    objetos de modelos específicos de Hospital que incluyan un campo 'alias'
    de tipo JSONField como lista de strings."""

    alias = models.JSONField(default=list, blank=True)

    def match_alias(self, input_str) -> bool:
        """Normaliza la cadena de texto del input del argumento y devuelve booleano
        'True/False' si encuentra o no un sinónimo en la lista de alias"""
        input_str = input_str.strip().lower()
        return any(input_str == a.strip().lower() for a in self.alias)

    class Meta:
        abstract = True

# Mixin para ModelForm para modelos con 'alias' de tipo JSONField
class JSONAliasMixin:
    """ Mixin para formularios de ModelForm que incluyen un campo 'alias'
    de tipo JSONField que debe ser una lista de strings"""

    # Sólo sobreescribimos el método de inicialización para inicializar el campo
    # 'alias' con un widget de tipo JSONListWidget personalizado
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aplicamos el widget JSONListWidget al campo 'alias' si existe
        if 'alias' in self.fields:
            self.fields['alias'].widget = JSONListWidget(attrs={'rows': 4, 'cols': 40})

# Mixins para filtrar por hospital
class HospitalFilterAdminMixin:
    """ Mixin que restringe los objetos visibles en el admin según el hospital del usuario.
    También filtra automáticamente los ForeignKey en los formularios para que solo muestren
    objetos del mismo hospital (cuando aplique)"""

    def get_alias(self, obj):
        """Devuelve los alias que pueda tener un objeto de esta clase de modelo
        para crear la columna ALIAS en el listado del panel de administración"""
        return ", ".join(obj.alias or [])

    get_alias.short_description = "Alias" # El título en la columna del resultado get_alias ("Alias")

    # Para las vistas de usuario hay que restringir a los objetos del propio hospital, no dejar ver
    # a otros usuarios los objetos de otro hospital.
    # Hay que sobreescribir varios métodos:
    # - get_queryset: devuelve una queryset de todas las instancias del modelo que pueden ser editadas.
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.get_search_results
    #
    # - get_fieldsets: devuelve tuplas de 2 que representan los campos del formulario.
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.get_fieldsets
    #
    # - save_model: método de guardado de objetos
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.save_model
    #
    # - get_readonly_fields: método que devuelve una lista o tupla de los nombres de campo de sólo lectura
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.get_readonly_fields
    #
    # - formfield_for_foreignkey: para devolver objetos con relación FK asociados al usuario
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.formfield_for_foreignkey
    #
    # - formfield_for_manytomany: para devolver objetos con relaciones ManyToMany asociados al usuario
    #   ref: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#django.contrib.admin.ModelAdmin.formfield_for_foreignkey


    def get_queryset(self, request) -> QuerySet:
        """ Filtra los objetos que aparecerán en la lista del admin por HOSPITAL.
        Si el usuario es superusuario no hay filtrado, devuelve el queryset completo """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(hospital=request.user.hospital)

    def get_fieldsets(self, request, obj=None):
        """ Elimina el campo de 'hospital' de los modelos específicos de Hospital. La sobreescritura
        del metodo 'save_model' ya garantiza la asignación del Hospital, no necesitamos que se muestre
        en la vista del usuario. Sólo si el usuario es superusuario se muestra este campo.
        Código en base a la respuesta: https://stackoverflow.com/questions/54116389/how-to-exclude-fields-in-get-fieldsets-based-on-user-type-in-django-admin"""
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets

        filtered_fieldsets = [] # inicializamos para guardar los fieldsets finales
        for titulo, opciones in fieldsets: # es una lista de tuplas [(titulo, {opciones}),]
            fields = list(opciones.get("fields", ())) # pasamos a lista para poder cambiar el contenido de la tupla, que es inmutable
            if "hospital" in fields:
                fields.remove("hospital") # elimina el campo 'hospital' de los fieldsets
            filtered_fieldsets.append((titulo, {"fields": fields})) # formamos de nuevo los fieldsets finales
        return filtered_fieldsets

    def save_model(self, request, obj, form, change):
        """ Asigna automáticamente el Hospital de los modelos específicos de Hospital en base
        al atributo hospital del usuario al guardar sus objetos."""
        if not obj.hospital_id and not request.user.is_superuser:
            obj.hospital = request.user.hospital # atributo hospital del usuario conectado
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        """Esto es sólo por si acaso, ya que no debería de mostrarse nunca el campo de Hospital. Pero si lo hiciera,
        estaría marcado como solo lectura"""
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.append("hospital") # si el usuario NO es superusuario, guardar el campo 'hospital' en campos de solo lectura
        return readonly

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """ Limita los ForeignKey a objetos del mismo hospital del usuario (si no es superuser).
        Detecta dinámicamente si el modelo FK tiene un campo 'hospital' para mostrar sólo los objetos
        del hospital del usuario.

        Ver https://stackoverflow.com/questions/41644515/filter-django-admin-many-to-one-editor, respuesta
        de glowka
        """
        # Hacemos la restricción si el usuario no es el superusuario
        if not request.user.is_superuser:
            related_model = db_field.remote_field.model # accedemos al modelo relacionado

            # Si el modelo relacionado tiene campo 'hospital' declarado en los metadatos, filtramos
            # los objetos por hospital del usuario.
            #
            # ref: https://docs.djangoproject.com/en/5.2/ref/models/meta/#retrieving-all-field-instances-of-a-model
            if any(f.name == "hospital" for f in related_model._meta.get_fields()):

                # Si sí tiene el campo 'hospital' filtra los objetos por el hosptial del usuario
                # y pásalo a la 'queryset' de los kwargs
                kwargs["queryset"] = related_model.objects.filter(
                    hospital=request.user.hospital # Filtrar la queryset por hospital
                )
        # devolvemos los objetos filtrados (van en la queryset de los kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limita los ManyToMany a objetos del mismo hospital del usuario (si no es superuser).
        Detecta dinámicamente si el modelo relacionado tiene campo 'hospital'.
        Procede de forma análoga a formfield_for_foreignkey, pero para las relaciones ManyToMany
        """
        if not request.user.is_superuser:
            related_model = db_field.remote_field.model

            # Si el modelo relacionado tiene campo 'hospital', filtramos por hospital del usuario
            if any(f.name == "hospital" for f in related_model._meta.get_fields()):

                kwargs["queryset"] = related_model.objects.filter(hospital=request.user.hospital) # Filtramos por hospital

        return super().formfield_for_manytomany(db_field, request, **kwargs)



