from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from movimentacoes.models import Movimentacao


@admin.register(Movimentacao)
class MovimentacaoAdmin(SimpleHistoryAdmin):
    list_display = ["beneficiario", "tipo", "contrato", "etapa", "vigencia", "cliente"]
    list_filter = ["tipo", "etapa"]
    search_fields = ["beneficiario__nome", "carteirinha", "cliente__nome"]
    list_select_related = ["beneficiario", "contrato__seguradora", "cliente"]
    raw_id_fields = ["beneficiario", "contrato", "solicitante", "origem", "vinculo"]
