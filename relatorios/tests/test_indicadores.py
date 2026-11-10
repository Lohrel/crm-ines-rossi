"""Indicadores: prazos, rejeições e volume de cada mês, na tela e em Excel."""

from datetime import date, datetime
from io import BytesIO

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from beneficiarios.models import Beneficiario, Vinculo
from beneficiarios.tests.fixtures import contrato, incluir
from boletos.models import Boleto
from clientes.models import Cliente
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia
from relatorios.excel import TIPO_XLSX
from relatorios.indicadores import calcular, prazo_de_fechamento

pytestmark = pytest.mark.django_db

INDICADORES = reverse("relatorios:indicadores")
HOJE = date(2026, 11, 10)
SETEMBRO, OUTUBRO, NOVEMBRO = date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)


def movimentacao(pessoa, plano, recebida, enviada, etapa="ANA", **campos):
    return Movimentacao.objects.create(
        tipo="INC",
        beneficiario=pessoa,
        contrato=plano,
        recebida_em=recebida,
        enviada_em=enviada,
        etapa=etapa,
        **campos,
    )


def do_mes(resultado, mes):
    return next(item for item in resultado.meses if item.mes == mes)


def test_prazo_de_fechamento_e_o_proximo_fechamento_do_contrato():
    assert prazo_de_fechamento(date(2026, 10, 3), 25) == date(2026, 10, 25)
    assert prazo_de_fechamento(date(2026, 10, 25), 25) == date(2026, 10, 25)
    # Depois do fechamento, o pedido tem até o fechamento do mês seguinte.
    assert prazo_de_fechamento(date(2026, 10, 26), 25) == date(2026, 11, 25)
    assert prazo_de_fechamento(date(2026, 12, 28), 25) == date(2027, 1, 25)
    # Mês mais curto que o dia de fechamento: vale o último dia.
    assert prazo_de_fechamento(date(2027, 2, 10), 31) == date(2027, 2, 28)


def test_movimentacoes_envio_fechamento_rejeicao_e_carteirinha(
    saude, dental, titular, conjuge, filho
):
    saude.dia_fechamento = 25
    saude.save()
    # Outubro, na saúde: uma no prazo (2 dias), uma depois do fechamento (24 dias) e rejeitada.
    movimentacao(
        titular,
        saude,
        date(2026, 10, 5),
        date(2026, 10, 7),
        etapa="CON",
        carteirinha_enviada_em=date(2026, 10, 17),
    )
    movimentacao(
        conjuge, saude, date(2026, 10, 4), date(2026, 10, 28), etapa="REJ", motivo_rejeicao="RAS"
    )
    # Cancelada: fica de fora. Dental não tem fechamento: fica fora só da conta do prazo.
    movimentacao(filho, saude, date(2026, 10, 6), date(2026, 10, 6), etapa="CAN")
    movimentacao(titular, dental, date(2026, 10, 10), date(2026, 10, 14))
    # Recebida depois do fechamento de outubro: o prazo é o de novembro.
    movimentacao(filho, saude, date(2026, 10, 27), date(2026, 11, 3), etapa="APR")

    resultado = calcular(SETEMBRO, NOVEMBRO, hoje=HOJE)

    outubro = do_mes(resultado, OUTUBRO).numeros
    assert outubro.movimentacoes == 4
    assert outubro.media_ate_o_envio == 9.2  # (2 + 24 + 4 + 7) / 4
    assert (outubro.ate_o_fechamento, outubro.com_fechamento) == (2, 3)
    assert outubro.pct_ate_o_fechamento == 67
    assert (outubro.rejeitadas, outubro.decididas) == (1, 3)
    assert outubro.pct_rejeitadas == 33
    assert outubro.media_ate_a_carteirinha == 10
    assert resultado.motivos == [("Rasura ou erro no formulário", 1)]
    vazio = do_mes(resultado, SETEMBRO).numeros
    assert vazio.movimentacoes == 0
    assert vazio.media_ate_o_envio is None and vazio.pct_ate_o_fechamento is None
    assert resultado.total.movimentacoes == 4


