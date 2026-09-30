"""Alteração de plano: a pessoa sai de um plano e entra noutro do mesmo ramo na mesma data."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from beneficiarios.models import Vinculo
from beneficiarios.tests.fixtures import contrato, incluir
from beneficiarios.vidas import VidasDoCliente
from movimentacoes.models import Etapa, Movimentacao
from movimentacoes.tests.test_movimentacoes import pedido

pytestmark = pytest.mark.django_db

OUTUBRO = date(2026, 10, 1)


@pytest.fixture
def pleno(empresa, seguradora, matriz, filial):
    return plano(empresa, seguradora, "U-100", "PLENO", [matriz, filial])


@pytest.fixture
def flex(empresa, seguradora, matriz, filial):
    return plano(empresa, seguradora, "U-200", "FLEX", [matriz, filial])


@pytest.fixture
def amigo(empresa, seguradora, matriz, filial):
    return plano(empresa, seguradora, "U-300", "AMIGO", [matriz, filial])


def plano(empresa, seguradora, numero, produto, unidades, ramo="Saúde"):
    novo = contrato(empresa, seguradora, ramo, numero, unidades)
    novo.produto = produto
    novo.save()
    return novo


def alteracao(pessoa, de, para, **extra):
    return pedido(pessoa, para, tipo="ALT", contrato_anterior=de, vigencia=OUTUBRO, **extra)


def planos_de(pessoa) -> list[tuple]:
    return list(
        pessoa.vinculos.order_by("data_inclusao", "pk").values_list(
            "contrato__produto", "data_inclusao", "data_exclusao", "carteirinha"
        )
    )


# ------------------------------------------------------------------
# Regras e etapas
# ------------------------------------------------------------------


def test_aprovada_sai_do_plano_atual_e_entra_no_novo(empresa, titular, pleno, flex):
    vinculo = incluir(titular, pleno, inclusao=date(2026, 1, 1))
    vinculo.carteirinha = "0032000000123"
    vinculo.save()
    mov = alteracao(titular, pleno, flex)
    assert (
        mov.etapa == Etapa.EM_ANALISE and str(mov) == "Alteração de plano de Ana Titular em Saúde"
    )

    mov.mudar_etapa(Etapa.APROVADA)
    # A carteirinha continua a mesma; se a operadora emitir outra, corrige-se no plano.
    assert planos_de(titular) == [
        ("PLENO", date(2026, 1, 1), OUTUBRO, "0032000000123"),
        ("FLEX", OUTUBRO, None, "0032000000123"),
    ]
    assert mov.vinculo.contrato == flex
    vidas = VidasDoCliente(empresa, em=OUTUBRO)
    assert vidas.total_pessoas == 1

    # Concluir não pede carteirinha, como na exclusão.
    mov.mudar_etapa(Etapa.CONCLUIDA)
    assert mov.etapa == Etapa.CONCLUIDA and mov.carteirinha_enviada_em is None


def test_no_seguro_de_vida_o_salario_vai_para_o_novo_plano(
    titular, empresa, seguradora, matriz, filial
):
    antigo = plano(empresa, seguradora, "V-100", "VIDA A", [matriz, filial], ramo="Vida")
    novo = plano(empresa, seguradora, "V-200", "VIDA B", [matriz, filial], ramo="Vida")
    for contrato_de_vida in (antigo, novo):
        contrato_de_vida.capital_multiplo = 24
        contrato_de_vida.save()
    vinculo = incluir(titular, antigo, inclusao=date(2026, 1, 1))
    vinculo.salario = Decimal("3000")
    vinculo.save()

    alteracao(titular, antigo, novo).mudar_etapa(Etapa.APROVADA)

    assert titular.vinculos.get(contrato=novo).salario == Decimal("3000")


def test_dependentes_do_plano_atual_mudam_junto(titular, conjuge, filho, pleno, flex, dental):
    incluir(titular, pleno, inclusao=date(2026, 1, 1))
    incluir(conjuge, pleno, inclusao=date(2026, 1, 1))
    incluir(titular, dental, inclusao=date(2026, 1, 1))
    incluir(filho, dental, inclusao=date(2026, 1, 1))
    alteracao(titular, pleno, flex).mudar_etapa(Etapa.APROVADA)

    assert [plano for plano, *_ in planos_de(conjuge)] == ["PLENO", "FLEX"]
    assert conjuge.vinculos.get(contrato=flex).data_inclusao == OUTUBRO
    # Quem está só no dental não muda.
    assert filho.vinculos.get().data_exclusao is None
    assert titular.vinculos.get(contrato=dental).data_exclusao is None


def test_dependente_que_ja_mudou_com_o_titular(titular, conjuge, pleno, flex):
    """O pedido do dependente, aprovado depois do titular, só se liga ao novo plano."""
    incluir(titular, pleno, inclusao=date(2026, 1, 1))
    incluir(conjuge, pleno, inclusao=date(2026, 1, 1))
    do_titular = alteracao(titular, pleno, flex)
    do_conjuge = alteracao(conjuge, pleno, flex)
    do_titular.mudar_etapa(Etapa.APROVADA)
    do_conjuge.refresh_from_db()
    do_conjuge.mudar_etapa(Etapa.APROVADA)
    assert do_conjuge.vinculo == conjuge.vinculos.get(contrato=flex)
    assert Vinculo.objects.filter(contrato=flex).count() == 2


def test_regras_para_pedir_a_alteracao(titular, pleno, flex, amigo, dental):
    incluir(titular, pleno)
    with pytest.raises(ValidationError, match="de onde a pessoa sai"):
        pedido(titular, flex, tipo="ALT")
    with pytest.raises(ValidationError, match="diferente do atual"):
        alteracao(titular, pleno, pleno)
    with pytest.raises(ValidationError, match="mesmo ramo"):
        alteracao(titular, pleno, dental)
    with pytest.raises(ValidationError, match="não está neste plano"):
        alteracao(titular, flex, amigo)
    incluir(titular, flex)
    with pytest.raises(ValidationError, match="já está neste plano"):
        alteracao(titular, pleno, flex)


def test_um_pedido_em_aberto_para_sair_do_plano(titular, pleno, flex, amigo):
    incluir(titular, pleno)
    alteracao(titular, pleno, flex)
    with pytest.raises(ValidationError, match="em aberto"):
        alteracao(titular, pleno, amigo)
    with pytest.raises(ValidationError, match="em aberto"):
        pedido(titular, pleno, tipo="EXC")


def test_um_pedido_em_aberto_para_entrar_no_plano(titular, pleno, flex):
    incluir(titular, pleno, inclusao=date(2026, 1, 1))
    alteracao(titular, pleno, flex)
    # Saiu do plano atual por outro caminho e pediu para entrar no novo: já há pedido.
    Vinculo.objects.filter(contrato=pleno).update(data_exclusao=date(2026, 9, 1))
    with pytest.raises(ValidationError, match="em aberto"):
        pedido(titular, flex)


def test_so_a_alteracao_tem_plano_anterior(titular, pleno, flex):
    with pytest.raises(ValidationError, match="Só a alteração de plano tem plano anterior"):
        pedido(titular, flex, contrato_anterior=pleno)


def test_aprovar_quando_ja_saiu_do_plano_atual(titular, pleno, flex):
    vinculo = incluir(titular, pleno, inclusao=date(2026, 1, 1))
    mov = alteracao(titular, pleno, flex)
    vinculo.encerrar(date(2026, 9, 1))
    with pytest.raises(ValidationError, match="não está mais no plano anterior"):
        mov.mudar_etapa(Etapa.APROVADA)
    assert not Vinculo.objects.filter(contrato=flex).exists()


def test_refazer_alteracao_rejeitada(titular, pleno, flex, usuario):
    incluir(titular, pleno)
    mov = alteracao(titular, pleno, flex)
    mov.mudar_etapa(Etapa.REJEITADA, motivo_rejeicao="DOC")
    nova = mov.refazer(usuario)
    assert nova.eh_alteracao and nova.contrato_anterior == pleno and nova.contrato == flex


# ------------------------------------------------------------------
# Telas
# ------------------------------------------------------------------


def test_botao_alterar_plano_so_quando_ha_outro_plano_do_ramo(
    logado, titular, conjuge, pleno, flex, dental
):
    incluir(titular, pleno)
    incluir(titular, dental)
    incluir(conjuge, pleno)
    alterar = reverse("movimentacoes:nova", args=[titular.pk, "alteracao"])
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    assert f"{alterar}?contrato={pleno.pk}" in pagina
    assert f"{alterar}?contrato={dental.pk}" not in pagina
    # O dependente muda junto com o titular.
    pagina = logado.get(conjuge.get_absolute_url()).content.decode()
    assert "Alterar plano" not in pagina


def test_pedir_alteracao_pela_tela(logado, titular, conjuge, pleno, flex, dental, contato_rh):
    incluir(titular, pleno)
    incluir(titular, dental)
    incluir(conjuge, pleno)
    url = reverse("movimentacoes:nova", args=[titular.pk, "alteracao"])
    pagina = logado.get(url, {"contrato": pleno.pk}).content.decode()
    assert "Alteração de plano de Ana Titular" in pagina
    assert "mudam junto" in pagina
    assert "U-200 (FLEX)" in pagina and "D-1" not in pagina
    # Só há um plano para onde ir: ele já vem escolhido.
    assert f'<option value="{flex.pk}" selected>' in pagina
    # O plano atual vem fixo do botão, mesmo que o formulário mande outro.
    resposta = logado.post(
        f"{url}?contrato={pleno.pk}",
        {
            "contrato_anterior": dental.pk,
            "contrato": flex.pk,
            "solicitante": contato_rh.pk,
            "recebida_em": "20/09/2026",
            "enviada_em": "21/09/2026",
            "vigencia": "01/10/2026",
        },
    )
    assert resposta.status_code == 302
    mov = Movimentacao.objects.get()
    assert (mov.tipo, mov.contrato_anterior, mov.contrato) == ("ALT", pleno, flex)
    assert mov.registrada_por.username == "ana"


def test_fluxo_da_alteracao_pela_tela(logado, titular, conjuge, pleno, flex):
    incluir(titular, pleno, inclusao=date(2026, 1, 1))
    incluir(conjuge, pleno, inclusao=date(2026, 1, 1))
    mov = alteracao(titular, pleno, flex)
    url = lambda etapa: reverse("movimentacoes:mudar_etapa", args=[mov.pk, etapa])  # noqa: E731
    pagina = logado.get(url("APR")).content.decode()
    assert "mudam junto" in pagina and 'name="carteirinha"' not in pagina
    logado.post(url("APR"), {"vigencia": "01/10/2026"})
    assert logado.get(url("CON")).status_code == 200
    logado.post(url("CON"), {"observacao": "Processada no portal"})
    mov.refresh_from_db()
    assert mov.etapa == Etapa.CONCLUIDA
    assert conjuge.vinculos.get(data_exclusao__isnull=True).contrato == flex

    pagina = logado.get(mov.get_absolute_url()).content.decode()
    assert "Plano anterior" in pagina and "U-100 (PLENO)" in pagina
    assert "Novo plano" in pagina and "U-200 (FLEX)" in pagina
    assert "Início no novo plano" in pagina
    lista = logado.get(reverse("movimentacoes:lista"), {"situacao": "todas"}).content.decode()
    assert "Alteração de plano" in lista and "PLENO para FLEX" in lista


def test_pedido_repetido_pela_tela_mostra_o_erro(logado, titular, saude):
    """Antes, um segundo pedido igual em aberto dava erro no servidor."""
    pedido(titular, saude)
    resposta = logado.post(
        reverse("movimentacoes:nova", args=[titular.pk, "inclusao"]),
        {"contrato": saude.pk, "recebida_em": "20/09/2026", "enviada_em": "21/09/2026"},
    )
    assert resposta.status_code == 200
    assert "Já existe uma movimentação em aberto" in resposta.content.decode()
    assert Movimentacao.objects.count() == 1
