"""Vários planos no mesmo contrato (ex.: TNPQ e TNP4 na mesma apólice), com dados fictícios."""

from datetime import date
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from openpyxl import load_workbook

from apolices.forms import PlanoDoContratoField
from apolices.models import Plano
from beneficiarios.forms import VinculoForm
from beneficiarios.models import Vinculo
from beneficiarios.tests.fixtures import incluir
from movimentacoes.forms import MovimentacaoForm
from movimentacoes.importacao import ATUALIZAR, IMPORTAR, PROBLEMA
from movimentacoes.models import Etapa, Movimentacao
from movimentacoes.planilha import PlanilhaDoMes
from movimentacoes.tests.test_alteracao_de_plano import plano as contrato_com_produto
from movimentacoes.tests.test_importacao import (
    ALTERACOES,
    DIGITADA,
    OUTUBRO,
    aba_unimed,
    importar,
    na_unimed,
    situacoes,
)

pytestmark = pytest.mark.django_db

INICIO = date(2026, 1, 1)


@pytest.fixture
def apolice(empresa, seguradora, matriz, filial):
    """Uma apólice de saúde com dois planos, como TNPQ e TNP4."""
    return contrato_com_produto(empresa, seguradora, "B-900", "TNPQ / TNP4", [matriz, filial])


@pytest.fixture
def tnpq(apolice):
    return Plano.objects.create(contrato=apolice, nome="TNPQ")


@pytest.fixture
def tnp4(apolice):
    return Plano.objects.create(contrato=apolice, nome="TNP4")


def no_plano(pessoa, plano, inclusao=INICIO):
    vinculo = Vinculo(
        beneficiario=pessoa, contrato=plano.contrato, plano=plano, data_inclusao=inclusao
    )
    vinculo.full_clean()
    vinculo.save()
    return vinculo


def pedido(pessoa, contrato, tipo="INC", **extra):
    movimentacao = Movimentacao(
        tipo=tipo,
        cliente=pessoa.cliente,
        beneficiario=pessoa,
        contrato=contrato,
        enviada_em=extra.pop("enviada_em", date.today()),
        vigencia=extra.pop("vigencia", OUTUBRO.date()),
        **extra,
    )
    movimentacao.full_clean()
    movimentacao.save()
    return movimentacao


def planos_de(pessoa) -> list[tuple]:
    return list(
        pessoa.vinculos.order_by("data_inclusao", "pk").values_list(
            "plano__nome", "data_inclusao", "data_exclusao"
        )
    )


# ------------------------------------------------------------------
# Planos do contrato
# ------------------------------------------------------------------


def test_contrato_sem_planos_continua_como_antes(apolice, titular):
    vinculo = incluir(titular, apolice)
    assert not apolice.tem_planos and not vinculo.falta_o_plano
    assert vinculo.nome_do_plano == "TNPQ / TNP4"


def test_cadastrar_planos_pela_tela(logado, apolice):
    url = reverse("apolices:novo_plano", args=[apolice.pk])
    resposta = logado.post(url, {"nome": "  TNPQ "})
    assert resposta.status_code == 302
    assert list(apolice.planos.values_list("nome", flat=True)) == ["TNPQ"]
    # O mesmo nome, com outras maiúsculas, não entra de novo.
    resposta = logado.post(url, {"nome": "tnpq"})
    assert "já tem um plano com este nome" in resposta.content.decode()
    assert apolice.planos.count() == 1


def test_plano_que_deixou_de_ser_oferecido(logado, apolice, tnpq, tnp4, titular):
    no_plano(titular, tnpq)
    resposta = logado.post(
        reverse("apolices:editar_plano", args=[tnpq.pk]), {"nome": "TNPQ antigo", "ativo": ""}
    )
    assert resposta.status_code == 302
    tnpq.refresh_from_db()
    assert (tnpq.nome, tnpq.ativo) == ("TNPQ antigo", False)
    # Sai das opções de inclusão, e quem está nele continua.
    assert apolice.planos_ativos == [tnp4]
    assert titular.vinculos.get().plano == tnpq


