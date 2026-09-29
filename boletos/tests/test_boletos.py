import re
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apolices.models import Contrato
from beneficiarios.tests.fixtures import HOJE, contrato
from boletos.models import Boleto, Situacao, somar_meses
from clientes.models import Contato

pytestmark = pytest.mark.django_db

OUTUBRO = date(2026, 10, 1)


@pytest.fixture
def com_boleto(saude):
    """Contrato de saúde em que a corretora envia o boleto (vence dia 10)."""
    saude.corretora_envia_boleto = True
    saude.save()
    return saude


def boleto(plano, tipo="MEN", referencia=OUTUBRO, **extra):
    novo = Boleto(contrato=plano, tipo=tipo, referencia=referencia, **extra)
    novo.full_clean(exclude=["vencimento"])
    novo.save()
    return novo


# ------------------------------------------------------------------
# Vencimento e geração do mês
# ------------------------------------------------------------------


def test_vencimento_do_contrato_em_meses_curtos(saude):
    saude.dia_vencimento = 31
    assert saude.vencimento_em(2026, 10) == date(2026, 10, 31)
    assert saude.vencimento_em(2026, 2) == date(2026, 2, 28)
    assert saude.vencimento_em(2028, 2) == date(2028, 2, 29)


def test_gerar_mensalidades_so_dos_contratos_em_que_a_corretora_envia(com_boleto, dental, usuario):
    assert Boleto.gerar_mensalidades(date(2026, 10, 15), usuario=usuario) == (1, 0)
    gerado = Boleto.objects.get()
    assert gerado.contrato == com_boleto and gerado.tipo == Boleto.Tipo.MENSALIDADE
    assert gerado.referencia == OUTUBRO and gerado.vencimento == date(2026, 10, 10)
    assert gerado.registrado_por == usuario and not gerado.fora_do_vencimento
    # Gerar de novo não repete.
    assert Boleto.gerar_mensalidades(OUTUBRO) == (0, 1)


def test_gerar_ignora_contrato_cancelado_e_o_que_ainda_nao_comecou(com_boleto, dental):
    com_boleto.situacao = Contrato.Situacao.CANCELADO
    com_boleto.save()
    dental.corretora_envia_boleto = True
    dental.inicio_vigencia = date(2026, 11, 1)
    dental.save()
    assert Boleto.gerar_mensalidades(OUTUBRO) == (0, 0)
    assert Boleto.gerar_mensalidades(date(2026, 11, 1)) == (1, 0)


def test_mensalidade_cancelada_nao_volta_ao_gerar_de_novo(com_boleto):
    Boleto.gerar_mensalidades(OUTUBRO)
    Boleto.objects.update(cancelado=True)
    assert Boleto.gerar_mensalidades(OUTUBRO) == (0, 1)
    # Mas dá para lançar outra mensalidade no lugar da cancelada.
    boleto(com_boleto, vencimento=date(2026, 10, 20))


def test_gerar_varios_meses_de_uma_vez(com_boleto, dental):
    dental.corretora_envia_boleto = True
    dental.dia_vencimento = 5
    dental.save()
    assert Boleto.gerar_mensalidades(OUTUBRO, date(2026, 12, 1)) == (6, 0)

    def vencimentos(plano) -> list:
        return [b.vencimento for b in plano.boletos.order_by("referencia")]

    assert vencimentos(com_boleto) == [date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)]
    assert vencimentos(dental) == [date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)]
    assert not Boleto.objects.filter(fora_do_vencimento=True).exists()
    # Com um mês a mais, só o mês novo é criado.
    assert Boleto.gerar_mensalidades(OUTUBRO, date(2027, 1, 1)) == (2, 6)


def test_gerar_so_de_um_contrato_a_partir_do_inicio_da_vigencia(com_boleto, dental):
    dental.corretora_envia_boleto = True
    dental.inicio_vigencia = date(2026, 11, 15)
    dental.save()
    assert Boleto.gerar_mensalidades(OUTUBRO, date(2026, 12, 1), contrato=dental) == (2, 0)
    assert set(Boleto.objects.values_list("contrato", "referencia")) == {
        (dental.pk, date(2026, 11, 1)),
        (dental.pk, date(2026, 12, 1)),
    }


def test_uma_mensalidade_por_contrato_e_mes(com_boleto):
    boleto(com_boleto)
    with pytest.raises(ValidationError, match="já tem a mensalidade"):
        boleto(com_boleto, referencia=date(2026, 10, 20))
    boleto(com_boleto, tipo="COP")


def test_vencimento_em_branco_usa_o_do_contrato(com_boleto):
    copart = boleto(com_boleto, tipo="COP", referencia=date(2026, 10, 15))
    assert copart.referencia == OUTUBRO
    assert copart.vencimento == date(2026, 10, 10) and not copart.fora_do_vencimento


def test_outro_vencimento_fica_marcado(com_boleto):
    reajuste = boleto(com_boleto, tipo="REA", vencimento=date(2026, 10, 25))
    assert reajuste.fora_do_vencimento
    reajuste.vencimento = date(2026, 10, 10)
    reajuste.save()
    assert not reajuste.fora_do_vencimento


# ------------------------------------------------------------------
# Situação e prazo
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dias", "prazo", "atencao"),
    [
        (-2, "venceu há 2 dias", True),
        (-1, "venceu ontem", True),
        (0, "vence hoje", True),
        (1, "vence amanhã", True),
        (7, "vence em 7 dias", True),
        (30, "vence em 30 dias", False),
    ],
)
def test_prazo_dos_que_faltam_enviar(com_boleto, dias, prazo, atencao):
    novo = boleto(com_boleto, vencimento=HOJE + timedelta(days=dias))
    assert novo.situacao == Situacao.A_ENVIAR
    assert novo.prazo == prazo and novo.pede_atencao is atencao


def test_registrar_envio(com_boleto, usuario, contato_rh):
    novo = boleto(com_boleto, vencimento=HOJE)
    novo.registrar_envio(usuario, para=contato_rh)
    assert novo.situacao == Situacao.ENVIADO and novo.enviado_em == HOJE
    assert novo.enviado_por == usuario and novo.enviado_para == contato_rh
    assert novo.prazo == "" and not novo.pede_atencao
    with pytest.raises(ValidationError, match="já está enviado"):
        novo.registrar_envio(usuario)


def test_boleto_cancelado_nao_e_enviado(com_boleto, usuario):
    novo = boleto(com_boleto, cancelado=True)
    assert novo.situacao == Situacao.CANCELADO
    with pytest.raises(ValidationError, match="já está cancelado"):
        novo.registrar_envio(usuario)


def test_contato_de_outro_cliente(com_boleto, pessoa):
    de_fora = Contato.objects.create(cliente=pessoa, nome="Outra Pessoa")
    with pytest.raises(ValidationError, match="deste cliente"):
        boleto(com_boleto, enviado_para=de_fora)


# ------------------------------------------------------------------
# Telas
# ------------------------------------------------------------------


def test_telas_de_boletos_exigem_login(client):
    resposta = client.get(reverse("boletos:lista"))
    assert resposta.status_code == 302 and "/entrar/" in resposta.url


def test_lista_mostra_o_que_falta_enviar_por_padrao(logado, com_boleto, dental, usuario):
    a_enviar = boleto(com_boleto, vencimento=HOJE - timedelta(days=1))
    enviado = boleto(dental, tipo="COP")
    enviado.registrar_envio(usuario)
    boleto(com_boleto, tipo="ESP", cancelado=True, observacao="Substituído")
    url = reverse("boletos:lista")

    pagina = logado.get(url).content.decode()
    assert a_enviar.get_absolute_url() in pagina
    assert enviado.get_absolute_url() not in pagina
    assert "venceu ontem" in pagina
    assert "<strong>1</strong> a enviar" in pagina
    assert "<strong>1</strong> já venceu sem envio" in pagina

    enviados = logado.get(url, {"situacao": "enviado"}).content.decode()
    assert enviado.get_absolute_url() in enviados and a_enviar.get_absolute_url() not in enviados

    todos = logado.get(url, {"situacao": "todos"}).content.decode()
    assert todos.count("/boletos/") >= 3 and "Cancelado" in todos and "Enviado" in todos


def test_filtros_por_mes_tipo_contrato_e_fora_do_vencimento(logado, com_boleto, dental):
    outubro = boleto(com_boleto)
    novembro = boleto(com_boleto, referencia=date(2026, 11, 1))
    fora = boleto(dental, tipo="REA", vencimento=date(2026, 10, 28))
    url = reverse("boletos:lista")

    def mostra(**filtros) -> set:
        pagina = logado.get(url, {"situacao": "enviar", **filtros}).content.decode()
        return {b for b in (outubro, novembro, fora) if b.get_absolute_url() in pagina}

    assert mostra(mes="10/2026") == {outubro, fora}
    assert mostra(tipo="REA") == {fora}
    assert mostra(fora="on") == {fora}
    assert mostra(contrato=com_boleto.pk) == {outubro, novembro}
    assert "Mês inválido" in logado.get(url, {"mes": "13/2026"}).content.decode()


def test_enviado_hoje_pela_lista(logado, com_boleto, usuario):
    novo = boleto(com_boleto)
    url = reverse("boletos:enviado_hoje", args=[novo.pk])
    volta = reverse("boletos:lista") + "?mes=10/2026"

    resposta = logado.post(url, {"proximo": volta})
    assert resposta.status_code == 302 and resposta.url == volta
    novo.refresh_from_db()
    assert novo.enviado_em == HOJE and novo.enviado_por == usuario

    # Clicar de novo não muda nada, e endereço de fora não é seguido.
    resposta = logado.post(url, {"proximo": "https://exemplo.invalid/"})
    assert resposta.url == reverse("boletos:lista")
    assert logado.get(url).status_code == 405


def test_registrar_envio_pela_tela(logado, com_boleto, contato_rh, usuario):
    novo = boleto(com_boleto)
    url = reverse("boletos:registrar_envio", args=[novo.pk])
    formulario = logado.get(url).content.decode()
    assert f'<option value="{contato_rh.pk}" selected>' in formulario  # o contato principal
    assert f'value="{HOJE:%d/%m/%Y}"' in formulario

    resposta = logado.post(url, {"enviado_em": "05/10/2026", "enviado_para": contato_rh.pk})
    assert resposta.status_code == 302
    novo.refresh_from_db()
    assert novo.enviado_em == date(2026, 10, 5) and novo.enviado_para == contato_rh
    assert novo.enviado_por == usuario
    # Depois de enviado (ou cancelado), a tela de envio não abre mais.
    assert logado.get(url).status_code == 404


def test_pessoa_fisica_nao_tem_campo_de_contato(logado, pessoa, seguradora):
    plano = contrato(pessoa, seguradora, "Vida", "V-1", [])
    novo = boleto(plano)
    pagina = logado.get(reverse("boletos:registrar_envio", args=[novo.pk])).content.decode()
    assert 'name="enviado_em"' in pagina and 'name="enviado_para"' not in pagina


def test_editar_e_desfazer_envio(logado, com_boleto, usuario):
    novo = boleto(com_boleto)
    novo.registrar_envio(usuario)
    resposta = logado.post(
        reverse("boletos:editar", args=[novo.pk]),
        {"tipo": "MEN", "referencia": "10/2026", "vencimento": "10/10/2026", "enviado_em": ""},
    )
    assert resposta.status_code == 302
    novo.refresh_from_db()
    assert novo.situacao == Situacao.A_ENVIAR and novo.enviado_por is None


def test_gerar_pela_tela(logado, com_boleto):
    url = reverse("boletos:gerar")
    formulario = logado.get(url).content.decode()
    assert f'value="{HOJE:%m/%Y}"' in formulario
    assert f'value="{somar_meses(HOJE, 11):%m/%Y}"' in formulario
    assert ">Gerar boletos</button>" in formulario

    resposta = logado.post(url, {"de": "10/2026", "ate": "10/2026"}, follow=True)
    assert resposta.redirect_chain[-1][0] == reverse("boletos:lista") + "?mes=10%2F2026"
    assert "1 boleto criado para 10/2026." in resposta.content.decode()

    de_novo = logado.post(url, {"de": "10/2026", "ate": "12/2026"}, follow=True)
    assert de_novo.redirect_chain[-1][0] == reverse("boletos:lista") + "?situacao=enviar"
    assert "2 boletos criados para 10/2026 a 12/2026. 1 já existia." in de_novo.content.decode()
    assert Boleto.objects.count() == 3


@pytest.mark.parametrize(
    "ate, erro", [("09/2026", "igual ou depois do primeiro"), ("10/2027", "no máximo 12 meses")]
)
def test_periodo_invalido_para_gerar(logado, com_boleto, ate, erro):
    resposta = logado.post(reverse("boletos:gerar"), {"de": "10/2026", "ate": ate})
    assert resposta.status_code == 200 and erro in resposta.content.decode()
    assert not Boleto.objects.exists()


def test_gerar_sem_contratos_com_envio(logado, saude):
    dados = {"de": "10/2026", "ate": "12/2026"}
    resposta = logado.post(reverse("boletos:gerar"), dados, follow=True)
    assert "Nenhum boleto criado" in resposta.content.decode()


def test_novo_boleto_pela_tela(logado, com_boleto, usuario):
    url = reverse("boletos:novo")
    formulario = logado.get(url, {"contrato": com_boleto.pk}).content.decode()
    assert f'<option value="{com_boleto.pk}" selected>' in formulario

    resposta = logado.post(
        url,
        {"contrato": com_boleto.pk, "tipo": "COP", "referencia": "10/2026", "vencimento": ""},
    )
    novo = Boleto.objects.get()
    assert resposta.url == novo.get_absolute_url()
    assert novo.tipo == "COP" and novo.vencimento == date(2026, 10, 10)
    assert novo.registrado_por == usuario


def test_campo_de_mes_tem_a_marca_para_a_barra_automatica(logado):
    """O script dos campos de data (static/js/campos-data.js) formata os data-campo-mes."""
    pagina = logado.get(reverse("boletos:novo")).content.decode()
    campo = re.search(r'<input[^>]*name="referencia"[^>]*>', pagina).group(0)
    assert "data-campo-mes" in campo and 'placeholder="mm/aaaa"' in campo
    assert f'value="{HOJE:%m/%Y}"' in campo


def test_pagina_do_boleto_mostra_o_historico(logado, com_boleto, usuario):
    novo = boleto(com_boleto)
    logado.post(reverse("boletos:enviado_hoje", args=[novo.pk]))
    pagina = logado.get(novo.get_absolute_url()).content.decode()
    assert "situação: Enviado" in pagina and "Ana Lima" in pagina


def test_contrato_com_envio_pela_corretora_tem_link_para_os_boletos(logado, com_boleto, dental):
    pagina = logado.get(com_boleto.cliente.get_absolute_url()).content.decode()
    assert f"?contrato={com_boleto.pk}&situacao=todos" in pagina
    assert f"?contrato={dental.pk}&situacao=todos" not in pagina


def test_mensalidade_repetida_pela_tela_mostra_o_erro(logado, com_boleto):
    boleto(com_boleto)
    resposta = logado.post(
        reverse("boletos:novo"),
        {"contrato": com_boleto.pk, "tipo": "MEN", "referencia": "10/2026", "vencimento": ""},
    )
    assert resposta.status_code == 200
    assert "Este contrato já tem a mensalidade deste mês." in resposta.content.decode()
    assert Boleto.objects.count() == 1


def test_edicao_nao_deixa_duas_mensalidades_no_mes(logado, com_boleto):
    cancelada = boleto(com_boleto, cancelado=True)
    boleto(com_boleto, vencimento=date(2026, 10, 20))
    setembro = boleto(com_boleto, referencia=date(2026, 9, 1))
    dados = {"tipo": "MEN", "referencia": "10/2026", "vencimento": "10/10/2026"}
    for editado, extra in [(cancelada, {"cancelado": ""}), (setembro, {})]:
        resposta = logado.post(reverse("boletos:editar", args=[editado.pk]), dados | extra)
        assert resposta.status_code == 200
        assert "Este contrato já tem a mensalidade deste mês." in resposta.content.decode()


def test_lista_padrao_mostra_os_proximos_30_dias(logado, com_boleto):
    perto = boleto(com_boleto, tipo="COP", vencimento=HOJE + timedelta(days=30))
    longe = boleto(com_boleto, tipo="REA", vencimento=HOJE + timedelta(days=31))
    url = reverse("boletos:lista")

    padrao = logado.get(url).content.decode()
    assert perto.get_absolute_url() in padrao and longe.get_absolute_url() not in padrao
    assert f"<strong>1</strong> a enviar até {HOJE + timedelta(days=30):%d/%m}" in padrao
    todos_os_meses = logado.get(url, {"situacao": "enviar"}).content.decode()
    assert longe.get_absolute_url() in todos_os_meses
    # Escolhendo o mês, aparece o mês inteiro.
    assert longe.get_absolute_url() in logado.get(url, {"mes": "10/2026"}).content.decode()


# ------------------------------------------------------------------
# Mudanças no contrato
# ------------------------------------------------------------------


def editar_contrato(cliente_http, plano, **mudancas):
    dados = {
        "seguradora": plano.seguradora_id,
        "ramo": plano.ramo_id,
        "numero": plano.numero,
        "modalidade": plano.modalidade,
        "situacao": plano.situacao,
        "inicio_vigencia": f"{plano.inicio_vigencia:%d/%m/%Y}",
        "dia_vencimento": plano.dia_vencimento,
        "corretora_envia_boleto": "on",
        "unidades": [unidade.pk for unidade in plano.unidades.all()],
        **mudancas,
    }
    url = reverse("apolices:editar_contrato", args=[plano.pk])
    return cliente_http.post(url, dados, follow=True).content.decode()


def test_novo_vencimento_do_contrato_vale_para_as_mensalidades_a_enviar(
    logado, com_boleto, usuario
):
    passada = boleto(com_boleto, referencia=somar_meses(HOJE, -1))
    Boleto.gerar_mensalidades(somar_meses(HOJE, 1), somar_meses(HOJE, 2))
    enviada = boleto(com_boleto, referencia=somar_meses(HOJE, 3))
    enviada.registrar_envio(usuario)
    mes_da_fora = somar_meses(HOJE, 4)
    fora = boleto(com_boleto, referencia=mes_da_fora, vencimento=mes_da_fora.replace(day=20))
    copart = boleto(com_boleto, tipo="COP", referencia=somar_meses(HOJE, 1))

    pagina = editar_contrato(logado, com_boleto, dia_vencimento=15)
    assert "2 mensalidades a enviar passaram para o novo vencimento." in pagina
    meses_gerados = [somar_meses(HOJE, 1), somar_meses(HOJE, 2)]
    geradas = Boleto.objects.filter(tipo="MEN", referencia__in=meses_gerados).order_by("referencia")
    assert [b.vencimento.day for b in geradas] == [15, 15]
    assert not any(b.fora_do_vencimento for b in geradas)
    for intocado in (passada, enviada, fora, copart):
        antes = intocado.vencimento
        intocado.refresh_from_db()
        assert intocado.vencimento == antes


def test_cancelar_o_contrato_cancela_as_mensalidades_dos_proximos_meses(logado, com_boleto):
    deste_mes = boleto(com_boleto, referencia=HOJE)
    Boleto.gerar_mensalidades(somar_meses(HOJE, 1), somar_meses(HOJE, 3))
    copart = boleto(com_boleto, tipo="COP", referencia=somar_meses(HOJE, 1))

    pagina = editar_contrato(logado, com_boleto, situacao="CAN")
    assert "3 mensalidades a enviar dos próximos meses foram canceladas" in pagina
    canceladas = Boleto.objects.cancelados()
    assert canceladas.count() == 3
    assert all(b.observacao == "Cancelado junto com o contrato." for b in canceladas)
    for continua in (deste_mes, copart):
        continua.refresh_from_db()
        assert continua.situacao == Situacao.A_ENVIAR

    lista = logado.get(reverse("boletos:lista"), {"situacao": "enviar"}).content.decode()
    assert "contrato cancelado" in lista
