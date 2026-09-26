from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from beneficiarios.models import Vinculo
from beneficiarios.tests.fixtures import HOJE, incluir
from beneficiarios.vidas import VidasDoCliente
from clientes.models import Contato
from movimentacoes.models import Etapa, Movimentacao

pytestmark = pytest.mark.django_db


@pytest.fixture
def rh(empresa, filial):
    contato = Contato.objects.create(cliente=empresa, nome="Carla RH", cargo="RH")
    contato.unidades.add(filial)
    return contato


def pedido(pessoa, plano, tipo="INC", **extra):
    movimentacao = Movimentacao(
        tipo=tipo,
        cliente=pessoa.cliente,
        beneficiario=pessoa,
        contrato=plano,
        vigencia=extra.pop("vigencia", date(2026, 10, 1)),
        **extra,
    )
    movimentacao.full_clean()
    movimentacao.save()
    return movimentacao


# ------------------------------------------------------------------
# Vigência sugerida pelo fechamento
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recebida", "esperada"),
    [
        (date(2026, 9, 10), date(2026, 10, 1)),
        (date(2026, 9, 25), date(2026, 10, 1)),
        (date(2026, 9, 26), date(2026, 11, 1)),
        (date(2026, 12, 26), date(2027, 2, 1)),
    ],
)
def test_vigencia_sugerida_respeita_o_dia_de_fechamento(saude, recebida, esperada):
    saude.dia_fechamento = 25
    assert saude.vigencia_sugerida(recebida) == esperada


def test_sem_fechamento_vigencia_e_o_mes_seguinte(saude):
    assert saude.vigencia_sugerida(date(2026, 12, 30)) == date(2027, 1, 1)


def test_vigencia_em_branco_usa_a_sugerida(titular, saude):
    saude.dia_fechamento = 25
    saude.save()
    mov = Movimentacao(
        tipo="INC", beneficiario=titular, contrato=saude, recebida_em=date(2026, 9, 27)
    )
    mov.save()
    assert mov.vigencia == date(2026, 11, 1)
    assert mov.apos_o_fechamento


# ------------------------------------------------------------------
# Regras e etapas
# ------------------------------------------------------------------


def test_nao_inclui_quem_ja_esta_no_plano(titular, saude):
    incluir(titular, saude)
    with pytest.raises(ValidationError, match="já está neste plano"):
        pedido(titular, saude)


def test_nao_exclui_quem_nao_esta_no_plano(titular, saude):
    with pytest.raises(ValidationError, match="não está neste plano"):
        pedido(titular, saude, tipo="EXC")


def test_um_pedido_em_aberto_por_pessoa_e_plano(titular, saude):
    pedido(titular, saude)
    with pytest.raises(ValidationError, match="em aberto"):
        pedido(titular, saude)


def test_etapas_fora_de_ordem_sao_barradas(titular, saude):
    mov = pedido(titular, saude)
    with pytest.raises(ValidationError, match="Não é possível"):
        mov.mudar_etapa(Etapa.APROVADA)


def test_inclusao_aprovada_entra_no_plano_e_conta_como_vida(empresa, titular, saude):
    mov = pedido(titular, saude, vigencia=date(2026, 10, 1))
    mov.mudar_etapa(Etapa.ENVIADA)
    assert mov.enviada_em == HOJE
    mov.mudar_etapa(Etapa.EM_ANALISE, observacao="Carência: aguardando entrevista médica")
    # Em análise ainda não é vida.
    assert VidasDoCliente(empresa, em=date(2026, 10, 1)).total_pessoas == 0

    mov.mudar_etapa(Etapa.APROVADA, carteirinha="0001")
    vinculo = Vinculo.objects.get()
    assert vinculo.data_inclusao == date(2026, 10, 1) and vinculo.carteirinha == "0001"
    assert mov.vinculo == vinculo
    assert VidasDoCliente(empresa, em=date(2026, 10, 1)).total_pessoas == 1
    assert Movimentacao.objects.em_aberto().exists()

    mov.mudar_etapa(Etapa.CONCLUIDA)
    assert mov.carteirinha_enviada_em == HOJE
    assert not Movimentacao.objects.em_aberto().exists()


