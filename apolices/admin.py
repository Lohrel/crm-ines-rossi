from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apolices.models import BemSegurado, Contrato, DocumentoDaSeguradora, Ramo, Seguradora


@admin.register(Ramo)
class RamoAdmin(admin.ModelAdmin):
    list_display = ["nome", "bem_segurado", "ativo"]


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


@admin.register(BemSegurado)
class BemSeguradoAdmin(SimpleHistoryAdmin):
    list_display = ["descricao", "placa", "tipo", "contrato"]
    list_filter = ["tipo"]
    search_fields = ["descricao", "placa", "contrato__numero", "contrato__cliente__nome"]
    list_select_related = ["contrato__seguradora"]


@admin.register(DocumentoDaSeguradora)
class DocumentoDaSeguradoraAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "tipo", "seguradora", "enviado_por", "criado_em"]
    list_filter = ["tipo"]
    readonly_fields = ["nome_original", "enviado_por"]
