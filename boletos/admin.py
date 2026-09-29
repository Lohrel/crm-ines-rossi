from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from boletos.models import Boleto


@admin.register(Boleto)
class BoletoAdmin(SimpleHistoryAdmin):
    list_display = ["contrato", "tipo", "referencia", "vencimento", "enviado_em", "cancelado"]
    list_filter = ["tipo", "cancelado", "fora_do_vencimento"]
    search_fields = ["contrato__cliente__nome", "contrato__numero"]
    list_select_related = ["contrato__cliente", "contrato__seguradora"]
    raw_id_fields = ["contrato", "enviado_para"]