def test_concluir_inclusao_exige_carteirinha(titular, saude):
    mov = pedido(titular, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    mov.mudar_etapa(Etapa.APROVADA)
    with pytest.raises(ValidationError, match="carteirinha"):
        mov.mudar_etapa(Etapa.CONCLUIDA)
    mov.refresh_from_db()
    assert mov.etapa == Etapa.APROVADA
    mov.mudar_etapa(Etapa.CONCLUIDA, carteirinha="0002")
    assert Vinculo.objects.get().carteirinha == "0002"


def test_dependente_aprovado_antes_do_titular_da_aviso(titular, conjuge, saude):
    mov_titular = pedido(titular, saude)
    mov_conjuge = pedido(conjuge, saude)
    for mov in (mov_titular, mov_conjuge):
        mov.mudar_etapa(Etapa.ENVIADA)
    with pytest.raises(ValidationError, match="aprove-o primeiro"):
        mov_conjuge.mudar_etapa(Etapa.APROVADA)
    assert not Vinculo.objects.exists()
    mov_titular.mudar_etapa(Etapa.APROVADA)
    mov_conjuge.refresh_from_db()
    mov_conjuge.mudar_etapa(Etapa.APROVADA)
    assert Vinculo.objects.count() == 2


def test_exclusao_aprovada_tira_do_plano(empresa, titular, saude):
    incluir(titular, saude, inclusao=date(2026, 1, 1))
    mov = pedido(titular, saude, tipo="EXC", vigencia=date(2026, 10, 1))
    mov.mudar_etapa(Etapa.ENVIADA)
    mov.mudar_etapa(Etapa.APROVADA)
    assert Vinculo.objects.get().data_exclusao == date(2026, 10, 1)
    assert VidasDoCliente(empresa, em=date(2026, 10, 1)).total_pessoas == 0
    mov.mudar_etapa(Etapa.CONCLUIDA)
    assert mov.etapa == Etapa.CONCLUIDA


def test_rejeitada_exige_motivo_e_pode_ser_refeita(titular, saude, usuario):
    mov = pedido(titular, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    with pytest.raises(ValidationError, match="motivo"):
        mov.mudar_etapa(Etapa.REJEITADA)
    mov.mudar_etapa(Etapa.REJEITADA, motivo_rejeicao="ENT")
    assert not Movimentacao.objects.em_aberto().exists()

    nova = mov.refazer(usuario)
    assert nova.origem == mov and nova.etapa == Etapa.RECEBIDA
    assert "Prazo da entrevista médica" in nova.observacao
    assert list(mov.refeitas.all()) == [nova]


# ------------------------------------------------------------------
# Telas
# ------------------------------------------------------------------


def test_solicitar_inclusao_do_titular_com_dependente(logado, titular, conjuge, filho, saude, rh):
    resposta = logado.post(
        reverse("movimentacoes:nova", args=[titular.pk, "inclusao"]),
        {
            "contrato": saude.pk,
            "solicitante": rh.pk,
            "recebida_em": "2026-09-20",
            "enviada_em": "2026-09-21",
            "vigencia": "2026-10-01",
            "dependentes": [conjuge.pk],
        },
    )
    assert resposta.status_code == 302
    pedidos = Movimentacao.objects.order_by("beneficiario__nome")
    assert [m.beneficiario for m in pedidos] == [titular, conjuge]
    assert all(m.etapa == Etapa.ENVIADA and m.solicitante == rh for m in pedidos)
    assert pedidos[0].registrada_por.username == "ana"


def test_dependente_pode_pedir_plano_em_que_o_titular_esta_entrando(
    logado, titular, filho, saude, dental
):
    pedido(titular, saude)
    pagina = logado.get(reverse("movimentacoes:nova", args=[filho.pk, "inclusao"]))
    conteudo = pagina.content.decode()
    assert "S-1" in conteudo and "D-1" not in conteudo


def test_tipo_invalido_na_url(logado, titular):
    assert logado.get(reverse("movimentacoes:nova", args=[titular.pk, "outro"])).status_code == 404


def test_fluxo_pela_tela_ate_a_carteirinha(logado, titular, saude):
    mov = pedido(titular, saude)
    url = lambda etapa: reverse("movimentacoes:mudar_etapa", args=[mov.pk, etapa])  # noqa: E731
    logado.post(url("ENV"), {"enviada_em": "2026-09-21"})
    logado.post(url("ANA"), {"observacao": "Carência"})
    logado.post(url("APR"), {"vigencia": "2026-10-01", "carteirinha": ""})
    resposta = logado.post(url("CON"), {"carteirinha": "", "carteirinha_enviada_em": "2026-10-02"})
    assert resposta.status_code == 200  # carteirinha obrigatória
    logado.post(url("CON"), {"carteirinha": "0009", "carteirinha_enviada_em": "2026-10-02"})
    mov.refresh_from_db()
    assert mov.etapa == Etapa.CONCLUIDA and mov.carteirinha == "0009"

    pagina = logado.get(mov.get_absolute_url()).content.decode()
    assert "etapa: Concluída" in pagina and "Ana Lima" in pagina


def test_etapa_nao_permitida_pela_url(logado, titular, saude):
    mov = pedido(titular, saude)
    url = reverse("movimentacoes:mudar_etapa", args=[mov.pk, "CON"])
    assert logado.get(url).status_code == 404


def test_erro_ao_aprovar_aparece_na_tela(logado, titular, conjuge, saude):
    pedido(titular, saude)
    mov = pedido(conjuge, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    resposta = logado.post(
        reverse("movimentacoes:mudar_etapa", args=[mov.pk, "APR"]), {"vigencia": "2026-10-01"}
    )
    assert resposta.status_code == 200
    assert "aprove-o primeiro" in resposta.content.decode()
    mov.refresh_from_db()
    assert mov.etapa == Etapa.ENVIADA


def test_refazer_pela_tela(logado, titular, saude):
    mov = pedido(titular, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    mov.mudar_etapa(Etapa.REJEITADA, motivo_rejeicao="RAS")
    resposta = logado.post(reverse("movimentacoes:refazer", args=[mov.pk]))
    nova = Movimentacao.objects.exclude(pk=mov.pk).get()
    assert resposta.url == nova.get_absolute_url()


def test_lista_mostra_em_aberto_de_qualquer_mes(logado, titular, conjuge, saude):
    setembro = pedido(titular, saude, vigencia=date(2026, 9, 1))
    outubro = pedido(conjuge, saude, vigencia=date(2026, 10, 1))
    setembro.mudar_etapa(Etapa.ENVIADA)
    setembro.mudar_etapa(Etapa.REJEITADA, motivo_rejeicao="DOC")
    url = reverse("movimentacoes:lista")

    em_aberto = logado.get(url).content.decode()
    assert outubro.beneficiario.nome in em_aberto
    assert setembro.beneficiario.nome not in em_aberto

    mes = logado.get(url, {"mes": "2026-09", "situacao": "todas"}).content.decode()
    assert setembro.beneficiario.nome in mes and outubro.beneficiario.nome not in mes

    assert "Mês inválido" in logado.get(url, {"mes": "2026-13"}).content.decode()


def test_pagina_da_pessoa_mostra_movimentacoes_e_historico(logado, titular, saude):
    mov = pedido(titular, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    assert "Inclusão em Saúde" in pagina
    assert "Movimentação" in pagina


def test_exclusao_do_dependente_depois_da_do_titular(titular, conjuge, saude):
    """O titular saiu e levou o dependente: aprovar o pedido do dependente não quebra."""
    incluir(titular, saude, inclusao=date(2026, 1, 1))
    incluir(conjuge, saude, inclusao=date(2026, 1, 1))
    do_titular = pedido(titular, saude, tipo="EXC", vigencia=date(2026, 10, 1))
    do_conjuge = pedido(conjuge, saude, tipo="EXC", vigencia=date(2026, 10, 1))
    for mov in (do_titular, do_conjuge):
        mov.mudar_etapa(Etapa.ENVIADA)
    do_titular.mudar_etapa(Etapa.APROVADA)
    do_conjuge.refresh_from_db()
    do_conjuge.mudar_etapa(Etapa.APROVADA)
    assert do_conjuge.vinculo.data_exclusao == date(2026, 10, 1)
    assert not Vinculo.objects.filter(data_exclusao__isnull=True).exists()


def test_corrigir_carteirinha_depois_de_aprovada_atualiza_o_plano(logado, titular, saude):
    mov = pedido(titular, saude)
    mov.mudar_etapa(Etapa.ENVIADA)
    mov.mudar_etapa(Etapa.APROVADA, carteirinha="0001")
    resposta = logado.post(
        reverse("movimentacoes:editar", args=[mov.pk]),
        {"recebida_em": mov.recebida_em.isoformat(), "carteirinha": "0001-9"},
    )
    assert resposta.status_code == 302
    assert Vinculo.objects.get().carteirinha == "0001-9"


def test_aviso_na_exclusao_do_titular_com_dependentes(logado, titular, conjuge, saude):
    incluir(titular, saude)
    incluir(conjuge, saude)
    pagina = logado.get(reverse("movimentacoes:nova", args=[titular.pk, "exclusao"]))
    assert "dependentes deste plano saem junto" in pagina.content.decode()
