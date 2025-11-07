from django.urls import path
from .views import CargarAntibiogramaView, ListarRegistrosView, RegistroDetailView, RegistroUpdateView, RegistroDeleteView
from .views import eliminar_registros_batch, editar_mecanismos_resistencia, editar_resultados_antibiotico, search_antibiotics

app_name = "CRUD"

urlpatterns = [
    path("upload/", CargarAntibiogramaView.as_view(), name="cargar_antibiograma"),
    path("registros/", ListarRegistrosView.as_view(), name="listar_registros"),
    path("registro/<int:pk>/ver/", RegistroDetailView.as_view(), name="registro_ver"),
    path("registro/<int:pk>/editar/", RegistroUpdateView.as_view(), name="registro_editar"),
    path("registro/<int:aislado_id>/editar-antibioticos/", editar_resultados_antibiotico, name="editar_resultados_antibiotico"),
    path("registro/<int:aislado_id>/editar-mecanismos/", editar_mecanismos_resistencia, name="editar_mecanismos_resistencia"),
    path("registro/<int:pk>/eliminar/", RegistroDeleteView.as_view(), name="registro_eliminar"),
    path("registros/eliminar/", eliminar_registros_batch, name="registro_batch_delete"),

    path("ajax/antibioticos/", search_antibiotics, name="buscar_antibioticos"),
]