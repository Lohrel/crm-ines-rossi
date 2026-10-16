"""Documentos anexados ao cliente: contrato assinado, aditivos, cartão CNPJ..."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apolices.models import Contrato, Ramo, Seguradora
from clientes.models import Cliente, DocumentoDoCliente

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def pasta_de_anexos(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def pdf(nome="contrato.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4 teste", content_type="application/pdf")


def anexar(cliente, nome="contrato.pdf", **campos):
    return DocumentoDoCliente.objects.create(
        cliente=cliente, tipo="CON", arquivo=pdf(nome), nome_original=nome, **campos
    )


@pytest.fixture
def contrato(empresa):
    return Contrato.objects.create(
        cliente=empresa,
        seguradora=Seguradora.objects.create(nome="Seguradora Exemplo"),
        ramo=Ramo.objects.get(nome="Saúde"),
        numero="SAU-001",
        produto="PLENO",
        modalidade="EM",
        inicio_vigencia="2026-01-01",
        dia_vencimento=10,
    )


def test_anexar_e_baixar_documento(logado, empresa, contrato, pasta_de_anexos):
    resposta = logado.post(
        reverse("clientes:novo_documento", args=[empresa.pk]),
        {
            "tipo": "CON",
            "contrato": contrato.pk,
            "descricao": "Contrato 2026",
            "arquivo": pdf("Contrato Supermercados.pdf"),
        },
    )
    assert resposta.status_code == 302
    assert resposta.url == f"{empresa.get_absolute_url()}#documentos"
    documento = DocumentoDoCliente.objects.get()
    assert documento.nome_original == "Contrato Supermercados.pdf"
    assert documento.enviado_por.username == "ana"
    assert documento.contrato == contrato
    # Fora da pasta pública, com nome aleatório, dentro da pasta que o backup copia.
    assert documento.arquivo.name.startswith(f"clientes/{empresa.pk}/")
    assert "Supermercados" not in documento.arquivo.name
    assert (Path(pasta_de_anexos) / documento.arquivo.name).exists()

    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Contrato 2026" in pagina
    assert "por Ana Lima" in pagina
    assert "Saúde · PLENO" in pagina
    assert "criou Documento do cliente: Contrato 2026" in pagina

    download = logado.get(reverse("clientes:baixar_documento", args=[documento.pk]))
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"%PDF-1.4 teste"
    assert "attachment" in download["Content-Disposition"]
    assert "no-store" in download["Cache-Control"]


def test_pessoa_fisica_tambem_tem_documentos(logado, pessoa):
    resposta = logado.post(
        reverse("clientes:novo_documento", args=[pessoa.pk]),
        {"tipo": "PES", "arquivo": pdf("rg.pdf")},
    )
    assert resposta.status_code == 302
    assert pessoa.documentos.get().nome_original == "rg.pdf"
    # Sem contratos, o campo de contrato nem aparece.
    formulario = logado.get(reverse("clientes:novo_documento", args=[pessoa.pk]))
    assert "contrato" not in formulario.context["form"].fields


def test_contrato_de_outro_cliente_nao_e_aceito(logado, empresa, contrato):
    outra = Cliente.objects.create(tipo="PJ", nome="Outra Empresa")
    Contrato.objects.create(
        cliente=outra,
        seguradora=contrato.seguradora,
        ramo=contrato.ramo,
        numero="SAU-002",
        modalidade="EM",
        inicio_vigencia="2026-01-01",
        dia_vencimento=10,
    )
    da_outra = outra.contratos.get()
    resposta = logado.post(
        reverse("clientes:novo_documento", args=[empresa.pk]),
        {"tipo": "CON", "contrato": da_outra.pk, "arquivo": pdf()},
    )
    assert resposta.status_code == 200
    assert not DocumentoDoCliente.objects.exists()


def test_documento_exige_login(client, pessoa):
    documento = anexar(pessoa)
    resposta = client.get(reverse("clientes:baixar_documento", args=[documento.pk]))
    assert resposta.status_code == 302
    assert "/entrar/" in resposta.url


def test_tipo_de_arquivo_nao_permitido(logado, pessoa):
    arquivo = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")
    resposta = logado.post(
        reverse("clientes:novo_documento", args=[pessoa.pk]), {"tipo": "OUT", "arquivo": arquivo}
    )
    assert resposta.status_code == 200
    assert not DocumentoDoCliente.objects.exists()


def test_planilha_do_excel_e_aceita(logado, pessoa):
    planilha = SimpleUploadedFile("tabela.xlsx", b"PK", content_type="application/octet-stream")
    logado.post(
        reverse("clientes:novo_documento", args=[pessoa.pk]), {"tipo": "OUT", "arquivo": planilha}
    )
    assert DocumentoDoCliente.objects.exists()


def test_arquivo_grande_demais(logado, pessoa, settings):
    settings.TAMANHO_MAXIMO_ANEXO_MB = 0
    resposta = logado.post(
        reverse("clientes:novo_documento", args=[pessoa.pk]), {"tipo": "CON", "arquivo": pdf()}
    )
    assert resposta.status_code == 200
    assert not DocumentoDoCliente.objects.exists()


def test_so_administrador_exclui_documento(logado, pessoa):
    documento = anexar(pessoa)
    assert "Excluir documento" not in logado.get(pessoa.get_absolute_url()).content.decode()
    url = reverse("clientes:excluir_documento", args=[documento.pk])
    assert logado.post(url, {"confirmacao": "contrato.pdf"}).status_code == 403
    assert DocumentoDoCliente.objects.exists()


def test_excluir_documento_apaga_o_arquivo(
    admin, pessoa, pasta_de_anexos, django_capture_on_commit_callbacks
):
    documento = anexar(pessoa)
    caminho = Path(pasta_de_anexos) / documento.arquivo.name
    assert "Excluir documento contrato.pdf" in admin.get(pessoa.get_absolute_url()).content.decode()
    url = reverse("clientes:excluir_documento", args=[documento.pk])

    assert admin.post(url, {"confirmacao": "outro"}).status_code == 200
    assert caminho.exists()

    with django_capture_on_commit_callbacks(execute=True):
        resposta = admin.post(url, {"confirmacao": "contrato.pdf"})
    assert resposta.url == f"{pessoa.get_absolute_url()}#documentos"
    assert not DocumentoDoCliente.objects.exists()
    assert not caminho.exists()
    historico = admin.get(pessoa.get_absolute_url()).content.decode()
    assert "removeu Documento do cliente: contrato.pdf" in historico


def test_excluir_cliente_apaga_os_documentos(
    admin, pessoa, pasta_de_anexos, django_capture_on_commit_callbacks
):
    caminho = Path(pasta_de_anexos) / anexar(pessoa).arquivo.name
    url = reverse("clientes:excluir", args=[pessoa.pk])
    assert "O documento anexado também será apagado" in admin.get(url).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(url, {"confirmacao": pessoa.nome})
    assert not Cliente.objects.exists()
    assert not DocumentoDoCliente.objects.exists()
    assert not caminho.exists()


def test_cliente_com_contrato_continua_bloqueado(admin, empresa, contrato, pasta_de_anexos):
    caminho = Path(pasta_de_anexos) / anexar(empresa).arquivo.name
    admin.post(reverse("clientes:excluir", args=[empresa.pk]), {"confirmacao": empresa.nome})
    assert Cliente.objects.filter(pk=empresa.pk).exists()
    assert DocumentoDoCliente.objects.exists()
    assert caminho.exists()
