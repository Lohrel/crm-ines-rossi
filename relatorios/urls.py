from django.urls import path

from relatorios import views

app_name = "relatorios"

urlpatterns = [
    path("", views.IndiceView.as_view(), name="indice"),
    path("vidas/", views.VidasView.as_view(), name="vidas"),
    path("inclusoes/", views.MovimentacoesView.as_view(), name="movimentacoes"),
    path("apolices/", views.ApolicesView.as_view(), name="apolices"),
]
