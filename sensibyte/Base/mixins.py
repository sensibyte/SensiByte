from django.db import models
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

    def match_alias(self, input_str):
        """Normaliza la cadena de texto del input del argumento y devuelve booleano
        'True/False' si encuentra o no un sinónimo en la lista de alias"""
        input_str = input_str.strip().lower()
        return any(input_str == a.strip().lower() for a in self.alias)

    class Meta:
        abstract = True

# Mixin para ModelForm con alias de tipo JSONField
class JSONAliasMixin:
    """ Mixin para formularios de ModelForm que incluyen un campo 'alias'
    de tipo JSONField que debe ser una lista de strings."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aplicamos el widget JSONListWidget al campo 'alias' si existe
        if 'alias' in self.fields:
            self.fields['alias'].widget = JSONListWidget(attrs={'rows': 4, 'cols': 40})

    def clean_alias(self):
        value = self.cleaned_data['alias']

        # Asegurarse de que sea una lista
        if not isinstance(value, list):
            raise forms.ValidationError("Debe ser una lista de cadenas.")

        # Verificar que todos los elementos sean strings
        if not all(isinstance(a, str) for a in value):
            raise forms.ValidationError("Todos los elementos deben ser cadenas de texto.")

        return value

# Mixins para filtrar por hospital
class HospitalFilterAdminMixin:
    """ Mixin que restringe los objetos visibles en el admin según el hospital del usuario.
    También filtra automáticamente los ForeignKey en los formularios para que solo muestren
    objetos del mismo hospital (cuando aplicable)."""

    def get_alias(self, obj):
        """Devuelve los alias que pueda tener un objeto de esta clase de modelo
        para crear la columna ALIAS en el listado del panel de administración"""
        return ", ".join(obj.alias or [])

    get_alias.short_description = "Alias" # El título en la columna del resultado get_alias ("Alias")

    def get_queryset(self, request):
        """ Filtra los objetos que aparecerán en la lista del admin por HOSPITAL.
        Si el usuario es superusuario no hay filtrado, devuelve el queryset completo """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(hospital=request.user.hospital)

    def save_model(self, request, obj, form, change):
        """ Asigna automáticamente el Hospital de los modelos específicos de Hospital en base
        al atributo hospital del usuario al guardar sus objetos."""
        if not obj.hospital_id and not request.user.is_superuser:
            obj.hospital = request.user.hospital # atributo hospital
        super().save_model(request, obj, form, change)

    def get_fieldsets(self, request, obj=None):
        """ Elimina el campo de 'hospital' de los modelos específicos de Hospital. La sobreescritura
        del metodo 'save_model' ya garantiza la asignación del Hospital, no necesitamos que se muestre
        en la UI del usuario. Sólo si el usuario es superusuario se muestra este campo.
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

        Ver https://stackoverflow.com/questions/41644515/filter-django-admin-many-to-one-editor
        """
        if not request.user.is_superuser:
            related_model = db_field.remote_field.model

            # Si el modelo relacionado tiene campo 'hospital' declarado en los metadatos, filtramos
            # los objetos por hospital del usuario
            if any(f.name == "hospital" for f in related_model._meta.get_fields()):

                kwargs["queryset"] = related_model.objects.filter(
                    hospital=request.user.hospital # Filtrar la queryset por hospital
                )

            # Si el campo ES 'hospital', seleccionar el propio hospital a través de su propia id
            # elif db_field.name == "hospital":
            #    kwargs["queryset"] = related_model.objects.filter(
            #        pk=request.user.hospital_id
            #    )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limita los ManyToMany a objetos del mismo hospital del usuario (si no es superuser).
        Detecta dinámicamente si el modelo relacionado tiene campo 'hospital'.
        """
        if not request.user.is_superuser:
            related_model = db_field.remote_field.model

            # Si el modelo relacionado tiene campo 'hospital', filtramos por hospital del usuario
            if any(f.name == "hospital" for f in related_model._meta.get_fields()):

                kwargs["queryset"] = related_model.objects.filter(hospital=request.user.hospital) # Filtramos por hospital

        return super().formfield_for_manytomany(db_field, request, **kwargs)



