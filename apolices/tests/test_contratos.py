import re
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apolices.models import Contrato, Ramo, Seguradora
from clientes.models import Cliente, Unidade

pytestmark = pytest.mark.django_db


def dados_contrato(seguradora, ramo, **extra):
    return {
        "seguradora": seguradora.pk,
        "ramo": ramo.pk,
        "numero": "C-123",
        "produto": "Plano X",
        "modalidade": "EM",
        "situacao": "ATV",
        "inicio_vigencia": "2026-01-01",
        "data_renovacao": "2027-01-01",
        "dia_vencimento": "15",
        "valor_mensal": "1234.56",
        **extra,
    }


def test_ramos_iniciais_criados():
    assert set(Ramo.objects.values_list("nome", flat=True)) >= {
        "Vida",
        "Saúde",
        "Dental",
        "Auto",
        "Imóvel",
    }


def test_numero_repetido_na_mesma_seguradora_e_barrado(contrato_empresa):
    repetido = Contrato(
        cliente=contrato_empresa.cliente,
        seguradora=contrato_empresa.seguradora,
        ramo=contrato_empresa.ramo,
        numero="SAU-001",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=5,
    )
    with pytest.raises(ValidationError, match="Já existe um contrato com este número"):
        repetido.full_clean()


def test_mesmo_numero_em_outra_seguradora_e_permitido(contrato_empresa):
    outra = Seguradora.objects.create(nome="Outra")
    Contrato(
        cliente=contrato_empresa.cliente,
        seguradora=outra,
        ramo=contrato_empresa.ramo,
        numero="SAU-001",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=5,
    ).full_clean()


def test_renovacao_antes_do_inicio_e_barrada(empresa, seguradora, saude):
    contrato = Contrato(
        cliente=empresa,
        seguradora=seguradora,
        ramo=saude,
        numero="X",
        modalidade="EM",
        inicio_vigencia=date(2026, 5, 1),
        data_renovacao=date(2026, 1, 1),
        dia_vencimento=1,
    )
    with pytest.raises(ValidationError, match="renovação não pode ser antes"):
        contrato.full_clean()


@pytest.mark.parametrize("dia", [0, 32])
def test_dia_de_vencimento_fora_do_mes_e_barrado(empresa, seguradora, saude, dia):
    contrato = Contrato(
        cliente=empresa,
        seguradora=seguradora,
        ramo=saude,
        numero="X",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=dia,
    )
    with pytest.raises(ValidationError):
        contrato.full_clean()


def test_contrato_empresarial_exige_pessoa_juridica(pessoa, seguradora, saude):
    contrato = Contrato(
        cliente=pessoa,
        seguradora=seguradora,
        ramo=saude,
        numero="X",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=1,
    )
    with pytest.raises(ValidationError, match="pessoa jurídica"):
        contrato.full_clean()


def test_empresa_pode_ter_varios_contratos(contrato_empresa, empresa, seguradora, saude):
    Contrato.objects.create(
        cliente=empresa,
        seguradora=seguradora,
        ramo=saude,
        numero="SAU-002",
        modalidade="EM",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=20,
    )
    assert empresa.contratos.count() == 2


def test_consultas_prontas(contrato_empresa):
    assert list(Contrato.objects.com_boleto_da_corretora()) == [contrato_empresa]
    assert list(Contrato.objects.renovam_ate(date(2027, 1, 31))) == [contrato_empresa]
    contrato_empresa.situacao = "CAN"
    contrato_empresa.save()
    assert not Contrato.objects.vigentes().exists()


# ---------------------------------------------------------------- telas


def test_cadastrar_contrato_de_empresa_com_filiais(
    logado, empresa, matriz, filial, seguradora, saude
):
    url = reverse("apolices:novo_contrato", args=[empresa.pk])
    resposta = logado.post(
        url,
        dados_contrato(
            seguradora, saude, unidades=[matriz.pk, filial.pk], corretora_envia_boleto="on"
        ),
    )
    assert resposta.status_code == 302
    contrato = Contrato.objects.get()
    assert contrato.cliente == empresa
    assert set(contrato.unidades.all()) == {matriz, filial}
    assert contrato.dia_vencimento == 15
    assert contrato.corretora_envia_boleto


def test_nao_aceita_unidade_de_outra_empresa(logado, empresa, matriz, seguradora, saude):
    outra = Cliente.objects.create(tipo="PJ", nome="Outra")
    unidade_alheia = Unidade.objects.create(
        cliente=outra, cnpj="12ABC34501DE35", razao_social="Outra Ltda"
    )
    resposta = logado.post(
        reverse("apolices:novo_contrato", args=[empresa.pk]),
        dados_contrato(seguradora, saude, unidades=[unidade_alheia.pk]),
    )
    assert resposta.status_code == 200
    assert not Contrato.objects.exists()