def test_plano_de_outro_contrato_nao_vale(apolice, tnpq, titular, dental):
    vinculo = Vinculo(beneficiario=titular, contrato=dental, plano=tnpq, data_inclusao=INICIO)
    with pytest.raises(ValidationError, match="de outro contrato"):
        vinculo.full_clean()


# ------------------------------------------------------------------
# Plano de cada pessoa
# ------------------------------------------------------------------


def test_lista_de_planos_agrupa_os_planos_debaixo_do_contrato(titular, apolice, tnpq, tnp4, dental):
    form = VinculoForm(beneficiario=titular)
    campo = form.fields["contrato"]
    assert isinstance(campo, PlanoDoContratoField)
    grupos = dict(campo.choices[1:])
    assert grupos["Saúde · Seguradora Exemplo B-900 (TNPQ / TNP4)"] == [
        (f"p{tnp4.pk}", "TNP4"),
        (f"p{tnpq.pk}", "TNPQ"),
    ]
    # O contrato sem planos é uma opção só, com o número dele.
    assert grupos[str(dental.pk)] == "Dental · Seguradora Exemplo D-1"


def test_incluir_no_plano_com_dependentes(logado, titular, conjuge, filho, apolice, tnpq, tnp4):
    resposta = logado.post(
        reverse("beneficiarios:novo_plano", args=[titular.pk]),
        {"contrato": f"p{tnp4.pk}", "data_inclusao": "01/01/2026", "dependentes": [conjuge.pk]},
    )
    assert resposta.status_code == 302
    assert planos_de(titular) == planos_de(conjuge) == [("TNP4", INICIO, None)]

    # O filho entra depois: o plano do titular já vem marcado, mas dá para escolher outro.
    form = VinculoForm(beneficiario=filho)
    assert form.initial["contrato"] == f"p{tnp4.pk}"
    resposta = logado.post(
        reverse("beneficiarios:novo_plano", args=[filho.pk]),
        {"contrato": f"p{tnpq.pk}", "data_inclusao": "01/02/2026"},
    )
    assert resposta.status_code == 302
    assert planos_de(filho) == [("TNPQ", date(2026, 2, 1), None)]


def test_corrigir_o_plano_na_edicao(logado, titular, apolice, tnpq, tnp4):
    vinculo = incluir(titular, apolice)
    assert vinculo.falta_o_plano
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    assert "Plano do contrato não informado" in pagina
    resposta = logado.post(
        reverse("beneficiarios:editar_plano", args=[vinculo.pk]),
        {"plano": tnpq.pk, "data_inclusao": vinculo.data_inclusao.strftime("%d/%m/%Y")},
    )
    assert resposta.status_code == 302
    vinculo.refresh_from_db()
    assert vinculo.plano == tnpq and not vinculo.falta_o_plano


def test_escolher_o_plano_de_quem_ja_estava_no_contrato(
    logado, titular, conjuge, filho, apolice, tnpq, tnp4
):
    """Contrato cadastrado antes dos planos: escolhe-se o plano de cada pessoa numa tela só."""
    for pessoa in (titular, conjuge, filho):
        incluir(pessoa, apolice)
    url = reverse("apolices:planos", args=[apolice.pk])
    pagina = logado.get(url)
    assert [v.beneficiario for v in pagina.context["sem_plano"]] == [titular, conjuge, filho]
    assert pagina.context["vidas_sem_plano"] == 3

    vinculos = {v.beneficiario_id: v.pk for v in apolice.vinculos.all()}
    resposta = logado.post(
        url,
        {
            f"plano_{vinculos[titular.pk]}": tnpq.pk,
            # O cônjuge fica com o plano do titular, e o filho, com outro.
            f"plano_{vinculos[conjuge.pk]}": "titular",
            f"plano_{vinculos[filho.pk]}": tnp4.pk,
        },
    )
    assert resposta.status_code == 302
    assert [planos_de(p)[0][0] for p in (titular, conjuge, filho)] == ["TNPQ", "TNPQ", "TNP4"]
    pagina = logado.get(url)
    assert not pagina.context["sem_plano"]
    assert {p.nome: p.vidas for p in pagina.context["planos"]} == {"TNPQ": 2, "TNP4": 1}


# ------------------------------------------------------------------
# Movimentações
# ------------------------------------------------------------------


