"""Etapa 21: empresa com muitas filiais sem encher a tela de texto."""

import pytest
from django.urls import reverse

from beneficiarios.tests.fixtures import contrato
from clientes.models import Unidade
from clientes.views import LIMITE_DE_QUADROS_DE_UNIDADE

pytestmark = pytest.mark.django_db


def cnpj_valido(base: str) -> str:
    """CNPJ fictício com os dígitos verificadores certos."""

    def digito(numeros: str, pesos: list[int]) -> str:
        resto = sum(int(n) * p for n, p in zip(numeros, pesos, strict=True)) % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    primeiro = digito(base, pesos)
    return base + primeiro + digito(base + primeiro, [6, *pesos])


def criar_filiais(empresa, quantas: int) -> list[Unidade]:
    return [
        Unidade.objects.create(
            cliente=empresa,
            cnpj=cnpj_valido(f"98765432{numero + 10:04d}"),
            razao_social=f"Filial Exemplo {numero:02d} Ltda",
            nome_fantasia=f"Loja Exemplo {numero:02d}",
            cidade="Londrina" if numero == 7 else "Curitiba",
        )
        for numero in range(1, quantas + 1)
    ]


@pytest.fixture
def rede(empresa, matriz, filial):
    """Matriz, filial e mais 40 filiais: 42 unidades."""
    return [matriz, filial, *criar_filiais(empresa, 40)]


def test_poucas_unidades_continuam_em_quadros(logado, empresa, matriz, filial):
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert 'id="tabela-de-unidades"' not in pagina
    assert "Contatos desta unidade" in pagina


def test_muitas_unidades_viram_tabela_com_filtro(logado, empresa, rede):
    assert len(rede) > LIMITE_DE_QUADROS_DE_UNIDADE
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert 'id="tabela-de-unidades"' in pagina
    assert "Filtrar por nome, CNPJ, cidade ou contato" in pagina
    assert "Contatos desta unidade" not in pagina
    assert "Loja Exemplo 40" in pagina
    assert "js/listas-longas.js" in pagina


def test_contrato_e_contato_resumem_as_unidades(logado, empresa, seguradora, rede, contato_rh):
    contrato(empresa, seguradora, "Saúde", "S-9", rede)
    contrato(empresa, seguradora, "Dental", "D-9", rede[:20])
    contato_rh.unidades.set(rede[:12])
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Todas as 42 unidades" in pagina
    assert "20 de 42 unidades" in pagina
    assert "12 de 42 unidades" in pagina
    # Os nomes continuam na página, recolhidos, para quem quiser abrir a lista.
    assert 'class="lista-recolhida"' in pagina


def test_ate_tres_unidades_mostram_os_nomes(logado, empresa, seguradora, rede):
    contrato(empresa, seguradora, "Saúde", "S-9", rede[2:4])
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "Loja Exemplo 01, Loja Exemplo 02" in pagina


def test_formulario_com_muitas_unidades_tem_marcar_todas(logado, empresa, rede):
    pagina = logado.get(reverse("apolices:novo_contrato", args=[empresa.pk])).content.decode()
    assert "Marcar todas" in pagina and "Desmarcar todas" in pagina
    assert 'class="opcoes-em-colunas"' in pagina
    poucas = logado.get(reverse("clientes:novo_contato", args=[empresa.pk])).content.decode()
    assert "Marcar todas" in poucas  # o contato também escolhe entre as 42 unidades


def test_exclusao_de_unidades_fica_recolhida(admin, empresa, rede):
    pagina = admin.get(empresa.get_absolute_url()).content.decode()
    assert "Excluir uma unidade (42)" in pagina


def test_comentario_dos_documentos_nao_aparece_na_pagina(logado, empresa, matriz):
    pagina = logado.get(empresa.get_absolute_url()).content.decode()
    assert "{#" not in pagina
    assert "Recebe: documentos" not in pagina
