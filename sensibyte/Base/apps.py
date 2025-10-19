# Configuración a nivel de Aplicación.

from django.apps import AppConfig
from django.db.utils import OperationalError


class BaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Base'  # referencia para las llamadas Base:

    # Creación del objeto de Sexo desconocido, código X
    def ready(self):
        from .models import Sexo
        try:
            if not Sexo.objects.filter(codigo__iexact="X").exists():
                Sexo.objects.create(
                    codigo="X",
                    descripcion="Desconocido"
                )
        except OperationalError:
            # Puede fallar si aún no hay tablas (durante migrate)
            pass
