from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apolices.models import Contrato, Ramo, Seguradora


@admin.register(Ramo)
class RamoAdmin(admin.ModelAdmin):
    list_display = ["nome", "ativo"]


@admin.register(Seguradora)
class SeguradoraAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "cnpj", "ativo"]
    search_fields = ["nome"]


@admin.register(Contrato)
class ContratoAdmin(SimpleHistoryAdmin):
    list_display = ["numero", "cliente", "seguradora", "ramo", "situacao", "dia_vencimento"]
    list_filter = ["situacao", "ramo", "seguradora", "corretora_envia_boleto"]
    search_fields = ["numero", "cliente__nome", "produto"]
    filter_horizontal = ["unidades"]
