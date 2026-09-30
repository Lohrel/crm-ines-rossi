"""Painel da página inicial: cada número, a lista para onde ele leva e as consultas ao banco."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apolices.models import Contrato
from beneficiarios.models import Beneficiario
from beneficiarios.tests.fixtures import HOJE, contrato, incluir
from boletos.models import Boleto
from clientes.prazos import quando
from contas.models import Usuario
from contas.painel import Painel, com_sinal, proxima_data
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia

pytestmark = pytest.mark.django_db

# Os quadros que dependem do dia do mês usam um dia fixo.
DIA_15 = date(2026, 9, 15)


def daqui_a(dias: int) -> date:
    return HOJE + timedelta(days=dias)


@pytest.fixture
def colega(db):
    return Usuario.objects.create_user(
        username="bruno", password="senha-forte-de-teste", first_name="Bruno", last_name="Reis"
    )


def pedido(pessoa, plano, etapa="ANA", recebida_em=HOJE, tipo="INC"):
    return Movimentacao.objects.create(
        tipo=tipo,
        beneficiario=pessoa,
        contrato=plano,
        etapa=etapa,
        recebida_em=recebida_em,
        enviada_em=recebida_em,
    )


def boleto(plano, vencimento, **extra):
    return Boleto.objects.create(
        contrato=plano,
        tipo=Boleto.Tipo.ESPECIAL,
        referencia=vencimento.replace(day=1),
        vencimento=vencimento,
        **extra,
    )


def pendencia(cliente, responsavel, prazo, descricao="Cobrar do RH a DPS do João", **extra):
    return Pendencia.objects.create(
        cliente=cliente, responsavel=responsavel, prazo=prazo, descricao=descricao, **extra
    )


def mudar(plano, **campos):
    Contrato.objects.filter(pk=plano.pk).update(**campos)


def ler_todos(painel: Painel) -> None:
    for nome in ("movimentacoes", "boletos", "pendencias", "prazos", "vidas", "renovacoes"):
        getattr(painel, nome)


# ------------------------------------------------------------------
# Contas de datas
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dia", "hoje", "esperada"),
    [
        (25, date(2026, 9, 20), date(2026, 9, 25)),
        (25, date(2026, 9, 25), date(2026, 9, 25)),
        (25, date(2026, 9, 26), date(2026, 10, 25)),
        (5, date(2026, 12, 6), date(2027, 1, 5)),
        # Em meses mais curtos, o último dia do mês.
        (31, date(2026, 9, 10), date(2026, 9, 30)),
        (30, date(2027, 1, 31), date(2027, 2, 28)),
    ],
)
def test_proxima_data_com_o_dia_do_mes(dia, hoje, esperada):
    assert proxima_data(dia, hoje) == esperada


@pytest.mark.parametrize(
    ("dias", "texto"),
    [(-3, "há 3 dias"), (-1, "ontem"), (0, "hoje"), (1, "amanhã"), (20, "em 20 dias")],
)
def test_quando(dias, texto):
    assert quando(dias) == texto


def test_saldo_com_o_sinal_na_frente():
    assert [com_sinal(n) for n in (3, 0, -2)] == ["+3", "0", "−2"]


# ------------------------------------------------------------------
# Quadros
# ------------------------------------------------------------------


def test_movimentacoes_em_aberto_com_as_mais_antigas_primeiro(
    usuario, titular, conjuge, filho, saude, dental
):
    recente = pedido(titular, saude, recebida_em=daqui_a(-3))
    antiga = pedido(conjuge, saude, recebida_em=daqui_a(-10))
    aprovada = pedido(filho, dental, etapa="APR", recebida_em=daqui_a(-20))
    pedido(filho, saude, recebida_em=daqui_a(-1))
    pedido(titular, dental, etapa="CON", recebida_em=daqui_a(-40))
    pedido(conjuge, dental, etapa="REJ", recebida_em=daqui_a(-30))

    quadro = Painel(usuario).movimentacoes
    assert (quadro["total"], quadro["em_analise"], quadro["aprovadas"]) == (4, 3, 1)
    assert [(item["movimentacao"], item["dias"]) for item in quadro["itens"]] == [
        (aprovada, 20),
        (antiga, 10),
        (recente, 3),
    ]


def test_boletos_vencidos_e_dos_proximos_7_dias(usuario, saude):
    vencido = boleto(saude, daqui_a(-3))
    de_hoje = boleto(saude, HOJE)
    no_limite = boleto(saude, daqui_a(7))
    boleto(saude, daqui_a(8))
    boleto(saude, daqui_a(-5), enviado_em=HOJE)
    boleto(saude, daqui_a(-5), cancelado=True)

    quadro = Painel(usuario).boletos
    assert (quadro["total"], quadro["vencidos"], quadro["vencendo"]) == (3, 1, 2)
    assert [(item["registro"], item["prazo"], item["venceu"]) for item in quadro["itens"]] == [
        (vencido, "venceu há 3 dias", True),
        (de_hoje, "vence hoje", False),
        (no_limite, "vence em 7 dias", False),
    ]


def test_pendencias_da_pessoa_logada_e_da_equipe(usuario, colega, pessoa):
    vencida = pendencia(pessoa, usuario, daqui_a(-1))
    no_limite = pendencia(pessoa, usuario, daqui_a(3))
    pendencia(pessoa, usuario, daqui_a(4))
    pendencia(pessoa, usuario, daqui_a(-9), concluida_em=HOJE)
    pendencia(pessoa, colega, daqui_a(-2))
    pendencia(pessoa, colega, daqui_a(1))

    quadro = Painel(usuario).pendencias
    assert (quadro["minhas"], quadro["minhas_vencidas"], quadro["minhas_vencendo"]) == (2, 1, 1)
    assert quadro["minhas_em_aberto"] == 3
    assert (quadro["equipe"], quadro["equipe_vencidas"]) == (4, 2)
    assert [(item["registro"], item["prazo"]) for item in quadro["itens"]] == [
        (vencida, "venceu ontem"),
        (no_limite, "vence em 3 dias"),
    ]


def test_prazos_do_mes(usuario, empresa, seguradora, matriz, saude, dental, vida):
    mudar(saude, dia_fechamento=25)
    mudar(dental, dia_fechamento=10)
    cancelado = contrato(empresa, seguradora, "Saúde", "S-9", [matriz])
    mudar(cancelado, dia_fechamento=5, situacao=Contrato.Situacao.CANCELADO)

    prazos = Painel(usuario, hoje=date(2026, 9, 20)).prazos
    assert [(p["titulo"], p["data"], p["contratos"], p["quando"], p["perto"]) for p in prazos] == [
        ("Fechamento das movimentações", date(2026, 9, 25), 1, "em 5 dias", True),
        ("Envio da planilha do seguro de vida", date(2026, 10, 5), 1, "em 15 dias", False),
        ("Fechamento das movimentações", date(2026, 10, 10), 1, "em 20 dias", False),
    ]
    assert prazos[0]["url"] == reverse("movimentacoes:lista")
    assert prazos[1]["url"] == reverse("movimentacoes:planilha")


def test_prazos_mostram_so_os_proximos_tres_fechamentos(usuario, empresa, seguradora, matriz):
    for numero, dia in enumerate([1, 15, 20, 28, 20]):
        mudar(contrato(empresa, seguradora, "Saúde", f"S-{numero}", [matriz]), dia_fechamento=dia)

    prazos = Painel(usuario, hoje=date(2026, 9, 16)).prazos
    assert [(p["data"], p["contratos"]) for p in prazos] == [
        (date(2026, 9, 20), 2),
        (date(2026, 9, 28), 1),
        (date(2026, 10, 1), 1),
    ]


def test_vidas_de_hoje_e_entradas_e_saidas_do_mes(
    usuario, empresa, seguradora, matriz, filial, saude, dental, titular, conjuge, filho
):
    def pessoa(nome):
        return Beneficiario.objects.create(cliente=empresa, unidade=filial, nome=nome)

    outro_saude = contrato(empresa, seguradora, "Saúde", "S-2", [matriz, filial])
    cancelado = contrato(empresa, seguradora, "Dental", "D-9", [matriz, filial])
    incluir(titular, saude, date(2026, 1, 1))
    incluir(titular, dental, date(2026, 9, 1))
    incluir(conjuge, saude, date(2026, 9, 1))
    incluir(filho, saude, date(2026, 1, 1), exclusao=date(2026, 9, 10))
    # Alteração de plano: sai de um plano de saúde e entra no outro no mesmo dia.
    davi = pessoa("Davi Titular")
    incluir(davi, saude, date(2026, 1, 1), exclusao=date(2026, 9, 1))
    incluir(davi, outro_saude, date(2026, 9, 1))
    incluir(pessoa("Eva Titular"), saude, date(2026, 9, 20))
    incluir(pessoa("Fábio Titular"), dental, date(2026, 10, 1))
    incluir(pessoa("Gil Titular"), cancelado, date(2026, 1, 1))
    mudar(cancelado, situacao=Contrato.Situacao.CANCELADO)

    quadro = Painel(usuario, hoje=DIA_15).vidas
    # Hoje: titular na saúde e no dental, cônjuge e Davi no plano novo (Gil está num cancelado).
    assert (quadro["vidas"], quadro["pessoas"]) == (4, 3)
    # Entram titular no dental, cônjuge e Eva; sai o filho. A troca do Davi não conta.
    assert (quadro["entradas"], quadro["saidas"], quadro["saldo"]) == (3, 1, "+2")
    assert quadro["mes"] == date(2026, 9, 1)


def test_renovacoes_dos_proximos_60_dias(usuario, empresa, seguradora, matriz, saude, dental, vida):
    mudar(saude, data_renovacao=DIA_15 - timedelta(days=1))
    mudar(dental, data_renovacao=DIA_15)
    mudar(vida, data_renovacao=DIA_15 + timedelta(days=60))
    longe = contrato(empresa, seguradora, "Saúde", "S-2", [matriz])
    mudar(longe, data_renovacao=DIA_15 + timedelta(days=61))
    cancelado = contrato(empresa, seguradora, "Saúde", "S-3", [matriz])
    mudar(cancelado, data_renovacao=DIA_15, situacao=Contrato.Situacao.CANCELADO)
    contrato(empresa, seguradora, "Saúde", "S-4", [matriz])

    quadro = Painel(usuario, hoje=DIA_15).renovacoes
    assert (quadro["total"], quadro["passadas"]) == (2, 1)
    assert [(item["contrato"].pk, item["quando"]) for item in quadro["itens"]] == [
        (dental.pk, "hoje"),
        (vida.pk, "em 60 dias"),
    ]


# ------------------------------------------------------------------
# Listas e página
# ------------------------------------------------------------------


def contar(cliente_http, url: str) -> int:
    return cliente_http.get(url).context["paginator"].count


def test_cada_numero_bate_com_a_lista_para_onde_leva(
    logado, usuario, colega, pessoa, titular, conjuge, filho, saude, dental
):
    pedido(titular, saude)
    pedido(conjuge, saude, etapa="APR")
    pedido(filho, dental, etapa="CON")
    boleto(saude, daqui_a(-2))
    boleto(saude, daqui_a(5))
    boleto(saude, daqui_a(20))
    pendencia(pessoa, usuario, daqui_a(-1))
    pendencia(pessoa, usuario, daqui_a(10))
    pendencia(pessoa, colega, daqui_a(2))
    mudar(saude, data_renovacao=daqui_a(-1))
    mudar(dental, data_renovacao=daqui_a(30))

    painel = Painel(usuario)
    movimentacoes, boletos = painel.movimentacoes, painel.boletos
    pendencias, renovacoes = painel.pendencias, painel.renovacoes
    assert contar(logado, movimentacoes["url"]) == movimentacoes["total"] == 2
    assert contar(logado, movimentacoes["url_em_analise"]) == movimentacoes["em_analise"] == 1
    assert contar(logado, movimentacoes["url_aprovadas"]) == movimentacoes["aprovadas"] == 1
    assert contar(logado, boletos["url"]) == boletos["total"] == 2
    assert contar(logado, pendencias["url"]) == pendencias["minhas"] == 1
    assert contar(logado, pendencias["url_minhas_em_aberto"]) == pendencias["minhas_em_aberto"]
    assert contar(logado, pendencias["url_equipe"]) == pendencias["equipe"] == 2
    # A lista de renovações traz também as com a data já passada, que o quadro só conta.
    assert contar(logado, renovacoes["url"]) == renovacoes["total"] + renovacoes["passadas"] == 2


def test_consultas_nao_crescem_com_a_carteira(
    django_assert_num_queries, usuario, colega, pessoa, titular, conjuge, filho, saude, dental
):
    def registros(dias: int, etapa: str, pessoa_do_pedido, plano):
        pedido(pessoa_do_pedido, plano, etapa=etapa, recebida_em=daqui_a(-dias))
        boleto(plano, daqui_a(dias - 5))
        pendencia(pessoa, usuario, daqui_a(dias - 2))
        pendencia(pessoa, colega, daqui_a(dias - 2))

    mudar(saude, dia_fechamento=25, data_renovacao=daqui_a(10))
    incluir(titular, saude)
    registros(1, "ANA", titular, saude)
    with django_assert_num_queries(11):
        ler_todos(Painel(usuario))

    mudar(dental, dia_fechamento=10, data_renovacao=daqui_a(20))
    incluir(titular, dental)
    incluir(conjuge, saude)
    registros(2, "APR", conjuge, saude)
    registros(3, "ANA", filho, dental)
    with django_assert_num_queries(11):
        ler_todos(Painel(usuario))


def test_pagina_inicial_mostra_o_painel(logado, usuario, pessoa, saude, django_assert_num_queries):
    pendencia(pessoa, usuario, daqui_a(-1), descricao="Ligar para o RH sobre a filial nova")
    boleto(saude, HOJE)

    with django_assert_num_queries(13):
        resposta = logado.get(reverse("inicio"))
    pagina = resposta.content.decode()
    assert "Suas pendências" in pagina and "Ligar para o RH sobre a filial nova" in pagina
    assert "Venceu ontem" in pagina and "Vence hoje" in pagina
    minhas = f"{reverse('pendencias:lista')}?responsavel={usuario.pk}&amp;situacao=atencao"
    assert f'href="{minhas}"' in pagina
    # Os atalhos de novo cliente continuam.
    assert reverse("clientes:novo_pf") in pagina and reverse("clientes:nova_empresa") in pagina


def test_pagina_inicial_sem_nada_pendente(logado):
    pagina = logado.get(reverse("inicio")).content.decode()
    assert "Nenhum pedido esperando a operadora." in pagina
    assert "Nenhum boleto vencido nem vencendo nos próximos 7 dias." in pagina
    assert "Nenhuma pendência sua vencida nem vencendo nos próximos 3 dias." in pagina
