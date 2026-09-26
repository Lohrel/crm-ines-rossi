import pytest
from django.urls import reverse

from clientes.models import Cliente, Contato, Unidade

from .conftest import CNPJ_FILIAL, CNPJ_MATRIZ, CPF_1, CPF_2

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("rota", ["clientes:lista", "clientes:novo_pf", "clientes:nova_empresa"])
def test_telas_exigem_login(client, rota):
    resposta = client.get(reverse(rota))
    assert resposta.status_code == 302
    assert "/entrar/" in resposta.url


def test_cadastrar_pessoa_fisica_com_cpf_pontuado(logado, usuario):
    resposta = logado.post(
        reverse("clientes:novo_pf"),
        {"nome": "Maria Exemplo", "cpf": "111.444.777-35", "sexo": "F", "ativo": "on"},
    )
    cliente = Cliente.objects.get(nome="Maria Exemplo")
    assert resposta.status_code == 302
    assert resposta.url == cliente.get_absolute_url()
    assert cliente.cpf == CPF_2
    assert cliente.tipo == "PF"
    assert cliente.history.first().history_user == usuario


def test_cpf_invalido_mostra_erro(logado):
    resposta = logado.post(reverse("clientes:novo_pf"), {"nome": "X", "cpf": "123.456.789-00"})
    assert resposta.status_code == 200
    assert "CPF inválido" in resposta.content.decode()
    assert not Cliente.objects.exists()


def test_cpf_repetido_mostra_erro(logado, pessoa):
    resposta = logado.post(reverse("clientes:novo_pf"), {"nome": "Y", "cpf": CPF_1})
    assert "Já existe um cliente com este CPF" in resposta.content.decode()


def test_cadastrar_empresa_cria_matriz_junto(logado):
    resposta = logado.post(
        reverse("clientes:nova_empresa"),
        {
            "nome": "Supermercados Exemplo",
            "ativo": "on",
            "unidade-cnpj": "11.222.333/0001-81",
            "unidade-razao_social": "Supermercados Exemplo Ltda",
            "unidade-matriz": "on",
            "unidade-ativo": "on",
        },
    )
    empresa = Cliente.objects.get()
    assert resposta.status_code == 302
    assert empresa.tipo == "PJ" and empresa.cpf is None
    unidade = empresa.unidades.get()
    assert unidade.cnpj == CNPJ_MATRIZ and unidade.matriz


def test_empresa_com_cnpj_invalido_nao_salva_nada(logado):
    resposta = logado.post(
        reverse("clientes:nova_empresa"),
        {"nome": "X", "unidade-cnpj": "11.111.111/1111-11", "unidade-razao_social": "X"},
    )
    assert resposta.status_code == 200
    assert "CNPJ inválido" in resposta.content.decode()
    assert not Cliente.objects.exists()


def test_adicionar_filial_e_contato(logado, empresa, matriz):
    logado.post(
        reverse("clientes:nova_unidade", args=[empresa.pk]),
        {"cnpj": CNPJ_FILIAL, "razao_social": "Filial Ltda", "ativo": "on"},
    )
    filial = Unidade.objects.get(cnpj=CNPJ_FILIAL)
    assert filial.cliente == empresa and not filial.matriz

    logado.post(
        reverse("clientes:novo_contato", args=[filial.pk]),
        {"nome": "Carla", "cargo": "RH", "email": "rh@exemplo.test", "principal": "on"},
    )
    assert filial.contatos.get().principal


def test_trocar_contato_principal_pela_tela(logado, contato_rh, filial):
    resposta = logado.post(
        reverse("clientes:novo_contato", args=[filial.pk]),
        {"nome": "Pedro", "principal": "on"},
    )
    assert resposta.status_code == 302
    assert Contato.objects.get(principal=True).nome == "Pedro"


def test_trocar_matriz_pela_tela(logado, matriz, filial):
    resposta = logado.post(
        reverse("clientes:editar_unidade", args=[filial.pk]),
        {"cnpj": CNPJ_FILIAL, "razao_social": filial.razao_social, "matriz": "on", "ativo": "on"},
    )
    assert resposta.status_code == 302
    matriz.refresh_from_db()
    filial.refresh_from_db()
    assert filial.matriz and not matriz.matriz


def test_nao_cria_unidade_para_pessoa_fisica(logado, pessoa):
    resposta = logado.get(reverse("clientes:nova_unidade", args=[pessoa.pk]))
    assert resposta.status_code == 404


def test_editar_empresa_usa_formulario_de_empresa(logado, empresa):
    resposta = logado.get(reverse("clientes:editar", args=[empresa.pk]))
    conteudo = resposta.content.decode()
    assert 'name="cpf"' not in conteudo
    assert "Nome da empresa ou grupo" in conteudo


def test_remover_contato(logado, contato_rh):
    resposta = logado.post(reverse("clientes:remover_contato", args=[contato_rh.pk]))
    assert resposta.status_code == 302
    assert not Contato.objects.exists()


def test_lista_busca_por_cnpj_de_filial(logado, empresa, matriz, filial, pessoa):
    resposta = logado.get(reverse("clientes:lista"), {"q": "11.222.333/0002-62"})
    conteudo = resposta.content.decode()
    assert "Supermercados Exemplo" in conteudo
    assert "João Exemplo" not in conteudo


def test_lista_filtra_por_tipo(logado, empresa, pessoa):
    resposta = logado.get(reverse("clientes:lista"), {"tipo": "PF"})
    conteudo = resposta.content.decode()
    assert "João Exemplo" in conteudo
    assert "Supermercados Exemplo" not in conteudo


def test_detalhe_mostra_unidades_contatos_e_historico(logado, empresa, filial, contato_rh):
    conteudo = logado.get(empresa.get_absolute_url()).content.decode()
    assert "11.222.333/0002-62" in conteudo
    assert "Carla RH" in conteudo
    assert "Histórico de alterações" in conteudo
    assert "criou Contato: Carla RH (RH)" in conteudo


def test_historico_mostra_quem_alterou_e_quais_campos(logado, pessoa):
    logado.post(
        reverse("clientes:editar", args=[pessoa.pk]),
        {"nome": pessoa.nome, "cpf": pessoa.cpf, "telefone": "11 98888-7777", "ativo": "on"},
    )
    conteudo = logado.get(pessoa.get_absolute_url()).content.decode()
    assert "Ana Lima" in conteudo
    assert "(telefone)" in conteudo
