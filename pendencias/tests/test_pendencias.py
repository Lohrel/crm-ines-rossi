import re
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apolices.models import Contrato, Ramo
from beneficiarios.tests.fixtures import HOJE
from clientes.models import Cliente, Unidade
from contas.models import Usuario
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia

pytestmark = pytest.mark.django_db

EM_5_DIAS = HOJE + timedelta(days=5)


def pendencia(cliente, responsavel, descricao="Cobrar do RH a DPS do João", **extra):
    nova = Pendencia(
        cliente=cliente,
        responsavel=responsavel,
        descricao=descricao,
        prazo=extra.pop("prazo", EM_5_DIAS),
        **extra,
    )
    nova.full_clean()
    nova.save()
    return nova


def pedido(pessoa, plano):
    movimentacao = Movimentacao(
        tipo="INC",
        cliente=pessoa.cliente,
        beneficiario=pessoa,
        contrato=plano,
        enviada_em=HOJE,
        vigencia=date(2026, 10, 1),
    )
    movimentacao.full_clean()
    movimentacao.save()
    return movimentacao


def dados(responsavel, **extra):
    return {
        "descricao": "Cobrar do RH a DPS do João",
        "responsavel": responsavel.pk,
        "prazo": EM_5_DIAS.strftime("%d/%m/%Y"),
        **extra,
    }


@pytest.fixture
def outra_empresa(db):
    empresa = Cliente.objects.create(tipo="PJ", nome="Padaria Exemplo")
    Unidade.objects.create(
        cliente=empresa, cnpj="12ABC34501DE35", razao_social="Padaria Exemplo Ltda", matriz=True
    )
    return empresa


@pytest.fixture
def bruno(db):
    return Usuario.objects.create_user(
        username="bruno", password="senha-forte-de-teste", first_name="Bruno", last_name="Reis"
    )


# ------------------------------------------------------------------
# Cliente e filial
# ------------------------------------------------------------------


def test_empresa_com_filiais_precisa_dizer_a_filial(empresa, matriz, filial, usuario):
    with pytest.raises(ValidationError) as erro:
        pendencia(empresa, usuario)
    assert "unidade" in erro.value.message_dict
    assert pendencia(empresa, usuario, unidade=filial).unidade == filial


def test_empresa_so_com_a_matriz_fica_com_ela(empresa, matriz, usuario):
    assert pendencia(empresa, usuario).unidade == matriz


def test_pessoa_fisica_nao_tem_filial(pessoa, matriz, usuario):
    assert pendencia(pessoa, usuario).unidade is None
    with pytest.raises(ValidationError):
        pendencia(pessoa, usuario, unidade=matriz)


def test_filial_contrato_e_movimentacao_precisam_ser_do_cliente(
    empresa, matriz, outra_empresa, saude, titular, usuario
):
    de_outra = outra_empresa.unidades.get()
    contrato_de_outra = Contrato.objects.create(
        cliente=outra_empresa,
        seguradora=saude.seguradora,
        ramo=Ramo.objects.get(nome="Vida"),
        numero="V-9",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=5,
    )
    movimentacao = pedido(titular, saude)
    for campo, valor in [("unidade", de_outra), ("contrato", contrato_de_outra)]:
        with pytest.raises(ValidationError) as erro:
            pendencia(empresa, usuario, **{"unidade": matriz, campo: valor})
        assert campo in erro.value.message_dict
    with pytest.raises(ValidationError) as erro:
        pendencia(outra_empresa, usuario, movimentacao=movimentacao)
    assert "movimentacao" in erro.value.message_dict


# ------------------------------------------------------------------
# Prazo, conclusão e reabertura
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dias", "texto", "atencao"),
    [
        (-2, "venceu há 2 dias", True),
        (0, "vence hoje", True),
        (3, "vence em 3 dias", True),
        (4, "vence em 4 dias", False),
    ],
)
def test_prazo_das_em_aberto(pessoa, usuario, dias, texto, atencao):
    nova = pendencia(pessoa, usuario, prazo=HOJE + timedelta(days=dias))
    assert nova.texto_do_prazo == texto and nova.pede_atencao is atencao


