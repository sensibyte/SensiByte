# urls.py: configuraciones del esquema de rutas de la aplicación asociado a las distintas vistas.
# Pueden ser establecidas a nivel de aplicación, como hacemos con este urls.py propio. Para eso hay que definir la
# aplicación que sirve a las llamadas "App:ruta" en app_name e incorporarlas en el urls.py del proyecto a través del
# metodo django.urls.include.
# Cada ruta se puede definir con el metodo django.urls.path que permite asociarle un nombre único para facilitar
# su propio acceso en el código de la aplicación (por ejemplo: redirect("nombre"), {% url "nombre" %}, reverse("nombre")...
#
# https://docs.djangoproject.com/en/5.2/topics/http/urls/
from django.urls import path
from .views import HomeView, LogView
from django.contrib.auth import views as auth_views

app_name = 'Base'

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('login/', LogView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='Base:login'), name='logout'),
]