from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from pendencias.models import Pendencia


@admin.register(Pendencia)
class PendenciaAdmin(SimpleHistoryAdmin):
    list_display = ["descricao", "cliente", "unidade", "responsavel", "prazo", "concluida_em"]
    list_filter = ["responsavel"]
    search_fields = ["descricao", "cliente__nome"]
    list_select_related = ["cliente", "unidade", "responsavel"]
    raw_id_fields = ["cliente", "unidade", "contrato", "movimentacao"]
