"""Exclusão de contrato cadastrado por engano: digitando o nome, só para administradores e sem
apagar pessoas, movimentações, boletos ou pendências."""

from datetime import date

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apolices.models import BemSegurado, Contrato, Plano, Subfatura
from beneficiarios.models import Vinculo
from beneficiarios.tests.fixtures import incluir
from boletos.models import Boleto
from clientes.models import DocumentoDoCliente
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia

pytestmark = pytest.mark.django_db

NOME = "Seguradora Exemplo SAU-001"


def url_de(contrato):
    return reverse("apolices:excluir_contrato", args=[contrato.pk])


def test_administrador_exclui_digitando_o_nome(admin, contrato_empresa, empresa):
    pagina = admin.get(url_de(contrato_empresa)).content.decode()
    assert NOME in pagina
    assert "Esta ação não pode ser desfeita" in pagina
    resposta = admin.post(url_de(contrato_empresa), {"confirmacao": " seguradora exemplo  sau-001"})
    assert resposta.status_code == 302
    assert resposta.url == f"{empresa.get_absolute_url()}#contratos"
    assert not Contrato.objects.exists()
    exclusao = Contrato.history.filter(history_type="-").get()
    assert exclusao.history_user.username == "chefe"
    assert exclusao.numero == "SAU-001"


def test_texto_errado_nao_exclui(admin, contrato_empresa):
    resposta = admin.post(url_de(contrato_empresa), {"confirmacao": "SAU-001"})
    assert resposta.status_code == 200
    assert "não confere" in resposta.content.decode()
    assert Contrato.objects.filter(pk=contrato_empresa.pk).exists()


def test_sem_permissao_nao_ve_o_botao_nem_exclui(logado, contrato_empresa, empresa):
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert url_de(contrato_empresa) not in pagina
    assert logado.get(url_de(contrato_empresa)).status_code == 403
    assert logado.post(url_de(contrato_empresa), {"confirmacao": NOME}).status_code == 403
    assert Contrato.objects.filter(pk=contrato_empresa.pk).exists()


def test_permissao_de_excluir_contrato_basta(logado, usuario, contrato_empresa, empresa):
    usuario.user_permissions.add(Permission.objects.get(codename="delete_contrato"))
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert url_de(contrato_empresa) in pagina
    assert f"Excluir contrato {NOME}" in pagina


def test_botao_fica_na_caixa_de_exclusao_no_fim_da_pagina(admin, contrato_empresa, empresa):
    pagina = admin.get(empresa.get_absolute_url()).content.decode()
    assert pagina.index("Excluir registros") < pagina.index(url_de(contrato_empresa))


def test_planos_subfaturas_e_bens_saem_junto(admin, contrato_empresa, filial):
    Plano.objects.create(contrato=contrato_empresa, nome="TNPQ")
    Plano.objects.create(contrato=contrato_empresa, nome="TNP4")
    Subfatura.objects.create(contrato=contrato_empresa, unidade=filial, identificador="7")
    BemSegurado.objects.create(contrato=contrato_empresa, tipo="IMO", descricao="Galpão")
    pagina = admin.get(url_de(contrato_empresa)).content.decode()
    assert "Os 2 planos serão excluídos junto com o contrato." in pagina
    assert "A subfatura (SUB) será excluída junto com o contrato." in pagina
    assert "O veículo ou imóvel será excluído junto com o contrato." in pagina
    admin.post(url_de(contrato_empresa), {"confirmacao": NOME})
    assert not Contrato.objects.exists()
    assert not Plano.objects.exists()
    assert not Subfatura.objects.exists()
    assert not BemSegurado.objects.exists()


def test_documento_do_cliente_fica(admin, contrato_empresa, empresa, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    documento = DocumentoDoCliente.objects.create(
        cliente=empresa,
        tipo="CON",
        contrato=contrato_empresa,
        arquivo=SimpleUploadedFile("contrato.pdf", b"%PDF-1.4"),
        nome_original="contrato.pdf",
    )
    pagina = admin.get(url_de(contrato_empresa)).content.decode()
    assert "continua lá, sem a ligação com o contrato" in pagina
    admin.post(url_de(contrato_empresa), {"confirmacao": NOME})
    documento.refresh_from_db()
    assert documento.contrato is None
    assert documento.arquivo.storage.exists(documento.arquivo.name)


def test_pessoas_no_contrato_impedem(admin, contrato_empresa, titular):
    incluir(titular, contrato_empresa)
    pagina = admin.get(url_de(contrato_empresa)).content.decode()
    assert "Não é possível excluir" in pagina
    assert "1 inclusão de pessoa neste contrato" in pagina
    assert "mude a situação para Cancelado" in pagina
    assert "Excluir definitivamente" not in pagina
    admin.post(url_de(contrato_empresa), {"confirmacao": NOME})
    assert Contrato.objects.filter(pk=contrato_empresa.pk).exists()
    assert Vinculo.objects.exists()


@pytest.mark.parametrize("registro", ["movimentacao", "boleto", "pendencia"])
def test_historico_da_carteira_impede(admin, usuario, contrato_empresa, empresa, titular, registro):
    hoje = date.today()
    if registro == "movimentacao":
        Movimentacao.objects.create(
            tipo="INC", beneficiario=titular, contrato=contrato_empresa, enviada_em=hoje
        )
    elif registro == "boleto":
        Boleto.objects.create(contrato=contrato_empresa, referencia=hoje.replace(day=1))
    else:
        Pendencia.objects.create(
            cliente=empresa,
            descricao="Conferir a fatura",
            responsavel=usuario,
            prazo=hoje,
            contrato=contrato_empresa,
        )
    resposta = admin.post(url_de(contrato_empresa), {"confirmacao": NOME})
    assert resposta.status_code == 200
    assert "Não é possível excluir" in resposta.content.decode()
    assert Contrato.objects.filter(pk=contrato_empresa.pk).exists()


def test_registro_ligado_depois_da_conferencia_nao_vira_erro(admin, contrato_empresa, titular):
    """Se alguém incluir uma pessoa num plano do contrato no meio da exclusão, nada se perde."""
    plano = Plano.objects.create(contrato=contrato_empresa, nome="TNPQ")
    vinculo = incluir(titular, contrato_empresa)
    Vinculo.objects.filter(pk=vinculo.pk).update(plano=plano)
    contrato_empresa.bloqueios_para_excluir = lambda: []
    with pytest.raises(ValidationError, match="Não é possível excluir"):
        contrato_empresa.excluir()
    assert Contrato.objects.filter(pk=contrato_empresa.pk).exists()
    assert Plano.objects.filter(pk=plano.pk).exists()