def test_inclusao_pede_o_plano_e_os_dependentes_vao_no_mesmo(
    logado, titular, conjuge, apolice, tnpq, tnp4
):
    resposta = logado.post(
        reverse("movimentacoes:nova", kwargs={"beneficiario_pk": titular.pk, "tipo": "inclusao"}),
        {
            "contrato": f"p{tnpq.pk}",
            "recebida_em": "10/09/2026",
            "enviada_em": "10/09/2026",
            "vigencia": "01/10/2026",
            "dependentes": [conjuge.pk],
        },
    )
    assert resposta.status_code == 302
    pedidos = Movimentacao.objects.order_by("pk")
    assert [(p.beneficiario, p.plano) for p in pedidos] == [(titular, tnpq), (conjuge, tnpq)]
    for mov in pedidos:
        mov.mudar_etapa(Etapa.APROVADA)
    assert planos_de(titular) == planos_de(conjuge) == [("TNPQ", OUTUBRO.date(), None)]
    assert pedidos[0].nome_do_plano == "TNPQ"


def test_troca_de_plano_dentro_do_contrato(titular, conjuge, filho, apolice, tnpq, tnp4):
    no_plano(titular, tnpq)
    no_plano(conjuge, tnpq)
    no_plano(filho, tnp4)
    mov = pedido(titular, apolice, tipo="ALT", contrato_anterior=apolice, plano=tnp4)
    # O plano de onde sai é o que a pessoa tem hoje.
    assert mov.plano_anterior == tnpq and mov.no_mesmo_contrato
    assert (mov.nome_do_plano_anterior, mov.nome_do_plano) == ("TNPQ", "TNP4")

    mov.mudar_etapa(Etapa.APROVADA)
    assert planos_de(titular) == [("TNPQ", INICIO, OUTUBRO.date()), ("TNP4", OUTUBRO.date(), None)]
    # O cônjuge, que estava no mesmo plano, muda junto; o filho já estava no TNP4.
    assert planos_de(conjuge) == planos_de(titular)
    assert planos_de(filho) == [("TNP4", INICIO, None)]


def test_troca_para_o_mesmo_plano_nao_vale(titular, apolice, tnpq, tnp4):
    no_plano(titular, tnpq)
    with pytest.raises(ValidationError, match="plano diferente do atual"):
        pedido(titular, apolice, tipo="ALT", contrato_anterior=apolice, plano=tnpq)


def test_dependente_troca_de_plano_sozinho_dentro_do_contrato(
    titular, filho, apolice, tnpq, tnp4, pleno_de_outro_contrato
):
    no_plano(titular, tnpq)
    no_plano(filho, tnpq)
    form = MovimentacaoForm(
        tipo="ALT", beneficiario=filho, initial={"contrato_anterior": apolice.pk}
    )
    # O dependente só troca dentro do contrato; entre contratos, vai junto com o titular.
    assert list(form.fields["contrato"].opcoes) == [f"p{tnp4.pk}"]
    assert form.initial["contrato"] == f"p{tnp4.pk}"

    mov = pedido(filho, apolice, tipo="ALT", contrato_anterior=apolice, plano=tnp4)
    mov.mudar_etapa(Etapa.APROVADA)
    assert planos_de(titular) == [("TNPQ", INICIO, None)]
    assert planos_de(filho)[-1] == ("TNP4", OUTUBRO.date(), None)


@pytest.fixture
def pleno_de_outro_contrato(empresa, seguradora, matriz, filial):
    return contrato_com_produto(empresa, seguradora, "U-100", "PLENO", [matriz, filial])


def test_titular_troca_para_outro_plano_ou_outro_contrato(
    titular, apolice, tnpq, tnp4, pleno_de_outro_contrato
):
    no_plano(titular, tnpq)
    form = MovimentacaoForm(
        tipo="ALT", beneficiario=titular, initial={"contrato_anterior": apolice.pk}
    )
    assert set(form.fields["contrato"].opcoes) == {f"p{tnp4.pk}", str(pleno_de_outro_contrato.pk)}
    assert "TNPQ" in form.fields["contrato_anterior"].label_from_instance(apolice)