def test_contrato_de_pessoa_fisica_nao_mostra_unidades(logado, pessoa, seguradora, saude):
    url = reverse("apolices:novo_contrato", args=[pessoa.pk])
    assert 'name="unidades"' not in logado.get(url).content.decode()
    resposta = logado.post(url, dados_contrato(seguradora, saude, modalidade="IF"))
    assert resposta.status_code == 302
    assert Contrato.objects.get().cliente == pessoa


def test_seguradora_inativa_nao_aparece_para_novo_contrato(logado, empresa, seguradora):
    Seguradora.objects.create(nome="Seguradora Antiga", ativo=False)
    conteudo = logado.get(reverse("apolices:novo_contrato", args=[empresa.pk])).content.decode()
    assert "Seguradora Exemplo" in conteudo
    assert "Seguradora Antiga" not in conteudo


def test_pagina_do_cliente_mostra_contratos_e_historico(logado, contrato_empresa, empresa):
    conteudo = logado.get(empresa.get_absolute_url()).content.decode()
    assert "SAU-001" in conteudo
    assert "Exemplo Centro" in conteudo  # filial coberta
    assert "criou Contrato: Seguradora Exemplo SAU-001" in conteudo


def test_lista_de_contratos_filtra(logado, contrato_empresa, pessoa, seguradora, saude):
    Contrato.objects.create(
        cliente=pessoa,
        seguradora=seguradora,
        ramo=saude,
        numero="IND-9",
        modalidade="IF",
        inicio_vigencia=date(2026, 1, 1),
        dia_vencimento=5,
    )
    url = reverse("apolices:contratos")
    conteudo = logado.get(url, {"vencimento": 10}).content.decode()
    assert "SAU-001" in conteudo and "IND-9" not in conteudo
    conteudo = logado.get(url, {"boleto": "on"}).content.decode()
    assert "SAU-001" in conteudo and "IND-9" not in conteudo
    conteudo = logado.get(url, {"q": "IND"}).content.decode()
    assert "IND-9" in conteudo and "SAU-001" not in conteudo


def test_cancelados_so_aparecem_quando_pedidos(logado, contrato_empresa):
    contrato_empresa.situacao = "CAN"
    contrato_empresa.save()
    url = reverse("apolices:contratos")
    assert "SAU-001" not in logado.get(url).content.decode()
    assert "SAU-001" in logado.get(url, {"situacao": "todas"}).content.decode()


def test_filtro_das_renovacoes_dos_proximos_60_dias(logado, contrato_empresa, seguradora, saude):
    hoje = date.today()

    def contrato(numero, renovacao, situacao="ATV"):
        return Contrato.objects.create(
            cliente=contrato_empresa.cliente,
            seguradora=seguradora,
            ramo=saude,
            numero=numero,
            modalidade="EM",
            situacao=situacao,
            inicio_vigencia=hoje - timedelta(days=365),
            data_renovacao=renovacao,
            dia_vencimento=10,
        )

    contrato("PASSOU", hoje - timedelta(days=3))
    contrato("PERTO", hoje + timedelta(days=60))
    contrato("LONGE", hoje + timedelta(days=61))
    contrato("CANCELADO", hoje, situacao="CAN")
    contrato_empresa.data_renovacao = None
    contrato_empresa.save()

    url = reverse("apolices:contratos")
    conteudo = logado.get(url, {"renovacao": "on"}).content.decode()
    # A data já passada vem primeiro, em vermelho, para ser atualizada.
    numeros = re.findall(r'<div class="small text-body-secondary">(PASSOU|PERTO)</div>', conteudo)
    assert numeros == ["PASSOU", "PERTO"]
    assert "LONGE" not in conteudo and "CANCELADO" not in conteudo and "SAU-001" not in conteudo
    passou = f"{hoje - timedelta(days=3):%d/%m/%Y}"
    assert f'<div class="small text-danger">Renovação {passou}</div>' in conteudo
    perto = f"{hoje + timedelta(days=60):%d/%m/%Y}"
    assert f'<div class="small text-body-secondary">Renovação {perto}</div>' in conteudo
    # Sem o filtro, a data aparece nos vigentes; nos cancelados, não.
    todos = logado.get(url, {"situacao": "todas"}).content.decode()
    assert f"Renovação {hoje + timedelta(days=61):%d/%m/%Y}" in todos
    assert f"Renovação {hoje:%d/%m/%Y}" not in todos


def test_cadastrar_seguradora_sem_cnpj_duas_vezes(logado):
    for nome in ["A Seguros", "B Seguros"]:
        resposta = logado.post(reverse("apolices:nova_seguradora"), {"nome": nome, "ativo": "on"})
        assert resposta.status_code == 302
    assert Seguradora.objects.filter(cnpj__isnull=True).count() == 2


def test_contratos_exigem_login(client):
    assert client.get(reverse("apolices:contratos")).status_code == 302
