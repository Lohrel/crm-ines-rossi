from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from contas.painel import Painel


class InicioView(TemplateView):
    """Página inicial: o painel com o que precisa de atenção hoje e os atalhos de novo cliente."""

    template_name = "contas/inicio.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "painel": Painel(self.request.user)}


@require_GET
@login_not_required
def saude(request: HttpRequest) -> JsonResponse:
    """Verificação usada pelo Docker para saber se o sistema e o banco estão no ar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
