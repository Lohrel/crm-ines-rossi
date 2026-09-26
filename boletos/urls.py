from django.urls import path

from boletos import views

app_name = "boletos"

urlpatterns = [
    path("", views.BoletoListView.as_view(), name="lista"),
    path("novo/", views.BoletoCreateView.as_view(), name="novo"),
    path("gerar/", views.GerarMensalidadesView.as_view(), name="gerar"),
    path("<int:pk>/", views.BoletoDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.BoletoUpdateView.as_view(), name="editar"),
    path("<int:pk>/envio/", views.RegistrarEnvioView.as_view(), name="registrar_envio"),
    path("<int:pk>/enviado-hoje/", views.EnviadoHojeView.as_view(), name="enviado_hoje"),
]