def test_pendencias_no_prazo_com_atraso_e_vencidas(empresa, usuario):
    def pendencia(prazo, concluida=None):
        return Pendencia.objects.create(
            cliente=empresa,
            descricao="Cobrar a ficha",
            responsavel=usuario,
            prazo=prazo,
            concluida_em=concluida,
        )

    pendencia(date(2026, 10, 10), date(2026, 10, 10))
    pendencia(date(2026, 10, 12), date(2026, 10, 9))
    pendencia(date(2026, 10, 15), date(2026, 10, 20))
    pendencia(date(2026, 10, 30))  # Venceu e continua em aberto.
    pendencia(date(2026, 11, 20))  # Em aberto, ainda dentro do prazo.
    pendencia(date(2026, 11, 5), date(2026, 11, 4))

    resultado = calcular(OUTUBRO, NOVEMBRO, hoje=HOJE)

    outubro = do_mes(resultado, OUTUBRO).numeros
    assert outubro.pendencias == 4
    assert (outubro.pendencias_no_prazo, outubro.pendencias_com_atraso) == (2, 1)
    assert outubro.pendencias_vencidas == 1
    assert outubro.pct_pendencias_no_prazo == 50
    novembro = do_mes(resultado, NOVEMBRO).numeros
    # A que ainda está dentro do prazo não pesa na porcentagem.
    assert (novembro.pendencias, novembro.pendencias_em_dia) == (2, 1)
    assert novembro.pct_pendencias_no_prazo == 100


def test_boletos_ate_o_vencimento_depois_e_vencidos(saude, dental):
    def boleto(plano, referencia, enviado=None, **campos):
        return Boleto.objects.create(
            contrato=plano, referencia=referencia, enviado_em=enviado, **campos
        )

    # Os contratos dos testes vencem no dia 10.
    boleto(saude, OUTUBRO, date(2026, 10, 8))
    boleto(dental, OUTUBRO, date(2026, 10, 13))
    boleto(saude, OUTUBRO, tipo="COP", vencimento=date(2026, 10, 20))  # Vencido, sem envio.
    boleto(dental, OUTUBRO, date(2026, 10, 1), tipo="ESP", cancelado=True)  # Fica de fora.
    boleto(saude, NOVEMBRO, tipo="COP", vencimento=date(2026, 11, 25))  # Ainda a enviar.

    resultado = calcular(OUTUBRO, NOVEMBRO, hoje=HOJE)

    outubro = do_mes(resultado, OUTUBRO).numeros
    assert outubro.boletos == 3
    assert (outubro.boletos_ate_o_vencimento, outubro.boletos_depois) == (1, 1)
    assert outubro.boletos_vencidos == 1
    assert outubro.pct_boletos_ate_o_vencimento == 33
    novembro = do_mes(resultado, NOVEMBRO).numeros
    assert (novembro.boletos, novembro.boletos_a_enviar) == (1, 1)
    assert novembro.pct_boletos_ate_o_vencimento is None


def test_cadastros_do_mes_e_vidas_no_fim_do_mes(empresa, saude, dental, titular, conjuge):
    def criado_em(modelo, pk, quando):
        modelo.objects.filter(pk=pk).update(criado_em=timezone.make_aware(quando))

    criado_em(Cliente, empresa.pk, datetime(2026, 9, 30, 23, 30))
    criado_em(Beneficiario, titular.pk, datetime(2026, 10, 1, 0, 30))
    criado_em(Beneficiario, conjuge.pk, datetime(2026, 10, 20, 9))
    for plano in (saude, dental):
        criado_em(type(plano), plano.pk, datetime(2026, 11, 3, 9))
    incluir(titular, saude, date(2026, 9, 15))
    incluir(titular, dental, date(2026, 10, 1), date(2026, 10, 31))
    incluir(conjuge, saude, date(2026, 11, 9))
    # Ainda não começou.
    Vinculo.objects.create(beneficiario=titular, contrato=dental, data_inclusao=date(2026, 11, 20))

    resultado = calcular(SETEMBRO, date(2026, 12, 1), hoje=HOJE)

    setembro, outubro, novembro, dezembro = resultado.meses
    assert (setembro.numeros.clientes_novos, setembro.numeros.pessoas_novas) == (1, 0)
    assert (outubro.numeros.clientes_novos, outubro.numeros.pessoas_novas) == (0, 2)
    assert novembro.numeros.contratos_novos == 2
    # Outubro: o dental saiu no dia 31. Novembro vale até hoje; dezembro ainda não começou.
    assert [mes.vidas for mes in resultado.meses] == [1, 1, 2, 0]
    assert resultado.total.pessoas_novas == 2
    assert dezembro.numeros.movimentacoes == 0


