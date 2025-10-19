# decorators.py: decoradores personalizados.

from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


def role_required(*roles):
    """
    Decorador que restringe el acceso a vistas a los usuarios con ciertos roles.
    Ejemplo: @role_required("admin", "microbiologo")
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, "Debes iniciar sesión.")
                return redirect("Base:login")
            if request.user.rol not in roles:
                messages.error(request, "No tienes permiso para acceder a esta sección.")
                return redirect("Base:home")
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