def test_concluir_e_reabrir(pessoa, usuario, bruno):
    nova = pendencia(pessoa, usuario)
    nova.concluir(bruno)
    nova.refresh_from_db()
    assert nova.concluida_em == HOJE and nova.concluida_por == bruno
    assert nova.texto_do_prazo == "" and not nova.pede_atencao
    with pytest.raises(ValidationError):
        nova.concluir(usuario)
    nova.reabrir()
    nova.refresh_from_db()
    assert nova.concluida_em is None and nova.concluida_por is None
    with pytest.raises(ValidationError):
        nova.reabrir()


# ------------------------------------------------------------------
# Nova pendência
# ------------------------------------------------------------------


def test_nova_pela_pagina_da_empresa_pede_a_filial(logado, empresa, matriz, filial, usuario):
    url = reverse("pendencias:nova") + f"?cliente={empresa.pk}"
    pagina = logado.get(url).content.decode()
    assert "Nova pendência de Supermercados Exemplo" in pagina
    assert "Escolha a unidade" in pagina and "Exemplo Centro (filial)" in pagina
    # O responsável já vem preenchido com quem está criando.
    assert re.search(rf'<option value="{usuario.pk}" selected>Ana Lima</option>', pagina)

    sem_filial = logado.post(url, dados(usuario)).content.decode()
    erros = re.findall(r"invalid-feedback[^>]*>(.*?)<", sem_filial, re.S)
    assert erros == ["Informe a filial (ou a matriz) desta pendência."]
    assert not Pendencia.objects.exists()

    resposta = logado.post(url, dados(usuario, unidade=filial.pk))
    assert resposta.status_code == 302 and resposta.url == empresa.get_absolute_url()
    nova = Pendencia.objects.get()
    assert (nova.cliente, nova.unidade, nova.prazo) == (empresa, filial, EM_5_DIAS)
    assert nova.registrada_por == usuario and nova.responsavel == usuario


def test_empresa_sem_filiais_ja_vem_com_a_matriz(logado, empresa, matriz):
    pagina = logado.get(reverse("pendencias:nova") + f"?cliente={empresa.pk}").content.decode()
    assert re.search(rf'<option value="{matriz.pk}" selected>', pagina)


def test_pessoa_fisica_nao_mostra_o_campo_da_filial(logado, pessoa, usuario):
    url = reverse("pendencias:nova") + f"?cliente={pessoa.pk}"
    assert 'name="unidade"' not in logado.get(url).content.decode()
    assert logado.post(url, dados(usuario)).status_code == 302
    assert Pendencia.objects.get().cliente == pessoa


def test_nova_pela_movimentacao_ja_vem_ligada_a_ela(logado, titular, saude, filial, usuario):
    movimentacao = pedido(titular, saude)
    url = reverse("pendencias:nova") + f"?movimentacao={movimentacao.pk}"
    pagina = logado.get(url).content.decode()
    for registro in (filial, saude, movimentacao):
        assert re.search(rf'<option value="{registro.pk}" selected>', pagina)

    envio = dados(usuario, unidade=filial.pk, contrato=saude.pk, movimentacao=movimentacao.pk)
    resposta = logado.post(url, envio)
    assert resposta.url == movimentacao.get_absolute_url()
    nova = Pendencia.objects.get()
    assert (nova.movimentacao, nova.contrato, nova.unidade) == (movimentacao, saude, filial)

    pagina = logado.get(movimentacao.get_absolute_url()).content.decode()
    assert "Pendências desta movimentação" in pagina and "Cobrar do RH a DPS do João" in pagina


