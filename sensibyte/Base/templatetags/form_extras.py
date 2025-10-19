from django import template

register = template.Library()


@register.filter(name='add_class')
def add_class(field, css_class):
    """Añade un filtro 'add_class' para usar en los templates.
    De esta forma podemos añadir directamente en el template la clase que queramos a
    los campos de un formulario, por ejemplo: {{ form.nombre|add_class:"form-control" }} """
    return field.as_widget(attrs={"class": css_class})
