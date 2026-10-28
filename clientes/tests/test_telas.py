import pytest
from django.urls import reverse

from clientes.models import Cliente, Contato, Unidade
from clientes.tests.fixtures import CNPJ_FILIAL, CNPJ_MATRIZ, CPF_1, CPF_2

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
        reverse("clientes:novo_contato", args=[empresa.pk]),
        {
            "nome": "Carla",
            "cargo": "RH",
            "email": "rh@exemplo.test",
            "unidades": [filial.pk],
            "principal": "on",
        },
    )
    assert filial.contatos.get().principal


def test_um_rh_atende_varias_filiais(logado, empresa, matriz, filial):
    resposta = logado.post(
        reverse("clientes:novo_contato", args=[empresa.pk]),
        {"nome": "Marta", "cargo": "RH", "unidades": [matriz.pk, filial.pk]},
    )
    assert resposta.status_code == 302
    marta = Contato.objects.get(nome="Marta")
    assert set(marta.unidades.all()) == {matriz, filial}
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Supermercados Exemplo Ltda, Exemplo Centro" in pagina


def test_contato_precisa_de_ao_menos_uma_unidade(logado, empresa, matriz):
    resposta = logado.post(reverse("clientes:novo_contato", args=[empresa.pk]), {"nome": "Sem"})
    assert resposta.status_code == 200
    assert not Contato.objects.exists()


def test_contato_nao_aceita_unidade_de_outra_empresa(logado, empresa, matriz):
    outra = Cliente.objects.create(tipo="PJ", nome="Outra Empresa")
    unidade_alheia = Unidade.objects.create(
        cliente=outra, cnpj="11444777000161", razao_social="Outra Ltda", matriz=True
    )
    resposta = logado.post(
        reverse("clientes:novo_contato", args=[empresa.pk]),
        {"nome": "Intruso", "unidades": [unidade_alheia.pk]},
    )
    assert resposta.status_code == 200
    assert not Contato.objects.exists()


def test_botao_da_unidade_ja_marca_a_unidade(logado, empresa, matriz, filial):
    url = reverse("clientes:novo_contato", args=[empresa.pk]) + f"?unidade={filial.pk}"
    pagina = logado.get(url).content.decode()
    assert f'value="{filial.pk}"' in pagina
    assert "checked" in pagina.split(f'value="{filial.pk}"')[1].split(">")[0]