def test_nova_pela_filial_e_pelo_contrato(logado, empresa, matriz, filial, saude, usuario):
    pagina = logado.get(reverse("pendencias:nova") + f"?unidade={filial.pk}").content.decode()
    assert re.search(rf'<option value="{filial.pk}" selected>', pagina)

    url = reverse("pendencias:nova") + f"?contrato={saude.pk}"
    assert re.search(rf'<option value="{saude.pk}" selected>', logado.get(url).content.decode())
    resposta = logado.post(url, dados(usuario, unidade=matriz.pk, contrato=saude.pk))
    assert resposta.url == reverse("pendencias:lista") + f"?contrato={saude.pk}"
    assert Pendencia.objects.get().contrato == saude


def test_nova_pela_lista_pergunta_o_cliente_primeiro(logado, empresa, matriz, pessoa, usuario):
    resposta = logado.get(reverse("pendencias:nova"))
    assert resposta.url == reverse("pendencias:escolher_cliente")

    pagina = logado.get(resposta.url, {"q": "supermercados"}).content.decode()
    assert "Supermercados Exemplo" in pagina and "João Exemplo" not in pagina
    link = f"{reverse('pendencias:nova')}?cliente={empresa.pk}&proximo=%2Fpendencias%2F"
    assert link in pagina

    resposta = logado.post(link, dados(usuario, unidade=matriz.pk))
    assert resposta.url == reverse("pendencias:lista")


# ------------------------------------------------------------------
# Lista
# ------------------------------------------------------------------


def test_lista_mostra_as_em_aberto_pelo_prazo(logado, pessoa, usuario):
    pendencia(pessoa, usuario, "Depois", prazo=HOJE + timedelta(days=10))
    pendencia(pessoa, usuario, "Vencida", prazo=HOJE - timedelta(days=1))
    pendencia(pessoa, usuario, "Hoje", prazo=HOJE)
    pendencia(pessoa, usuario, "Resolvida").concluir(usuario)

    url = reverse("pendencias:lista")
    pagina = logado.get(url).content.decode()
    posicoes = [pagina.index(f">{texto}</a>") for texto in ("Vencida", "Hoje", "Depois")]
    assert posicoes == sorted(posicoes) and ">Resolvida</a>" not in pagina
    assert "<strong>3</strong> em aberto" in pagina
    assert "<strong>1</strong> com o prazo vencido" in pagina
    assert "<strong>1</strong> vence nos próximos 3 dias" in pagina
    assert 'text-bg-danger">Venceu ontem' in pagina and 'text-bg-warning">Vence hoje' in pagina

    concluidas = logado.get(url, {"situacao": "concluidas"}).content.decode()
    assert ">Resolvida</a>" in concluidas and ">Hoje</a>" not in concluidas
    assert "concluída em" in concluidas and "por Ana Lima" in concluidas
    assert ">Resolvida</a>" in logado.get(url, {"situacao": "todas"}).content.decode()


def test_filtro_por_responsavel_e_busca(logado, empresa, matriz, filial, pessoa, usuario, bruno):
    pendencia(empresa, usuario, "Mandar carteirinhas", unidade=filial)
    pendencia(pessoa, bruno, "Renovar seguro de vida")
    url = reverse("pendencias:lista")

    pagina = logado.get(url).content.decode()
    assert f'href="{url}?responsavel={usuario.pk}"' in pagina
    minhas = logado.get(url, {"responsavel": usuario.pk}).content.decode()
    assert "Mandar carteirinhas" in minhas and "Renovar seguro" not in minhas

    for termo in ("carteirinhas", "supermercados", "centro"):
        encontradas = logado.get(url, {"q": termo}).content.decode()
        assert "Mandar carteirinhas" in encontradas and "Renovar seguro" not in encontradas


