# widgets.py: widgets personalizados para mostrar en formularios
#
# https://docs.djangoproject.com/en/5.2/ref/forms/widgets/#customizing-widget-instances

from django import forms
import json

class JSONListWidget(forms.Textarea):
    """
    Widget personalizado de Django para editar listas almacenadas en JSONField.
    Extiende el widget de forms.Textarea. Al mostrar convierte listas en varias líneas.
    Al leer datos del formulario, convierte textarea vacío en lista vacía.
    """

    def format_value(self, value) -> str:
        """
        Este metodo convierte el valor del modelo en texto multilínea para el form.
        'value' es el valor del modelo. Parsea el valor como JSON y después a líneas,
        si es None o lista vacía, cadena vacía, devuelve un carácter de texto vacío.
        Si 'value' ya es lista se utiliza directamente.
        """
        if not value:
            return ""

        # Si ya es lista, usamos directamente
        if isinstance(value, list):
            parsed = value
        else:
            try:
                parsed = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return ""

        # json.loads("null") returns None — guard against it
        if not parsed:  # handles None, [], "", 0, etc.
            return ""

        return "\n".join(str(item) for item in parsed)

    def value_from_datadict(self, data, files, name) -> str:  # ← returns str, not list
        """
        Convierte el textarea en un JSON string que forms.JSONField puede parsear.
        Devuelve un JSON string de lista (ej: '["a", "b"]') o '[]' si está vacío.
        """
        raw = data.get(name, "")
        if not raw.strip():
            return "[]"  # JSON string
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return json.dumps(lines)  # ← serialize to JSON string

