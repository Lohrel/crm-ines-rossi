from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("clientes/", include("clientes.urls")),
    path("contratos/", include("apolices.urls")),
    path("beneficiarios/", include("beneficiarios.urls")),
    path("movimentacoes/", include("movimentacoes.urls")),
    path("boletos/", include("boletos.urls")),
    path("pendencias/", include("pendencias.urls")),
    path("calendario/", include("calendario.urls")),
    path("", include("contas.urls")),
]
