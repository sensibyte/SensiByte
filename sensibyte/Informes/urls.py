from django.urls import path
from .views import ResultadosResistenciaView, InformePredefinidoResistenciaPDFView

app_name = "Informes"

urlpatterns = [
    path("explorar-resultados/", ResultadosResistenciaView.as_view(), name="informe_dinamico"),
    path("informe-acumulado/", InformePredefinidoResistenciaPDFView.as_view(), name="informe_acumulado"),
]