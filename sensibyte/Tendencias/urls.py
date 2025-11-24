from django.urls import path
from .views import reinterpretar_resultados, vista_tendencias_regresion, get_antibioticos, get_mec_resistencia, get_sub_mecanismos

app_name = "Tendencias"

urlpatterns = [
    path("reinterpretar-resultados/", reinterpretar_resultados, name="reinterpretar_resultados"),
    path("analisis-tendencias/", vista_tendencias_regresion, name="analisis_tendencias"),

    # JSONResponse para AJAX
    path("ajax/get-antibioticos/", get_antibioticos, name="get-antibioticos"),
    path("ajax/get-mecanismos/", get_mec_resistencia, name="get-mec-resistencia"),
    path("ajax/get-subtipos/", get_sub_mecanismos, name="get-sub-mec-resistencia"),
]