def test_pagina_abre_nos_ultimos_seis_meses_sem_nada_registrado(logado):
    resposta = logado.get(INDICADORES)
    assert resposta.status_code == 200
    resultado = resposta.context["indicadores"]
    assert len(resultado.meses) == 6
    assert resultado.meses[-1].mes == date.today().replace(day=1)
    assert "Nada registrado" in resposta.content.decode()
    abertos = [item["texto"] for item in resposta.context["menu_principal"] if item["aberto"]]
    assert abertos == ["Relatórios"]
    assert f'href="{INDICADORES}"' in logado.get(reverse("relatorios:indice")).content.decode()


def test_pagina_exige_login(client):
    resposta = client.get(INDICADORES)
    assert resposta.status_code == 302 and "/entrar/" in resposta.url


def test_pagina_mostra_os_numeros_sem_dados_pessoais(logado, saude, titular):
    saude.dia_fechamento = 25
    saude.save()
    movimentacao(titular, saude, date(2026, 10, 5), date(2026, 10, 7))

    resposta = logado.get(INDICADORES, {"de": "10/2026", "ate": "10/2026"})

    pagina = resposta.content.decode()
    assert resposta.context["indicadores"].total.pct_ate_o_fechamento == 100
    assert "100%" in pagina and "1 de 1" in pagina
    # O nome da empresa só aparece na lista do filtro; o das pessoas, em lugar nenhum.
    assert titular.nome not in pagina and pagina.count(str(saude.cliente)) == 1


@pytest.mark.parametrize(
    ("filtro", "erro"),
    [
        ({"de": "11/2026", "ate": "10/2026"}, "Escolha um mês igual ou depois do primeiro."),
        ({"de": "01/2020", "ate": "10/2026"}, "Escolha até 36 meses de uma vez."),
        ({"de": "13/2026", "ate": "10/2026"}, "Mês inválido"),
    ],
)
def test_filtro_invalido_mostra_o_erro(logado, filtro, erro):
    resposta = logado.get(INDICADORES, filtro)
    assert resposta.status_code == 200
    assert resposta.context["indicadores"] is None
    assert erro in resposta.content.decode()
    # Com o filtro errado, o botão do Excel volta para a tela, com o mesmo aviso.
    assert erro in logado.get(INDICADORES, {**filtro, "formato": "excel"}).content.decode()


def test_excel_tem_uma_linha_por_mes_e_o_total(logado, saude, titular):
    saude.dia_fechamento = 25
    saude.save()
    movimentacao(titular, saude, date(2026, 10, 5), date(2026, 10, 8))

    resposta = logado.get(INDICADORES, {"de": "09/2026", "ate": "10/2026", "formato": "excel"})

    assert resposta["Content-Type"] == TIPO_XLSX
    aba = load_workbook(BytesIO(b"".join(resposta.streaming_content))).active
    assert aba["A1"].value == "Indicadores · 09/2026 a 10/2026"
    linhas = list(aba.iter_rows(min_row=2, values_only=True))
    assert len(linhas[0]) == 20 and linhas[0][:3] == (
        "Mês",
        "Movimentações recebidas",
        "Dias até o envio (média)",
    )
    assert [linha[0] for linha in linhas[1:]] == ["09/2026", "10/2026", "Total"]
    assert linhas[1][1:3] == (0, None)
    assert linhas[2][1:5] == (1, 3, 1, 1)
    assert linhas[3][1] == 1 and linhas[3][-1] is None


