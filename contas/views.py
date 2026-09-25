from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView


class InicioView(TemplateView):
    """Página inicial exibida após o login."""

    template_name = "contas/inicio.html"


@require_GET
@login_not_required
def saude(request: HttpRequest) -> JsonResponse:
    """Verificação usada pelo Docker para saber se o sistema e o banco estão no ar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
