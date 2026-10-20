import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apolices.models import Contrato, Ramo
from beneficiarios.models import Anexo, Beneficiario, Vinculo
from beneficiarios.tests.fixtures import HOJE, ONTEM, contrato, incluir
from beneficiarios.vidas import VidasDoCliente, anotar_vidas
from clientes.tests.fixtures import CPF_1, CPF_2

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def pasta_de_anexos(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


# ------------------------------------------------------------------
# Regras do cadastro
# ------------------------------------------------------------------


def test_titular_de_empresa_precisa_de_unidade(empresa):
    with pytest.raises(ValidationError, match="unidade"):
        Beneficiario(cliente=empresa, nome="Sem unidade").full_clean()


def test_dependente_precisa_de_parentesco(titular):
    with pytest.raises(ValidationError):
        Beneficiario(cliente=titular.cliente, titular=titular, nome="X").full_clean()


def test_dependente_de_dependente_e_barrado(conjuge):
    with pytest.raises(ValidationError, match="dependente de outra pessoa"):
        Beneficiario(
            cliente=conjuge.cliente, titular=conjuge, parentesco="FI", nome="Neto"
        ).full_clean()


def test_cpf_repetido_no_mesmo_cliente_e_barrado(titular):
    with pytest.raises(ValidationError, match="CPF"):
        Beneficiario(
            cliente=titular.cliente, unidade=titular.unidade, nome="Outra", cpf=CPF_1
        ).full_clean()


def test_plano_de_outro_cliente_e_barrado(titular, pessoa, seguradora):
    alheio = Contrato.objects.create(
        cliente=pessoa,
        seguradora=seguradora,
        ramo=Ramo.objects.get(nome="Vida"),
        numero="V-9",
        modalidade="IF",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=1,
    )
    with pytest.raises(ValidationError, match="mesmo cliente"):
        incluir(titular, alheio)


def test_plano_que_nao_cobre_a_filial_e_barrado(titular, empresa, seguradora, matriz):
    so_matriz = contrato(empresa, seguradora, "Saúde", "S-M", [matriz])
    with pytest.raises(ValidationError, match="não cobre a unidade"):
        incluir(titular, so_matriz)


def test_dependente_so_entra_em_plano_do_titular(titular, conjuge, saude, dental):
    incluir(titular, saude)
    incluir(conjuge, saude)
    with pytest.raises(ValidationError, match="titular não está neste plano"):
        incluir(conjuge, dental)


def test_mesmo_plano_duas_vezes_e_barrado(titular, saude):
    incluir(titular, saude)
    with pytest.raises(ValidationError, match="já está neste plano"):
        incluir(titular, saude)


def test_titular_excluido_leva_os_dependentes_so_daquele_plano(
    titular, conjuge, filho, saude, dental
):
    plano_saude = incluir(titular, saude)
    incluir(titular, dental)
    incluir(conjuge, saude)
    incluir(conjuge, dental)
    incluir(filho, saude)
    encerrados = plano_saude.encerrar(HOJE)
    assert len(encerrados) == 3
    assert not Vinculo.objects.filter(contrato=saude).ativos(HOJE).exists()
    assert Vinculo.objects.filter(contrato=dental).ativos(HOJE).count() == 2


# ------------------------------------------------------------------
# Número de vidas
# ------------------------------------------------------------------


def test_vidas_por_contrato_filial_e_grupo(
    empresa, matriz, filial, titular, conjuge, filho, saude, dental
):
    incluir(titular, saude)
    incluir(titular, dental)
    incluir(conjuge, saude)  # cônjuge só na saúde
    incluir(filho, saude)
    incluir(filho, dental)
    na_matriz = Beneficiario.objects.create(cliente=empresa, unidade=matriz, nome="Davi Matriz")
    incluir(na_matriz, dental)
    saiu = Beneficiario.objects.create(cliente=empresa, unidade=matriz, nome="Eva Saiu")
    incluir(saiu, saude, inclusao=date(2026, 1, 1), exclusao=HOJE)
    futuro = Beneficiario.objects.create(cliente=empresa, unidade=matriz, nome="Fábio Futuro")
    incluir(futuro, saude, inclusao=HOJE + timedelta(days=10))

    vidas = VidasDoCliente(empresa)
    assert vidas.por_contrato == {saude.pk: 3, dental.pk: 3}
    assert vidas.por_celula[(filial.pk, saude.pk)] == 3
    assert vidas.por_celula[(filial.pk, dental.pk)] == 2
    assert vidas.por_celula[(matriz.pk, dental.pk)] == 1
    assert vidas.da_unidade(filial.pk) == 3
    assert vidas.da_unidade(matriz.pk) == 1
    assert vidas.total_pessoas == 4

    contratos = {c.pk: c.vidas for c in anotar_vidas(Contrato.objects.all())}
    assert contratos == {saude.pk: 3, dental.pk: 3}


def test_vidas_em_data_passada(empresa, matriz, saude):
    saiu = Beneficiario.objects.create(cliente=empresa, unidade=matriz, nome="Eva")
    incluir(saiu, saude, inclusao=date(2026, 1, 1), exclusao=date(2026, 3, 1))
    assert VidasDoCliente(empresa, em=date(2026, 2, 1)).total_pessoas == 1
    assert VidasDoCliente(empresa, em=date(2026, 3, 1)).total_pessoas == 0


# ------------------------------------------------------------------
# Telas
# ------------------------------------------------------------------


def test_cadastrar_titular_e_incluir_com_dependentes_escolhidos(
    logado, empresa, filial, saude, dental
):
    resposta = logado.post(
        reverse("beneficiarios:novo_titular", args=[empresa.pk]),
        {"nome": "Ana", "cpf": "529.982.247-25", "unidade": filial.pk},
    )
    assert resposta.status_code == 302
    ana = Beneficiario.objects.get(nome="Ana")
    assert ana.cpf == CPF_1

    logado.post(
        reverse("beneficiarios:novo_dependente", args=[ana.pk]),
        {"nome": "Bruno", "parentesco": "CJ", "cpf": CPF_2},
    )
    logado.post(
        reverse("beneficiarios:novo_dependente", args=[ana.pk]),
        {"nome": "Caio", "parentesco": "FI"},
    )
    bruno, caio = ana.dependentes.order_by("nome")

    logado.post(
        reverse("beneficiarios:novo_plano", args=[ana.pk]),
        {
            "contrato": saude.pk,
            "data_inclusao": ONTEM.isoformat(),
            "dependentes": [bruno.pk, caio.pk],
        },
    )
    logado.post(
        reverse("beneficiarios:novo_plano", args=[ana.pk]),
        {"contrato": dental.pk, "data_inclusao": ONTEM.isoformat(), "dependentes": [caio.pk]},
    )
    assert set(bruno.vinculos.values_list("contrato", flat=True)) == {saude.pk}
    assert set(caio.vinculos.values_list("contrato", flat=True)) == {saude.pk, dental.pk}

    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "3 vidas" in pagina


def test_dependente_so_ve_planos_do_titular(logado, titular, conjuge, saude, dental):
    incluir(titular, saude)
    pagina = logado.get(reverse("beneficiarios:novo_plano", args=[conjuge.pk])).content.decode()
    assert "S-1" in pagina and "D-1" not in pagina


def test_titular_com_cpf_ja_cadastrado_mostra_aviso(logado, empresa, filial, titular):
    resposta = logado.post(
        reverse("beneficiarios:novo_titular", args=[empresa.pk]),
        {"nome": "Ana de novo", "cpf": CPF_1, "unidade": filial.pk},
    )
    assert resposta.status_code == 200
    assert "já está cadastrado neste cliente, em Ana Titular" in resposta.content.decode()
    assert not Beneficiario.objects.filter(nome="Ana de novo").exists()


def test_dependente_com_cpf_ja_cadastrado_mostra_aviso(logado, titular):
    resposta = logado.post(
        reverse("beneficiarios:novo_dependente", args=[titular.pk]),
        {"nome": "Outra", "parentesco": "FI", "cpf": CPF_1},
    )
    assert resposta.status_code == 200
    assert "já está cadastrado neste cliente" in resposta.content.decode()


def test_editar_a_pessoa_mantendo_o_proprio_cpf(logado, titular, filial):
    resposta = logado.post(
        reverse("beneficiarios:editar", args=[titular.pk]),
        {"nome": "Ana Renomeada", "cpf": CPF_1, "unidade": filial.pk},
    )
    assert resposta.status_code == 302


def test_incluir_de_novo_no_mesmo_plano_mostra_aviso(logado, titular, saude):
    incluir(titular, saude)
    resposta = logado.post(
        reverse("beneficiarios:novo_plano", args=[titular.pk]),
        {"contrato": saude.pk, "data_inclusao": HOJE.isoformat()},
    )
    assert resposta.status_code == 200
    assert "Ana Titular já está neste plano" in resposta.content.decode()
    assert titular.vinculos.count() == 1


def test_reabrir_plano_antigo_quando_ja_ha_outro_aberto_mostra_aviso(logado, titular, saude):
    antigo = incluir(titular, saude, inclusao=ONTEM - timedelta(days=30), exclusao=ONTEM)
    incluir(titular, saude)
    resposta = logado.post(
        reverse("beneficiarios:editar_plano", args=[antigo.pk]),
        {"data_inclusao": antigo.data_inclusao.isoformat(), "data_exclusao": ""},
    )
    assert resposta.status_code == 200
    assert "já está neste plano" in resposta.content.decode()


def test_excluir_do_plano_pela_tela(logado, titular, conjuge, saude):
    plano = incluir(titular, saude)
    incluir(conjuge, saude)
    resposta = logado.post(
        reverse("beneficiarios:encerrar_plano", args=[plano.pk]),
        {"data_exclusao": HOJE.isoformat()},
    )
    assert resposta.status_code == 302
    assert not Vinculo.objects.ativos(HOJE).exists()


def test_lista_mostra_quadro_e_busca_dependente_pelo_cpf(logado, empresa, titular, conjuge, saude):
    conjuge.cpf = CPF_2
    conjuge.save()
    incluir(titular, saude)
    incluir(conjuge, saude)
    url = reverse("beneficiarios:lista", args=[empresa.pk])
    pagina = logado.get(url, {"q": "111.444"}).content.decode()
    assert "Ana Titular" in pagina and "Bruno Cônjuge" in pagina
    assert "Total do grupo" in pagina
    assert "Nenhum beneficiário" in logado.get(url, {"q": "ninguém"}).content.decode()


def test_lista_com_menos_ruido(logado, empresa, titular, conjuge, saude, dental):
    incluir(titular, saude)
    incluir(titular, dental)
    incluir(conjuge, saude)
    pagina = logado.get(reverse("beneficiarios:lista", args=[empresa.pk])).content.decode()
    # "Pessoas" vem logo depois da unidade, para o total nunca ficar escondido à direita.
    cabecalhos = re.findall(
        r"<th(?:\s[^>]*)?>([^<]+)", pagina.split("Vidas hoje")[1].split("</thead>")[0]
    )
    assert [c.strip() for c in cabecalhos] == ["Unidade", "Pessoas", "Dental", "Saúde"]
    # Sem o selo "Titular" em todas as linhas, e os planos em selos neutros (não verdes).
    assert ">Titular</span>" not in pagina
    assert '<span class="badge selo-plano me-1">Saúde</span>' in pagina
    assert "text-bg-success" not in pagina


def test_quem_saiu_de_todos_os_planos_so_aparece_quando_pedido(logado, empresa, titular, saude):
    incluir(titular, saude, inclusao=date(2026, 1, 1), exclusao=ONTEM)
    url = reverse("beneficiarios:lista", args=[empresa.pk])
    assert "Ana Titular" not in logado.get(url).content.decode()
    assert "Ana Titular" in logado.get(url, {"inativos": "on"}).content.decode()


def test_quem_ainda_nao_tem_plano_ou_entra_no_futuro_aparece_na_lista(
    logado, empresa, titular, filial, saude
):
    # Recém-cadastrada, sem plano: não pode sumir da lista.
    url = reverse("beneficiarios:lista", args=[empresa.pk])
    assert "Ana Titular" in logado.get(url).content.decode()
    outra = Beneficiario.objects.create(cliente=empresa, unidade=filial, nome="Bia Futura")
    incluir(outra, saude, inclusao=HOJE + timedelta(days=10))
    assert "Bia Futura" in logado.get(url).content.decode()


# ------------------------------------------------------------------
# Anexos
# ------------------------------------------------------------------


def pdf(nome="dps.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4 teste", content_type="application/pdf")


def test_anexar_e_baixar_arquivo(logado, titular, pasta_de_anexos):
    resposta = logado.post(
        reverse("beneficiarios:novo_anexo", args=[titular.pk]),
        {"tipo": "DPS", "arquivo": pdf("DPS Ana Titular.pdf")},
    )
    assert resposta.status_code == 302
    anexo = Anexo.objects.get()
    assert anexo.nome_original == "DPS Ana Titular.pdf"
    assert anexo.enviado_por.username == "ana"
    # No disco o nome é aleatório: o nome da pessoa não aparece no caminho.
    assert "Ana" not in anexo.arquivo.name
    assert (Path(pasta_de_anexos) / anexo.arquivo.name).exists()

    download = logado.get(reverse("beneficiarios:baixar_anexo", args=[anexo.pk]))
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"%PDF-1.4 teste"
    assert "attachment" in download["Content-Disposition"]
    assert "no-store" in download["Cache-Control"]


def test_anexo_exige_login(client, titular):
    anexo = Anexo.objects.create(
        beneficiario=titular, tipo="DPS", arquivo=pdf(), nome_original="dps.pdf"
    )
    resposta = client.get(reverse("beneficiarios:baixar_anexo", args=[anexo.pk]))
    assert resposta.status_code == 302
    assert "/entrar/" in resposta.url


def test_tipo_de_arquivo_nao_permitido(logado, titular):
    arquivo = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")
    resposta = logado.post(
        reverse("beneficiarios:novo_anexo", args=[titular.pk]), {"tipo": "OUT", "arquivo": arquivo}
    )
    assert resposta.status_code == 200
    assert not Anexo.objects.exists()


def test_arquivo_grande_demais(logado, titular, settings):
    settings.TAMANHO_MAXIMO_ANEXO_MB = 0
    resposta = logado.post(
        reverse("beneficiarios:novo_anexo", args=[titular.pk]), {"tipo": "DPS", "arquivo": pdf()}
    )
    assert resposta.status_code == 200
    assert not Anexo.objects.exists()


def test_excluir_anexo_apaga_o_arquivo(
    admin, titular, pasta_de_anexos, django_capture_on_commit_callbacks
):
    anexo = Anexo.objects.create(
        beneficiario=titular, tipo="DPS", arquivo=pdf(), nome_original="dps.pdf"
    )
    caminho = Path(pasta_de_anexos) / anexo.arquivo.name
    url = reverse("beneficiarios:excluir_anexo", args=[anexo.pk])

    assert admin.post(url, {"confirmacao": "outro"}).status_code == 200
    assert caminho.exists()

    with django_capture_on_commit_callbacks(execute=True):
        admin.post(url, {"confirmacao": "dps.pdf"})
    assert not Anexo.objects.exists()
    assert not caminho.exists()


# ------------------------------------------------------------------
# Exclusões
# ------------------------------------------------------------------


def test_titular_com_dependentes_nao_pode_ser_excluido(admin, titular, conjuge):
    pagina = admin.post(
        reverse("beneficiarios:excluir", args=[titular.pk]), {"confirmacao": titular.nome}
    )
    assert pagina.status_code == 200
    assert Beneficiario.objects.filter(pk=titular.pk).exists()


def test_funcionario_sem_permissao_nao_exclui_beneficiario(logado, titular):
    resposta = logado.post(
        reverse("beneficiarios:excluir", args=[titular.pk]), {"confirmacao": titular.nome}
    )
    assert resposta.status_code == 403
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    assert "Excluir cadastro" not in pagina


def test_permissao_de_excluir_pode_ser_dada(logado, usuario, titular, saude):
    usuario.user_permissions.add(Permission.objects.get(codename="delete_beneficiario"))
    incluir(titular, saude)
    logado.post(reverse("beneficiarios:excluir", args=[titular.pk]), {"confirmacao": titular.nome})
    assert not Beneficiario.objects.exists()
    assert not Vinculo.objects.exists()


def test_filial_com_beneficiarios_nao_pode_ser_excluida(titular, filial):
    assert filial.bloqueios_para_excluir()