def test_numero_de_consultas_nao_cresce_com_os_dados(logado, saude, dental, titular, conjuge):
    def consultas() -> int:
        with CaptureQueriesContext(connection) as capturadas:
            logado.get(INDICADORES, {"de": "01/2026", "ate": "12/2026"})
        return len(capturadas.captured_queries)

    antes = consultas()
    movimentacao(titular, saude, date(2026, 10, 5), date(2026, 10, 7))
    movimentacao(conjuge, saude, date(2026, 10, 5), date(2026, 10, 7))
    movimentacao(titular, dental, date(2026, 9, 5), date(2026, 9, 7))
    Boleto.objects.create(contrato=saude, referencia=OUTUBRO)
    Boleto.objects.create(contrato=dental, referencia=SETEMBRO)
    assert consultas() == antes


# ------------------------------------------------------------------
# Relatório por empresa
# ------------------------------------------------------------------


@pytest.fixture
def duas_empresas(empresa, pessoa, seguradora, saude, titular, usuario):
    """A empresa tem uma movimentação, uma pendência, um boleto e uma vida; a pessoa física,
    uma pendência e um boleto."""
    individual = contrato(pessoa, seguradora, "Saúde", "I-1", [])
    saude.dia_fechamento = 25
    saude.save()
    movimentacao(titular, saude, date(2026, 10, 5), date(2026, 10, 7))
    incluir(titular, saude, date(2026, 10, 1))
    for cliente in (empresa, pessoa):
        Pendencia.objects.create(
            cliente=cliente,
            descricao="Cobrar a ficha",
            responsavel=usuario,
            prazo=date(2026, 10, 10),
            concluida_em=date(2026, 10, 9),
        )
    Boleto.objects.create(contrato=saude, referencia=OUTUBRO, enviado_em=date(2026, 10, 8))
    Boleto.objects.create(contrato=individual, referencia=OUTUBRO)
    return empresa, pessoa


def test_relatorio_por_empresa_conta_so_o_que_e_dela(duas_empresas):
    empresa, pessoa = duas_empresas

    geral = calcular(OUTUBRO, OUTUBRO, hoje=HOJE)
    da_empresa = calcular(OUTUBRO, OUTUBRO, empresa, hoje=HOJE)
    da_pessoa = calcular(OUTUBRO, OUTUBRO, pessoa, hoje=HOJE)

    def numeros(resultado):
        total = resultado.total
        return (total.movimentacoes, total.pendencias, total.boletos, resultado.meses[0].vidas)

    assert numeros(geral) == (1, 2, 2, 1)
    assert numeros(da_empresa) == (1, 1, 1, 1)
    assert numeros(da_pessoa) == (0, 1, 1, 0)
    assert da_empresa.total.pct_boletos_ate_o_vencimento == 100
    assert da_pessoa.total.boletos_vencidos == 1


def test_cadastros_do_relatorio_por_empresa(duas_empresas):
    empresa, pessoa = duas_empresas
    mes = date.today().replace(day=1)

    geral = calcular(mes, mes).total
    da_empresa = calcular(mes, mes, empresa).total

    assert (geral.clientes_novos, geral.pessoas_novas, geral.contratos_novos) == (2, 1, 2)
    assert (da_empresa.clientes_novos, da_empresa.pessoas_novas) == (1, 1)
    assert da_empresa.contratos_novos == 1


def test_pagina_e_excel_do_relatorio_por_empresa(logado, duas_empresas):
    empresa, pessoa = duas_empresas
    filtro = {"de": "10/2026", "ate": "10/2026", "cliente": empresa.pk}

    resposta = logado.get(INDICADORES, filtro)

    pagina = resposta.content.decode()
    assert resposta.context["indicadores"].total.pendencias == 1
    assert f"<strong>{empresa}</strong>" in pagina
    assert "Clientes cadastrados" not in pagina
    geral = logado.get(INDICADORES, {"de": "10/2026", "ate": "10/2026"}).content.decode()
    assert "<strong>Relatório geral</strong>" in geral and "Clientes cadastrados" in geral

    excel = logado.get(INDICADORES, {**filtro, "formato": "excel"})
    assert "indicadores-" in excel["Content-Disposition"]
    aba = load_workbook(BytesIO(b"".join(excel.streaming_content))).active
    assert aba["A1"].value == f"Indicadores · 10/2026 a 10/2026 · {empresa}"
    assert aba["I3"].value == 1  # Pendências com prazo no mês.