def test_filtro_das_que_pedem_atencao(logado, pessoa, usuario, bruno):
    vencida = pendencia(pessoa, bruno, "Ligar para o RH", prazo=HOJE - timedelta(days=1))
    no_limite = pendencia(pessoa, usuario, "Pedir a DPS", prazo=HOJE + timedelta(days=3))
    longe = pendencia(pessoa, usuario, "Renovar o dental", prazo=HOJE + timedelta(days=4))
    url = reverse("pendencias:lista")

    def mostra(**filtros) -> set:
        pagina = logado.get(url, {"situacao": "atencao", **filtros}).content.decode()
        return {p for p in (vencida, no_limite, longe) if p.get_absolute_url() in pagina}

    assert mostra() == {vencida, no_limite}
    assert mostra(responsavel=usuario.pk) == {no_limite}
    pagina = logado.get(url, {"situacao": "atencao"}).content.decode()
    assert '<option value="atencao" selected>Pedem atenção (3 dias)</option>' in pagina


def test_lista_do_contrato_cria_a_nova_ja_ligada(logado, empresa, matriz, saude, usuario):
    pendencia(empresa, usuario, "Resposta do reajuste", unidade=matriz, contrato=saude)
    pendencia(empresa, usuario, "Outra coisa", unidade=matriz)
    url = reverse("pendencias:lista")

    pagina = logado.get(url, {"contrato": saude.pk}).content.decode()
    assert "Pendências do contrato" in pagina
    assert "Resposta do reajuste" in pagina and "Outra coisa" not in pagina
    nova = f"{reverse('pendencias:nova')}?contrato={saude.pk}&amp;proximo="
    assert nova in pagina

    # A tabela de contratos do cliente leva a essa lista.
    cliente = logado.get(empresa.get_absolute_url()).content.decode()
    assert f"{url}?contrato={saude.pk}" in cliente


# ------------------------------------------------------------------
# Concluir, reabrir e editar
# ------------------------------------------------------------------


def test_concluir_pela_lista_volta_para_ela(logado, pessoa, usuario, bruno):
    nova = pendencia(pessoa, bruno)
    url = reverse("pendencias:concluir", args=[nova.pk])
    assert logado.get(url).status_code == 405

    volta = reverse("pendencias:lista") + "?situacao=todas"
    resposta = logado.post(url, {"proximo": volta})
    assert resposta.url == volta
    nova.refresh_from_db()
    assert nova.concluida_em == HOJE and nova.concluida_por == usuario

    # Endereço de fora do sistema é ignorado: volta para a própria pendência.
    reabrir = reverse("pendencias:reabrir", args=[nova.pk])
    resposta = logado.post(reabrir, {"proximo": "https://exemplo.invalid/"})
    assert resposta.url == nova.get_absolute_url()
    nova.refresh_from_db()
    assert not nova.concluida


def test_pagina_da_pendencia_e_historico(logado, empresa, matriz, filial, usuario):
    url = reverse("pendencias:nova") + f"?cliente={empresa.pk}"
    logado.post(url, dados(usuario, unidade=filial.pk, observacao="RH pediu até sexta."))
    nova = Pendencia.objects.get()
    logado.post(reverse("pendencias:concluir", args=[nova.pk]))

    pagina = logado.get(nova.get_absolute_url()).content.decode()
    assert "Exemplo Centro" in pagina and "RH pediu até sexta." in pagina
    assert "Reabrir" in pagina and "Marcar como concluída" not in pagina
    assert "criou a pendência · situação: em aberto" in pagina
    assert "alterou a pendência · situação: concluída" in pagina

    # O histórico do cliente também mostra a pendência.
    cliente = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Pendência: Cobrar do RH a DPS do João" in cliente


