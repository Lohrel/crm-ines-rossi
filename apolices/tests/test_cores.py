"""Cor de cada seguradora: escolhida no cadastro, aparece numa faixa nas listas e num ponto antes
do nome."""

import pathlib
import re
from datetime import date

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from apolices.models import Seguradora
from boletos.models import Boleto
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia

pytestmark = pytest.mark.django_db

FAIXA = 'class="faixa-seguradora cor-roxo"'
PONTO = '<span class="seguradora-cor cor-roxo">Seguradora Exemplo</span>'


@pytest.fixture
def roxa(seguradora):
    seguradora.cor = Seguradora.Cor.ROXO
    seguradora.save()
    return seguradora


def test_escolher_a_cor_no_cadastro(logado, seguradora):
    url = reverse("apolices:editar_seguradora", args=[seguradora.pk])
    pagina = logado.get(url).content.decode()
    assert '<span class="amostra-cor cor-azul"></span>Azul' in pagina
    assert '<span class="amostra-cor"></span>Sem cor' in pagina
    resposta = logado.post(url, {"nome": seguradora.nome, "cor": "azul", "ativo": "on"})
    assert resposta.status_code == 302
    seguradora.refresh_from_db()
    assert seguradora.cor == "azul"


def test_cor_fora_da_paleta_nao_e_aceita(logado, seguradora):
    url = reverse("apolices:editar_seguradora", args=[seguradora.pk])
    resposta = logado.post(url, {"nome": seguradora.nome, "cor": "vermelho-vivo", "ativo": "on"})
    assert resposta.status_code == 200
    seguradora.refresh_from_db()
    assert seguradora.cor == ""


def test_sem_cor_as_listas_ficam_como_antes(logado, contrato_empresa):
    pagina = logado.get(reverse("apolices:contratos")).content.decode()
    assert "faixa-seguradora" not in pagina
    assert "seguradora-cor" not in pagina


def test_contratos_e_seguradoras_mostram_a_cor(logado, roxa, contrato_empresa):
    for url in [reverse("apolices:contratos"), reverse("apolices:seguradoras")]:
        pagina = logado.get(url).content.decode()
        assert FAIXA in pagina, url
        assert PONTO in pagina, url


def test_movimentacoes_boletos_e_pendencias_mostram_a_cor(
    logado, usuario, roxa, contrato_empresa, empresa, titular
):
    hoje = date.today()
    Movimentacao.objects.create(
        tipo="INC", beneficiario=titular, contrato=contrato_empresa, enviada_em=hoje, vigencia=hoje
    )
    Boleto.objects.create(contrato=contrato_empresa, referencia=hoje)
    Pendencia.objects.create(
        cliente=empresa,
        descricao="Conferir a fatura",
        responsavel=usuario,
        prazo=hoje,
        contrato=contrato_empresa,
    )
    respostas = {
        "movimentações": logado.get(reverse("movimentacoes:lista")),
        "boletos": logado.get(reverse("boletos:lista"), {"situacao": "todos"}),
        "pendências": logado.get(reverse("pendencias:lista")),
    }
    for lista, resposta in respostas.items():
        pagina = resposta.content.decode()
        assert FAIXA in pagina, lista
        assert PONTO in pagina, lista


def test_cada_cor_da_paleta_tem_o_tom_no_css():
    css = pathlib.Path(finders.find("css/crm.css")).read_text()
    for valor, _ in Seguradora.Cor.choices:
        assert re.search(rf"\.cor-{valor} \{{ --cor-seguradora: #[0-9a-f]{{6}}; \}}", css), valor
