from django.urls import path

from pendencias import views

app_name = "pendencias"

urlpatterns = [
    path("", views.PendenciaListView.as_view(), name="lista"),
    path("nova/", views.PendenciaCreateView.as_view(), name="nova"),
    path("nova/cliente/", views.EscolherClienteView.as_view(), name="escolher_cliente"),
    path("<int:pk>/", views.PendenciaDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.PendenciaUpdateView.as_view(), name="editar"),
    path("<int:pk>/concluir/", views.ConcluirView.as_view(), name="concluir"),
    path("<int:pk>/reabrir/", views.ReabrirView.as_view(), name="reabrir"),
]
