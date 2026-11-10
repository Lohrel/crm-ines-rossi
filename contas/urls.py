from django.contrib.auth import views as auth_views
from django.urls import path

from contas.views import BuscaView, InicioView, saude

urlpatterns = [
    path("", InicioView.as_view(), name="inicio"),
    path("buscar/", BuscaView.as_view(), name="buscar"),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("saude/", saude, name="saude"),
]
