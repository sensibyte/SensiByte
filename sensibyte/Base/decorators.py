# decorators.py: decoradores personalizados.

from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

# Decorador de rol de usuario requerido: restringe el acceso a vistas según el rol del usuario activo
# ref: https://medium.com/@blueberry92450/using-functools-wraps-in-python-decorator-952030a70615
def role_required(*roles):
    """
    Decorador que restringe el acceso a vistas a los usuarios con ciertos roles.
    Ejemplo: @role_required("admin", "microbiologo")
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated: # si no está autenticado -> ir a la página de login
                messages.error(request, "Debes iniciar sesión.")
                return redirect("Base:login")

            user_rol = getattr(request.user, "rol", None) # más explícito
            if user_rol not in roles: # si no está en los roles permitidos -> ir a la página de inicio
                messages.error(request, "No tienes permiso para acceder a esta sección.")
                return redirect("Base:home")
            return view_func(request, *args, **kwargs) # si está autenticado y tiene rol correspondiente -> accede a la vista

        return _wrapped_view

    return decorator
