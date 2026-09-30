"""Itens do menu principal, com o da página aberta marcado."""

from django.urls import reverse

# Texto, endereço e os apps cujas páginas ficam sob o item: os beneficiários (e a planilha
# do seguro de vida) ficam em Clientes, e as seguradoras em Contratos.
ITENS = [
    ("Clientes", "clientes:lista", {"clientes", "beneficiarios"}),
    ("Contratos", "apolices:contratos", {"apolices"}),
    ("Movimentações", "movimentacoes:lista", {"movimentacoes"}),
    ("Boletos", "boletos:lista", {"boletos"}),
    ("Pendências", "pendencias:lista", {"pendencias"}),
]


def menu_principal(request) -> dict:
    secao = request.resolver_match.app_name if request.resolver_match else ""
    return {
        "menu_principal": [
            {"texto": texto, "url": reverse(nome), "aberto": secao in apps}
            for texto, nome, apps in ITENS
        ]
    }
