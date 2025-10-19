# widgets.py: widgets personalizados para mostrar en formularios
#
# https://docs.djangoproject.com/en/5.2/ref/forms/widgets/#customizing-widget-instances

from django import forms
import json

class JSONListWidget(forms.Textarea):
    """
    Widget personalizado de Django para manejar listas almacenadas en JSONField.
    Extiende el widget de forms.Textarea. Permite mostrar y editar listas de cadenas
    o valores simples en un formulario como un 'textarea' donde cada elemento de la
    lista aparece en una línea separada.
    Al mostrar el formulario convierte la lista en múltiples líneas, mientras que al
    enviar el formulario, convierte las líneas en una lista para guardar en el modelo
    """
    def format_value(self, value):
        """
        Este metodo convierte el valor del modelo en el formato del formulario.
        'value' es el valor del modelo. Parsea el valor como JSON y después a líneas,
        si es None devuelve un carácter de texto vacío.
        Devuelve una representación en varias líneas del valor para el textarea o carácter vacío
        """
        if value is None:
            return ""
        parsed = json.loads(value) # parseo del JSON
        return "\n".join(str(item) for item in parsed) # texto multilínea con un elemento por línea

    def value_from_datadict(self, data, files, name):
        """
        Este metodo convierte el valor enviado desde el formulario a la estructura
        de listas que espera el modelo con su campo JSONField. Los argumentos son:
        - data (dict): diccionario con los datos enviados en el POST
        - files (dict): (no usado pero necesario para la sobreescritura)
        - name (str): nombre del campo en el formulario
        Devuelve una lista con una cadena por cada línea no vacía del textarea
        """
        raw = data.get(name, '')
        if not raw:
            return []
        lines = [line.strip() for line in raw.splitlines() if line.strip()] # lista de cadenas por línea no vacía
        return lines