def test_movimentacao_refeita_mantem_o_plano(titular, apolice, tnpq):
    mov = pedido(titular, apolice, plano=tnpq)
    mov.mudar_etapa(Etapa.REJEITADA, motivo_rejeicao="RAS")
    assert mov.refazer(None).plano == tnpq


# ------------------------------------------------------------------
# Planilha do mês
# ------------------------------------------------------------------


def test_planilha_do_mes_traz_o_plano_de_cada_pessoa(
    empresa, titular, conjuge, apolice, tnpq, tnp4
):
    digitada = {"enviada_em": DIGITADA.date(), "recebida_em": DIGITADA.date()}
    no_plano(titular, tnpq)
    pedido(conjuge, apolice, plano=tnpq, **digitada)
    pedido(titular, apolice, tipo="ALT", contrato_anterior=apolice, plano=tnp4, **digitada)
    livro = load_workbook(BytesIO(PlanilhaDoMes(empresa, DIGITADA.date()).gerar()))
    saude, alteracoes = livro["SAÚDE"], livro["ALTERAÇÕES DE PLANO"]
    assert saude["H2"].value == "PLANO" and saude["H3"].value == "TNPQ"
    linha = [celula.value for celula in alteracoes[3]]
    assert "TNP4" in linha and "TNPQ para TNP4." in linha


def test_importar_pelo_nome_do_plano(empresa, usuario, ana_4521, apolice, tnpq, tnp4):
    resultados = importar(
        empresa, usuario, aba_unimed(na_unimed("Ana Titular", 4521, plano="tnp4"))
    )
    assert situacoes(resultados) == [(IMPORTAR, "Inclusão em TNP4, em análise.")]
    assert Movimentacao.objects.get().plano == tnp4


def test_importar_sem_dizer_qual_plano_do_contrato(empresa, usuario, ana_4521, apolice, tnpq, tnp4):
    linha = na_unimed("Ana Titular", 4521, plano="TNPQ / TNP4")
    [(situacao, mensagem)] = situacoes(importar(empresa, usuario, aba_unimed(linha)))
    assert situacao == PROBLEMA
    assert mensagem == (
        "O contrato B-900 tem mais de um plano: informe na coluna PLANO qual deles (TNP4, TNPQ)."
    )


def test_importar_anota_o_plano_de_quem_ja_estava_no_contrato(
    empresa, usuario, ana_4521, apolice, tnpq, tnp4
):
    vinculo = incluir(ana_4521, apolice)
    linha = na_unimed("Ana Titular", 4521, "Processado", "123", plano="TNPQ")
    assert situacoes(importar(empresa, usuario, aba_unimed(linha))) == [
        (ATUALIZAR, "Já estava no contrato; agora com o plano TNPQ anotado.")
    ]
    vinculo.refresh_from_db()
    assert vinculo.plano == tnpq and not Movimentacao.objects.exists()


def test_importar_troca_de_plano_dentro_do_contrato(
    empresa, usuario, ana_4521, apolice, tnpq, tnp4
):
    no_plano(ana_4521, tnpq)
    aba = (
        "ALTERAÇÕES DE PLANO",
        ALTERACOES,
        [["Carla", "Pendente", 4521, "Ana Titular", DIGITADA, OUTUBRO, "TNP4", ""]],
    )
    assert situacoes(importar(empresa, usuario, aba)) == [
        (IMPORTAR, "Alteração de TNPQ para TNP4, em análise.")
    ]
    mov = Movimentacao.objects.get()
    assert (mov.contrato_anterior, mov.plano_anterior, mov.plano) == (apolice, tnpq, tnp4)


@pytest.fixture
def ana_4521(titular):
    titular.matricula = "4521"
    titular.save()
    return titular


# ------------------------------------------------------------------
# Relatório de vidas
# ------------------------------------------------------------------


def test_relatorio_de_vidas_separa_os_planos_do_contrato(logado, titular, conjuge, apolice, tnpq):
    no_plano(titular, tnpq)
    incluir(conjuge, apolice)
    resposta = logado.get(reverse("relatorios:vidas"), {"data": date.today().strftime("%d/%m/%Y")})
    linhas = resposta.context["resumo"]["por_contrato"]
    assert [(linha["plano__nome"], linha["vidas"]) for linha in linhas] == [("TNPQ", 1), (None, 1)]