def test_editar_pendencia(logado, empresa, matriz, filial, usuario, bruno):
    nova = pendencia(empresa, usuario, unidade=filial)
    url = reverse("pendencias:editar", args=[nova.pk])
    assert "Editar pendência de Supermercados Exemplo" in logado.get(url).content.decode()

    novo_prazo = HOJE + timedelta(days=20)
    envio = dados(bruno, unidade=matriz.pk, prazo=novo_prazo.strftime("%d/%m/%Y"))
    assert logado.post(url, envio).url == nova.get_absolute_url()
    nova.refresh_from_db()
    assert (nova.unidade, nova.responsavel, nova.prazo) == (matriz, bruno, novo_prazo)

    # O histórico diz o que mudou.
    pagina = logado.get(nova.get_absolute_url()).content.decode()
    campos = re.search(r"situação: em aberto\s*<span[^>]*>\((.*?)\)</span>", pagina).group(1)
    assert set(campos.split(", ")) == {"unidade (filial)", "responsável", "prazo"}


def test_responsavel_so_entre_os_usuarios_ativos(logado, pessoa, usuario, bruno):
    nova = pendencia(pessoa, bruno)
    bruno.is_active = False
    bruno.save()
    pagina = logado.get(reverse("pendencias:nova") + f"?cliente={pessoa.pk}").content.decode()
    assert "Bruno Reis" not in pagina
    # Quem já era responsável continua aparecendo na edição.
    edicao = logado.get(reverse("pendencias:editar", args=[nova.pk])).content.decode()
    assert "Bruno Reis" in edicao


# ------------------------------------------------------------------
# Páginas do cliente e exclusão
# ------------------------------------------------------------------


def test_pagina_do_cliente_mostra_as_em_aberto(logado, empresa, matriz, filial, usuario):
    pendencia(empresa, usuario, "Mandar carteirinhas", unidade=filial)
    pendencia(empresa, usuario, "Já resolvida", unidade=matriz).concluir(usuario)

    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Pendências em aberto" in pagina
    assert ">Mandar carteirinhas</a>" in pagina and ">Já resolvida</a>" not in pagina
    assert f"{reverse('pendencias:nova')}?cliente={empresa.pk}" in pagina
    # Cada unidade tem o botão para criar a pendência já com ela.
    assert f"{reverse('pendencias:nova')}?unidade={filial.pk}" in pagina


def test_excluir_empresa_leva_as_pendencias(admin, empresa, matriz, filial):
    responsavel = Usuario.objects.get(username="chefe")
    pendencia(empresa, responsavel, unidade=filial)
    url = reverse("clientes:excluir", args=[empresa.pk])
    pagina = admin.get(url).content.decode()
    assert "Serão excluídas também todas as unidades e contatos desta empresa." in pagina
    assert "A pendência deste cliente também será excluída." in pagina

    admin.post(url, {"confirmacao": "Supermercados Exemplo"})
    assert not Cliente.objects.exists() and not Pendencia.objects.exists()


def test_excluir_filial_leva_so_as_pendencias_dela(admin, empresa, matriz, filial):
    responsavel = Usuario.objects.get(username="chefe")
    da_filial = pendencia(empresa, responsavel, unidade=filial)
    da_matriz = pendencia(empresa, responsavel, unidade=matriz)
    url = reverse("clientes:excluir_unidade", args=[filial.pk])
    pagina = admin.get(url).content.decode()
    assert "Os contatos que atendem só esta unidade também serão excluídos." in pagina
    assert "A pendência desta unidade também será excluída." in pagina

    admin.post(url, {"confirmacao": "Exemplo Centro"})
    assert not Pendencia.objects.filter(pk=da_filial.pk).exists()
    assert Pendencia.objects.filter(pk=da_matriz.pk).exists()


def test_aviso_da_exclusao_de_pessoa_fisica_nao_fala_de_contatos(admin, pessoa):
    pagina = admin.get(reverse("clientes:excluir", args=[pessoa.pk])).content.decode()
    aviso = re.search(r'<div class="alert alert-danger">(.*?)</div>', pagina, re.S).group(1)
    assert "contatos" not in aviso and "pendência" not in aviso
