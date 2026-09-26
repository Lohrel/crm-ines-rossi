from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from beneficiarios.models import Anexo, Beneficiario, Vinculo


class VinculoInline(admin.TabularInline):
    model = Vinculo
    extra = 0
    fields = ["contrato", "carteirinha", "data_inclusao", "data_exclusao"]


@admin.register(Beneficiario)
class BeneficiarioAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "cliente", "titular", "unidade"]
    search_fields = ["nome", "cpf", "matricula", "cliente__nome"]
    list_select_related = ["cliente", "titular", "unidade"]
    inlines = [VinculoInline]


@admin.register(Anexo)
class AnexoAdmin(SimpleHistoryAdmin):
    # O arquivo não é editável aqui: é baixado só pela tela do beneficiário, com login.
    list_display = ["beneficiario", "tipo", "nome_original", "criado_em", "enviado_por"]
    exclude = ["arquivo"]
    readonly_fields = ["nome_original", "enviado_por"]
    search_fields = ["beneficiario__nome", "descricao"]
