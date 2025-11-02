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

    def format_value(self, value)-> str:
        """
        Este metodo convierte el valor del modelo en texto multilínea para el form.
        'value' es el valor del modelo. Parsea el valor como JSON y después a líneas,
        si es None o lista vacía, cadena vacía, devuelve un carácter de texto vacío.
        Si 'value' ya es lista se utiliza directamente.
        """
        if not value:
            return ""  # maneja None, [], "" etc.

        # Si ya es lista, usamos directamente
        if isinstance(value, list):
            parsed = value
        else:
            try:
                parsed = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                parsed = []

        return "\n".join(str(item) for item in parsed)

    def value_from_datadict(self, data, files, name)-> list[str]:
        """
        Este metodo convierte el valor enviado desde el formulario a la estructura
        de listas de Python que espera el modelo con su campo JSONField. Los argumentos son:
        - data (dict): diccionario con los datos enviados en el POST
        - files (dict): (no usado pero necesario para la sobreescritura)
        - name (str): nombre del campo en el formulario
        Devuelve una lista con una cadena por cada línea no vacía del textarea o una lista vacía
        en el caso de campo vacío en el formulario.
        Nota: el widget no valida JSON, sólo devuelve la lista de strings preparada para que
        el campo JSONField lo procese. La validación JSON la realiza el field (forms.JSONField).
        Para evitar que llegue None al modelo y a la base de datos, se necesita
        un método clean_... en el formulario que devuelva siempre una lista válida.
        """
        raw = data.get(name, "")
        if not raw.strip():
            return []  # devuelve lista vacía
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines

