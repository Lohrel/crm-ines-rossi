"""Etapa 20: cadastrar a pessoa e pedir a inclusão nos planos na mesma tela."""

from datetime import date

import pytest
from django.urls import reverse

from apolices.models import Plano
from beneficiarios.models import Beneficiario
from beneficiarios.tests.fixtures import incluir
from movimentacoes.models import Movimentacao

pytestmark = pytest.mark.django_db

HOJE = date.today()


def novo_titular(cliente_http, empresa, filial, **pedido):
    dados = {"nome": "Nina Nova", "unidade": filial.pk}
    dados.update({f"pedido-{campo}": valor for campo, valor in pedido.items()})
    return cliente_http.post(reverse("beneficiarios:novo_titular", args=[empresa.pk]), dados)


def test_tela_do_titular_traz_o_pedido_com_os_planos_do_cliente(logado, empresa, saude, dental):
    resposta = logado.get(reverse("beneficiarios:novo_titular", args=[empresa.pk]))
    pagina = resposta.content.decode()
    assert "Pedido de inclusão (opcional)" in pagina
    assert "Saúde · Seguradora Exemplo S-1" in pagina
    assert "Dental · Seguradora Exemplo D-1" in pagina
    # A data de recebimento e a de envio já vêm com o dia de hoje.
    assert f'value="{HOJE:%d/%m/%Y}"' in pagina


def test_sem_plano_marcado_so_cadastra_a_pessoa(logado, empresa, filial, saude):
    resposta = novo_titular(logado, empresa, filial)
    nina = Beneficiario.objects.get(nome="Nina Nova")
    assert resposta["Location"] == nina.get_absolute_url()
    assert not Movimentacao.objects.exists()


def test_cadastra_e_pede_a_inclusao_em_dois_planos(
    logado, empresa, filial, saude, dental, contato_rh
):
    resposta = novo_titular(
        logado,
        empresa,
        filial,
        planos=[saude.pk, dental.pk],
        solicitante=contato_rh.pk,
        recebida_em="03/11/2026",
        enviada_em="04/11/2026",
        observacao="Admissão",
    )
    nina = Beneficiario.objects.get(nome="Nina Nova")
    assert resposta["Location"] == nina.get_absolute_url()
    pedidos = Movimentacao.objects.filter(beneficiario=nina).order_by("contrato__numero")
    assert [p.contrato for p in pedidos] == [dental, saude]
    for pedido in pedidos:
        assert pedido.tipo == Movimentacao.Tipo.INCLUSAO
        assert pedido.etapa == "ANA"
        assert pedido.solicitante == contato_rh
        assert pedido.enviada_em == date(2026, 11, 4)
        assert pedido.observacao == "Admissão"
        # Sem vigência digitada, vale a do contrato (dia 1º do mês seguinte).
        assert pedido.vigencia == date(2026, 12, 1)
    mensagem = [str(m) for m in resposta.wsgi_request._messages]
    assert mensagem == ["Titular cadastrado e 2 pedidos de inclusão registrados (Em análise)."]


def test_pedido_sem_data_de_envio_nao_grava_nada(logado, empresa, filial, saude):
    resposta = novo_titular(logado, empresa, filial, planos=[saude.pk], enviada_em="")
    assert resposta.status_code == 200
    assert "Informe quando o pedido foi enviado à operadora." in resposta.content.decode()
    assert not Beneficiario.objects.filter(nome="Nina Nova").exists()


def test_erro_no_cadastro_mostra_tambem_o_erro_do_pedido(logado, empresa, filial, saude):
    dados = {"nome": "", "unidade": filial.pk, "pedido-planos": [saude.pk]}
    dados["pedido-enviada_em"] = ""
    resposta = logado.post(reverse("beneficiarios:novo_titular", args=[empresa.pk]), dados)
    pagina = resposta.content.decode()
    assert resposta.status_code == 200
    assert "Informe quando o pedido foi enviado à operadora." in pagina
    assert not Beneficiario.objects.exists()


def test_contrato_com_planos_marca_um_so(logado, empresa, filial, saude):
    tnpq = Plano.objects.create(contrato=saude, nome="TNPQ")
    tnp4 = Plano.objects.create(contrato=saude, nome="TNP4")
    pagina = logado.get(reverse("beneficiarios:novo_titular", args=[empresa.pk])).content
    assert "S-1 · plano TNPQ" in pagina.decode()
    resposta = novo_titular(
        logado, empresa, filial, planos=[f"p{tnpq.pk}", f"p{tnp4.pk}"], enviada_em="04/11/2026"
    )
    assert "Marque um só plano de cada contrato." in resposta.content.decode()
    assert not Beneficiario.objects.filter(nome="Nina Nova").exists()
    novo_titular(logado, empresa, filial, planos=[f"p{tnp4.pk}"], enviada_em="04/11/2026")
    pedido = Movimentacao.objects.get(beneficiario__nome="Nina Nova")
    assert (pedido.contrato, pedido.plano) == (saude, tnp4)


def test_dependente_so_ve_os_planos_do_titular(logado, titular, saude, dental):
    incluir(titular, saude)
    url = reverse("beneficiarios:novo_dependente", args=[titular.pk])
    pagina = logado.get(url).content.decode()
    assert "Saúde · Seguradora Exemplo S-1" in pagina
    assert "Dental · Seguradora Exemplo D-1" not in pagina
    resposta = logado.post(
        url,
        {
            "nome": "Dora Dependente",
            "parentesco": "FI",
            "pedido-planos": [saude.pk],
            "pedido-enviada_em": "04/11/2026",
        },
    )
    dora = Beneficiario.objects.get(nome="Dora Dependente")
    assert resposta["Location"] == dora.get_absolute_url()
    assert Movimentacao.objects.get(beneficiario=dora).contrato == saude


def test_cliente_sem_contrato_vigente_nao_mostra_o_pedido(logado, empresa, filial):
    pagina = logado.get(reverse("beneficiarios:novo_titular", args=[empresa.pk])).content
    assert "Pedido de inclusão" not in pagina.decode()


def test_nova_inclusao_pela_lista_de_movimentacoes(logado, empresa, saude, pessoa):
    lista = logado.get(reverse("movimentacoes:lista")).content.decode()
    assert reverse("movimentacoes:nova_inclusao") in lista
    resposta = logado.get(reverse("movimentacoes:nova_inclusao"))
    # Só aparece quem tem contrato de saúde, dental ou vida em vigor.
    assert list(resposta.context["object_list"]) == [empresa]
    pagina = resposta.content.decode()
    assert reverse("beneficiarios:novo_titular", args=[empresa.pk]) in pagina
