# views.py: definiciones de las vistas de la aplicación.
# Las vistas contienen la lógica de negocio que conecta los Modelos con los Templates, procesan las peticiones HTTP
# y devuelven las respuestas adecuadas (HTML, JSON, etc.). Son una pieza fundamental del paradigma de programación
# orientada a objetos MVT, variante del patrón MVC en el que la Vista es el Template y el Controller es el View.
#
# En Django existen distintas formas de declarar las vistas, pero habitualmente se utilizan:
#
# Function-Based Views - Vistas basadas en funciones que admiten un request como argumento
# Class-Based Views - Vistas basadas en Clases. Aceptan un Modelo que puede llevarse al contexto para las operaciones lógicas
#
# Otras más simples son TemplateView o RedirectView, que permiten un control total sobreescribiendo sus métodos.
# También existen vistas incluidas por defecto para Autenticación en django.contrib.auth.views
#
# https://docs.djangoproject.com/en/5.2/topics/http/views/
# https://docs.djangoproject.com/en/5.2/topics/class-based-views/ -> Class-Based Views

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView

class HomeView(LoginRequiredMixin, TemplateView):
    """ Vista de la página de inicio. Se le pasa al contexto el hospital y la fecha actual.
    Hereda de TemplateView, que acepta un template como argumento para su construcción.
    ref: https://docs.djangoproject.com/en/5.2/topics/class-based-views/generic-display/#adding-extra-context"""
    template_name = "Base/base.html" # El template base. Posee todos los bloques

    def get_context_data(self, **kwargs):
        """Método de inicialización del contexto de la vista"""
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_superuser:
            context['hospital'] = None # Si es el superusuario no tiene hospital asociado
        else:
            # Si no es superusuario tiene un atributo hospital en su instancia
            context['hospital'] = getattr(user, 'hospital', None) # variable hospital pasada al contexto
        return context

class LogView(LoginView):
    """ Vista de la página de login. Se le pasa la fecha actual al contexto"""
    template_name = 'Base/login.html' # template para su construcción
