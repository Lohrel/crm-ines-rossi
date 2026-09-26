from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from clientes.models import Cliente, Contato, Unidade


class UnidadeInline(admin.TabularInline):
    model = Unidade
    extra = 0
    fields = ["cnpj", "razao_social", "nome_fantasia", "matriz", "ativo"]


@admin.register(Cliente)
class ClienteAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "tipo", "cpf", "ativo"]
    list_filter = ["tipo", "ativo"]
    search_fields = ["nome", "cpf", "unidades__cnpj", "unidades__razao_social"]
    inlines = [UnidadeInline]


@admin.register(Contato)
class ContatoAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "cargo", "cliente", "principal"]
    search_fields = ["nome", "cliente__nome", "unidades__razao_social"]
    filter_horizontal = ["unidades"]