def test_trocar_contato_principal_pela_tela(logado, contato_rh, empresa, filial):
    resposta = logado.post(
        reverse("clientes:novo_contato", args=[empresa.pk]),
        {"nome": "Pedro", "unidades": [filial.pk], "principal": "on"},
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


def test_cadastrar_filial_com_cnpj_alfanumerico(logado, empresa, matriz):
    resposta = logado.post(
        reverse("clientes:nova_unidade", args=[empresa.pk]),
        {"cnpj": "12.abc.345/01de-35", "razao_social": "Filial Nova Ltda", "ativo": "on"},
    )
    assert resposta.status_code == 302
    assert Unidade.objects.get(cnpj="12ABC34501DE35").cliente == empresa
    conteudo = logado.get(empresa.get_absolute_url()).content.decode()
    assert "12.ABC.345/01DE-35" in conteudo


def test_rotulos_dos_filtros_sem_dois_pontos(logado):
    pagina = logado.get(reverse("movimentacoes:lista")).content.decode()
    assert '<label for="id_q">Buscar</label>' in pagina
    assert "Buscar:" not in pagina


@pytest.mark.parametrize("rota", ["clientes:novo_pf", "clientes:nova_empresa"])
def test_listas_de_escolha_sem_tracejado(logado, rota):
    pagina = logado.get(reverse(rota)).content.decode()
    assert "---------" not in pagina
    assert '<option value="" selected>Escolha</option>' in pagina


def test_lista_de_escolha_do_banco_sem_tracejado(logado, empresa):
    pagina = logado.get(reverse("apolices:novo_contrato", args=[empresa.pk])).content.decode()
    assert "---------" not in pagina
    assert '<option value="" selected>Escolha</option>' in pagina


def test_atalhos_para_cada_parte_da_pagina_do_cliente(logado, empresa, matriz, filial, contato_rh):
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert 'aria-label="Partes da página do cliente"' in pagina
    for parte, total in [("pendencias", 0), ("contatos", 1), ("unidades", 2), ("contratos", 0)]:
        assert f'href="#{parte}"' in pagina and f'id="{parte}"' in pagina
        assert f'<span class="badge rounded-pill">{total}</span>' in pagina
    assert 'href="#historico"' in pagina and 'id="historico"' in pagina
    # Sem apólice de auto ou imóvel, não há o atalho dos veículos.
    assert 'href="#bens"' not in pagina


def test_atalhos_da_pessoa_fisica(logado, pessoa):
    pagina = logado.get(pessoa.get_absolute_url()).content.decode()
    assert 'href="#dados"' in pagina and 'id="dados"' in pagina
    assert 'href="#contatos"' not in pagina and 'href="#unidades"' not in pagina


def test_historico_mostra_as_5_ultimas_e_recolhe_o_resto(logado, pessoa):
    for numero in range(7):
        pessoa.telefone = f"(11) 3333-000{numero}"
        pessoa.save()
    pagina = logado.get(pessoa.get_absolute_url()).content.decode()
    visiveis, recolhidas = pagina.split('<details class="historico-anterior">')
    visiveis = visiveis[visiveis.index('id="historico"') :]
    assert visiveis.count("<li") == 5
    assert "Ver as outras 3 alterações" in recolhidas
    assert recolhidas.split("</details>")[0].count("<li") == 3


def test_historico_curto_nao_recolhe(logado, pessoa):
    pagina = logado.get(pessoa.get_absolute_url()).content.decode()
    assert "historico-anterior" not in pagina


def test_lista_de_clientes_com_menos_ruido(logado, empresa, matriz, filial, pessoa):
    Cliente.objects.filter(pk=pessoa.pk).update(ativo=False)
    pagina = logado.get(reverse("clientes:lista")).content.decode()
    assert "2 clientes" in pagina
    assert "<th>Situação</th>" not in pagina and ">Ativo</span>" not in pagina
    assert 'João Exemplo</a> <span class="badge text-bg-secondary">Inativo</span>' in pagina
    assert "<td>Empresa · 2 unidades</td>" in pagina and "<td>Pessoa física</td>" in pagina


def test_historico_com_uma_alteracao_a_mais(logado, pessoa):
    for numero in range(5):
        pessoa.telefone = f"(11) 3333-000{numero}"
        pessoa.save()
    pagina = logado.get(pessoa.get_absolute_url()).content.decode()
    assert "Ver a outra alteração" in pagina


def test_telefone_e_email_ficam_num_grupo_separado_do_endereco(logado):
    resposta = logado.get(reverse("clientes:nova_empresa"))

    html = resposta.content.decode()
    contato = html.index(">Telefone e e-mail</h2>")
    endereco = html.index(">Endereço</h2>")
    assert contato < html.index('name="unidade-telefone"') < html.index('name="unidade-email"')
    assert html.index('name="unidade-email"') < endereco < html.index('name="unidade-cep"')
    # Os dois telefones dividem a linha; o e-mail não cabe ao lado deles e desce.
    assert 'class="col-sm-6 col-lg-4"' in html
    assert 'class="col-lg-8"' in html


def test_formulario_sem_subtitulos_continua_numa_grade_so(logado, empresa):
    resposta = logado.get(reverse("clientes:editar", args=[empresa.pk]))

    html = resposta.content.decode()
    assert "subtitulo-do-formulario" not in html
    assert html.count('class="row g-3') == 1
