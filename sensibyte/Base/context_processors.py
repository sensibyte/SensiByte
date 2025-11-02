# Fuente: context_processors: https://diegoamorin.com/context-processors-en-django/
# Para pasar un contexto específico a las plantillas. En este caso vamos a pasar el
# año, que se puede filtrar en el template a partir del datetime de ahora mismo.
# Se lo pasamos a la variable llamada 'now'

from django.utils import timezone

def get_current_year(request):
    return {
        "now": timezone.now()
    }
