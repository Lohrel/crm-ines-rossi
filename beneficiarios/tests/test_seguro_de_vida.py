"""Seguro de vida: salário no plano, capital e fatura, subfaturas e a planilha do mês."""

import ast
import operator
import re
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from openpyxl import load_workbook

from apolices.models import Contrato, Subfatura
from beneficiarios.forms import VinculoForm
from beneficiarios.models import Beneficiario, Vinculo
from beneficiarios.seguro_de_vida import (
    PlanilhaDoSeguroDeVida,
    mes_sugerido,
    telefone_em_partes,
)
from clientes.models import Unidade
from clientes.tests.fixtures import CPF_2

pytestmark = pytest.mark.django_db

OUTUBRO = date(2026, 10, 1)
# Colunas da planilha do escritório (as outras ficam vazias).
TITULOS = {
    "A": "Local",
    "B": "IDENTIFICADOR DE SUB",
    "C": "Empresa",
    "E": "Nome",
    "H": "Nascimento",
    "N": "CPF",
    "O": "Valor Salário",
    "P": "E-MAIL",
    "Q": "DDD",
    "R": "FONE",
    "S": "24x",
    "T": "Capital Segurado",
    "U": "Fatura",
}


def pessoa(empresa, unidade, nome, **dados):
    return Beneficiario.objects.create(cliente=empresa, unidade=unidade, nome=nome, **dados)


def na_vida(quem, plano, salario, inclusao=date(2026, 3, 1), exclusao=None):
    vinculo = Vinculo(
        beneficiario=quem,
        contrato=plano,
        data_inclusao=inclusao,
        data_exclusao=exclusao,
        salario=Decimal(salario) if salario is not None else None,
    )
    vinculo.full_clean()
    vinculo.save()
    return vinculo


def folha_de(planilha: PlanilhaDoSeguroDeVida):
    return load_workbook(BytesIO(planilha.gerar())).active


def linhas(folha, colunas="ABCEHNOPQRSTU") -> list[list]:
    return [
        [folha[f"{coluna}{numero}"].value for coluna in colunas]
        for numero in range(2, folha.max_row + 1)
    ]


# Calcula as fórmulas da planilha como o Excel (só o que a planilha usa).

OPERACOES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}
FUNCOES = {"SUM": sum, "MIN": min}


def calcular(folha, referencia: str) -> float:
    valor = folha[referencia].value
    if not (isinstance(valor, str) and valor.startswith("=")):
        return float(valor or 0)

    def faixa(achado) -> str:
        coluna, inicio, fim = achado[1], int(achado[2]), int(achado[3])
        return ",".join(f"{coluna}{numero}" for numero in range(inicio, fim + 1))

    texto = re.sub(r"([A-Z]+)(\d+):\1(\d+)", faixa, valor[1:])
    return _avaliar(ast.parse(texto, mode="eval").body, folha)


def _avaliar(no, folha) -> float:
    if isinstance(no, ast.Constant):
        return float(no.value)
    if isinstance(no, ast.Name):
        return calcular(folha, no.id)
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Div):
        return _avaliar(no.left, folha) / _avaliar(no.right, folha)
    if isinstance(no, ast.BinOp):
        return OPERACOES[type(no.op)](_avaliar(no.left, folha), _avaliar(no.right, folha))
    if isinstance(no, ast.Call):
        return FUNCOES[no.func.id]([_avaliar(arg, folha) for arg in no.args])
    raise ValueError(f"Fórmula inesperada: {ast.dump(no)}")


def total_da_linha(folha, rotulo: str) -> float:
    for numero in range(2, folha.max_row + 1):
        if folha[f"T{numero}"].value == rotulo:
            return round(calcular(folha, f"U{numero}"), 2)
    raise AssertionError(f"Sem a linha {rotulo}")


# ------------------------------------------------------------------
# Capital e fatura
# ------------------------------------------------------------------


def test_capital_e_salario_vezes_o_multiplo_ate_o_maximo(vida):
    assert vida.calcula_capital and vida.usa_salario
    assert vida.capital_de(Decimal("2500")) == Decimal("60000")
    # 24 x 20 mil passaria do máximo: vale o máximo.
    assert vida.capital_de(Decimal("20000")) == Decimal("300000")
    assert vida.capital_de(None) is None
    assert vida.fatura_de(Decimal("60000")) == Decimal("21")
    assert vida.fatura_de(None) is None


def test_sem_multiplo_o_capital_maximo_e_o_capital_de_todos(vida):
    vida.capital_multiplo = None
    assert vida.calcula_capital and not vida.usa_salario
    assert vida.capital_de(None) == vida.capital_de(Decimal("1000")) == Decimal("300000")


def test_taxa_sem_capital_nao_vale(saude):
    saude.taxa_por_mil = Decimal("0.35")
    with pytest.raises(ValidationError) as erro:
        saude.full_clean()
    assert "taxa_por_mil" in erro.value.message_dict
    assert not saude.calcula_capital
    assert saude.capital_de(Decimal("1000")) is None


def test_plano_calcula_capital_e_fatura(vida, titular):
    vinculo = na_vida(titular, vida, "3000")
    assert vinculo.capital == Decimal("72000")
    assert vinculo.fatura == Decimal("25.2")
    vinculo.salario = None
    assert vinculo.capital is None and vinculo.fatura is None


# ------------------------------------------------------------------
# Formulários
# ------------------------------------------------------------------


def test_salario_aparece_so_para_titular_com_seguro_de_vida(titular, conjuge, saude, vida):
    assert "salario" in VinculoForm(beneficiario=titular).fields
    # Dependente não tem salário, mesmo que entre no seguro de vida.
    incluir_titular = na_vida(titular, vida, "3000")
    assert "salario" not in VinculoForm(beneficiario=conjuge).fields
    # Na edição, só no plano de vida.
    assert "salario" in VinculoForm(instance=incluir_titular).fields
    no_saude = Vinculo.objects.create(
        beneficiario=titular, contrato=saude, data_inclusao=date(2026, 3, 1)
    )
    assert "salario" not in VinculoForm(instance=no_saude).fields


def test_salario_nao_aparece_sem_seguro_de_vida(titular, saude):
    assert "salario" not in VinculoForm(beneficiario=titular).fields


def test_salario_e_opcional_e_so_fica_no_plano_de_vida(logado, titular, saude, vida):
    url = reverse("beneficiarios:novo_plano", args=[titular.pk])
    resposta = logado.post(url, {"contrato": vida.pk, "data_inclusao": "01/03/2026", "salario": ""})
    assert resposta.status_code == 302
    assert titular.vinculos.get(contrato=vida).salario is None
    # Salário digitado para o plano de saúde não é guardado.
    logado.post(url, {"contrato": saude.pk, "data_inclusao": "01/03/2026", "salario": "5000"})
    assert titular.vinculos.get(contrato=saude).salario is None


def test_editar_salario_fica_no_historico(logado, titular, vida):
    vinculo = na_vida(titular, vida, None)
    url = reverse("beneficiarios:editar_plano", args=[vinculo.pk])
    resposta = logado.post(
        url, {"carteirinha": "", "data_inclusao": "01/03/2026", "salario": "4200.50"}
    )
    assert resposta.status_code == 302
    vinculo.refresh_from_db()
    assert vinculo.salario == Decimal("4200.50")
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    assert "Salário R$ 4.200,50" in pagina and "Capital R$ 100.812,00" in pagina
    assert "salário (R$)" in pagina  # no histórico de alterações


def test_pagina_da_pessoa_leva_a_preencher_o_salario(logado, titular, conjuge, vida):
    vinculo = na_vida(titular, vida, None)
    na_vida(conjuge, vida, None)
    pagina = logado.get(titular.get_absolute_url()).content.decode()
    editar = reverse("beneficiarios:editar_plano", args=[vinculo.pk])
    assert f'não informado</span> (<a href="{editar}">preencher</a>)' in pagina
    # Dependente não tem salário: a linha do plano mostra só o capital.
    assert "Salário" not in logado.get(conjuge.get_absolute_url()).content.decode()


def test_contrato_tem_cartao_do_seguro_de_vida(logado, vida):
    url = reverse("apolices:editar_contrato", args=[vida.pk])
    pagina = logado.get(url).content.decode()
    assert "Só para seguro de vida: capital e fatura de cada vida" in pagina
    # A taxa aparece sem zeros sobrando.
    assert 'value="0.35"' in pagina


def test_salvar_contrato_com_capital(logado, empresa, seguradora, matriz, saude):
    url = reverse("apolices:editar_contrato", args=[saude.pk])
    dados = {
        "seguradora": seguradora.pk,
        "ramo": saude.ramo_id,
        "numero": saude.numero,
        "modalidade": "EM",
        "situacao": "ATV",
        "inicio_vigencia": "01/01/2026",
        "dia_vencimento": 10,
        "unidades": [matriz.pk],
        "capital_multiplo": 36,
        "capital_maximo": "1000000",
        "taxa_por_mil": "0.4",
    }
    assert logado.post(url, dados).status_code == 302
    saude.refresh_from_db()
    assert (saude.capital_multiplo, saude.capital_maximo, saude.taxa_por_mil) == (
        36,
        Decimal("1000000"),
        Decimal("0.4"),
    )


# ------------------------------------------------------------------
# Planilha do mês
# ------------------------------------------------------------------


@pytest.fixture
def grupo(empresa, matriz, filial, irma, vida):
    """Vidas fictícias em três filiais; a irmã paga boleto separado."""
    Subfatura.objects.create(contrato=vida, unidade=matriz, local="1", identificador="10")
    Subfatura.objects.create(contrato=vida, unidade=filial, local="3", identificador="2")
    vida.unidades.add(irma)
    Subfatura.objects.create(
        contrato=vida, unidade=irma, local="1", identificador="11", boleto_separado=True
    )
    ana = pessoa(
        empresa,
        filial,
        "Ana Filial",
        cpf=CPF_2,
        data_nascimento=date(1990, 4, 12),
        email="ana@exemplo.test",
        telefone="(11) 98765-4321",
    )
    na_vida(ana, vida, "2500")
    na_vida(pessoa(empresa, matriz, "Bia Matriz"), vida, "20000")
    na_vida(pessoa(empresa, matriz, "Caio Matriz"), vida, None)
    na_vida(pessoa(empresa, irma, "Duda Irmã"), vida, "3000")
    na_vida(pessoa(empresa, irma, "Eva Irmã"), vida, "1000.50")
    # Fora do mês: entrou depois do dia 1º e saiu antes.
    na_vida(pessoa(empresa, matriz, "Fábio Novo"), vida, "5000", inclusao=date(2026, 10, 2))
    na_vida(
        pessoa(empresa, matriz, "Gil Saiu"),
        vida,
        "5000",
        exclusao=OUTUBRO,
    )
    return vida


def test_planilha_tem_as_vidas_do_dia_primeiro_no_layout_do_escritorio(grupo):
    planilha = PlanilhaDoSeguroDeVida(grupo, date(2026, 10, 15))
    folha = folha_de(planilha)

    assert folha.title == "seguro de vida 01.10.2026"
    assert planilha.nome_do_arquivo == "seguro-de-vida-supermercados-exemplo-2026-10.xlsx"
    assert {coluna: folha[f"{coluna}1"].value for coluna in TITULOS} == TITULOS
    assert all(folha[f"{coluna}1"].value is None for coluna in "DFGIJKLM")
    assert folha.freeze_panes == "A2"
    # Em ordem de subfatura (2 antes de 10) e de nome.
    assert [linha[3] for linha in linhas(folha)[:5]] == [
        "Ana Filial",
        "Bia Matriz",
        "Caio Matriz",
        "Duda Irmã",
        "Eva Irmã",
    ]
    ana = linhas(folha)[0]
    assert ana[:4] == [3, 2, "Supermercados Exemplo Filial Ltda", "Ana Filial"]
    assert ana[4].date() == date(1990, 4, 12)
    assert ana[5:10] == ["111.444.777-35", 2500, "ana@exemplo.test", 11, 987654321]
    assert ana[10:] == ["=O2*24", "=MIN(S2,300000)", "=(T2*0.35)/1000"]
    assert folha["H2"].number_format == "DD/MM/YYYY"
    # Sem salário: a célula fica em branco para preencher no Excel.
    assert linhas(folha)[2][6] is None


def test_totais_da_planilha_batem_com_o_resumo_da_tela(grupo):
    planilha = PlanilhaDoSeguroDeVida(grupo, OUTUBRO)
    folha = folha_de(planilha)

    # Ana 60.000 (21,00); Bia no máximo 300.000 (105,00); Caio sem salário;
    # Duda 72.000 (25,20) e Eva 24.012 (8,4042), da irmã, com boleto separado.
    assert planilha.fatura_total == Decimal("159.60")
    assert planilha.capital_total == Decimal("456012")
    assert [(g.rotulo, g.fatura) for g in planilha.boletos_separados] == [
        ("Boleto separado: Mercado Irmão Ltda", Decimal("33.60"))
    ]
    assert planilha.fatura_sem_os_separados == Decimal("126.00")
    assert total_da_linha(folha, "Total") == 159.60
    assert total_da_linha(folha, "Boleto separado: Mercado Irmão Ltda") == 33.60
    assert total_da_linha(folha, "Total sem o boleto separado") == 126.00
    assert folha["U7"].value == "=SUM(U2:U6)"
    assert folha["U8"].value == "=SUM(U5:U6)"
    assert folha["U9"].value == "=U7-U8"


def test_quem_preenche_o_salario_no_excel_ve_recalcular(grupo):
    folha = folha_de(PlanilhaDoSeguroDeVida(grupo, OUTUBRO))
    assert calcular(folha, "T4") == 0
    folha["O4"] = 5000
    assert calcular(folha, "T4") == 120000
    assert round(calcular(folha, "U7"), 2) == round(159.60 + 42, 2)


def test_avisos_de_vidas_sem_salario_e_sem_subfatura(grupo, empresa, matriz):
    Subfatura.objects.filter(unidade=matriz).delete()
    planilha = PlanilhaDoSeguroDeVida(grupo, OUTUBRO)
    assert [vida.pessoa.nome for vida in planilha.sem_salario] == ["Caio Matriz"]
    assert sorted(vida.pessoa.nome for vida in planilha.sem_subfatura) == [
        "Bia Matriz",
        "Caio Matriz",
    ]
    # Sem subfatura, Local e SUB saem em branco e as vidas vão para o fim.
    assert [linha[:4] for linha in linhas(folha_de(planilha))[3:5]] == [
        [None, None, "Supermercados Exemplo Ltda", "Bia Matriz"],
        [None, None, "Supermercados Exemplo Ltda", "Caio Matriz"],
    ]


def test_sem_vidas_a_planilha_sai_so_com_os_titulos(vida):
    folha = folha_de(PlanilhaDoSeguroDeVida(vida, OUTUBRO))
    assert folha.max_row == 1
    assert folha["U1"].value == "Fatura"


def test_sem_taxa_nao_ha_fatura(grupo):
    grupo.taxa_por_mil = None
    planilha = PlanilhaDoSeguroDeVida(grupo, OUTUBRO)
    folha = folha_de(planilha)
    assert planilha.fatura_total is None and planilha.boletos_separados == []
    assert folha["U2"].value is None and folha.max_row == 6


def test_capital_fixo_nao_precisa_de_salario(grupo):
    grupo.capital_multiplo = None
    planilha = PlanilhaDoSeguroDeVida(grupo, OUTUBRO)
    folha = folha_de(planilha)
    assert planilha.sem_salario == []
    assert folha["S1"].value is None and folha["S2"].value is None
    assert folha["T2"].value == 300000
    assert planilha.fatura_total == Decimal("525.00")


def test_texto_com_igual_no_comeco_nao_vira_formula(vida, empresa, matriz):
    na_vida(pessoa(empresa, matriz, "=HYPERLINK(1)"), vida, "1000")
    folha = folha_de(PlanilhaDoSeguroDeVida(vida, OUTUBRO))
    assert folha["E2"].data_type == "s"


@pytest.mark.parametrize(
    ("hoje", "esperado"),
    [
        (date(2026, 9, 19), date(2026, 9, 1)),
        (date(2026, 9, 20), date(2026, 10, 1)),
        (date(2026, 12, 30), date(2027, 1, 1)),
        (date(2027, 1, 3), date(2027, 1, 1)),
    ],
)
def test_mes_sugerido(hoje, esperado):
    assert mes_sugerido(hoje) == esperado


@pytest.mark.parametrize(
    ("telefone", "esperado"),
    [
        ("(11) 98765-4321", ("11", "987654321")),
        ("+55 21 3000-0000", ("21", "30000000")),
        ("011 3000-0000", ("11", "30000000")),
        ("98765-4321", ("", "987654321")),
        ("", ("", "")),
    ],
)
def test_telefone_em_partes(telefone, esperado):
    assert telefone_em_partes(telefone) == esperado


# ------------------------------------------------------------------
# Página
# ------------------------------------------------------------------


def test_pagina_mostra_o_resumo_e_baixa_a_planilha(logado, grupo):
    url = reverse("beneficiarios:seguro_de_vida", args=[grupo.pk])
    pagina = logado.get(url, {"mes": "10/2026"}).content.decode()
    assert "Resumo para conferir a cobrança" in pagina
    assert "R$ 159,60" in pagina and "R$ 33,60" in pagina and "R$ 126,00" in pagina
    assert "Prazo de envio: até 05/10/2026" in pagina
    assert "1 vida sem salário" in pagina and "Caio Matriz" in pagina

    resposta = logado.get(url, {"mes": "10/2026", "baixar": "1"})
    assert resposta["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "seguro-de-vida-supermercados-exemplo-2026-10.xlsx" in resposta["Content-Disposition"]
    assert resposta["Cache-Control"] == "private, no-store"
    folha = load_workbook(BytesIO(b"".join(resposta.streaming_content))).active
    assert folha.title == "seguro de vida 01.10.2026"


def test_pagina_sugere_o_mes_e_avisa_sem_capital(logado, saude, vida):
    pagina = logado.get(reverse("beneficiarios:seguro_de_vida", args=[saude.pk])).content
    assert "ainda não tem o capital configurado" in pagina.decode()
    pagina = logado.get(reverse("beneficiarios:seguro_de_vida", args=[vida.pk])).content
    assert f"Vidas em {mes_sugerido(date.today()):%d/%m/%Y}" in pagina.decode()


def test_mes_invalido_mostra_o_erro(logado, vida):
    url = reverse("beneficiarios:seguro_de_vida", args=[vida.pk])
    resposta = logado.get(url, {"mes": "13/2026", "baixar": "1"})
    assert resposta.status_code == 200
    assert "Mês inválido" in resposta.content.decode()


def test_salvar_subfaturas(logado, vida, matriz, filial):
    url = reverse("beneficiarios:seguro_de_vida", args=[vida.pk])
    dados = {
        "mes": "10/2026",
        f"unidade-{matriz.pk}-local": "7",
        f"unidade-{matriz.pk}-identificador": "12",
        f"unidade-{matriz.pk}-boleto_separado": "on",
        f"unidade-{filial.pk}-local": "",
        f"unidade-{filial.pk}-identificador": "",
    }
    resposta = logado.post(url, dados)
    assert resposta.status_code == 302 and resposta.url == f"{url}?mes=10%2F2026"
    # Só a filial preenchida ganha subfatura.
    assert list(
        vida.subfaturas.values_list("unidade", "local", "identificador", "boleto_separado")
    ) == [(matriz.pk, "7", "12", True)]
    historico = logado.get(vida.cliente.get_absolute_url()).content.decode()
    assert "Subfatura: Supermercados Exemplo Ltda · SUB 12" in historico


def test_subfatura_grande_demais_mostra_o_erro(logado, vida, matriz):
    url = reverse("beneficiarios:seguro_de_vida", args=[vida.pk])
    resposta = logado.post(url, {f"unidade-{matriz.pk}-identificador": "9" * 21})
    assert resposta.status_code == 200
    assert "no máximo 20 caracteres" in resposta.content.decode()
    assert not vida.subfaturas.exists()


def test_pagina_pede_login(client, vida):
    resposta = client.get(reverse("beneficiarios:seguro_de_vida", args=[vida.pk]))
    assert resposta.status_code == 302 and "/entrar/" in resposta.url


def test_atalhos_para_a_planilha(logado, empresa, vida, saude):
    planilha_mensal = logado.get(reverse("movimentacoes:planilha")).content.decode()
    url = reverse("beneficiarios:seguro_de_vida", args=[vida.pk])
    assert url in planilha_mensal
    cliente = logado.get(empresa.get_absolute_url()).content.decode()
    assert url in cliente
    assert reverse("beneficiarios:seguro_de_vida", args=[saude.pk]) not in cliente


def test_excluir_filial_leva_junto_a_subfatura(vida, empresa):
    avulsa = Unidade.objects.create(
        cliente=empresa, cnpj="44777000100040", razao_social="Filial Sem Contrato"
    )
    Subfatura.objects.create(contrato=vida, unidade=avulsa, identificador="5")
    avulsa.excluir()
    assert not Subfatura.objects.exists()
    assert Contrato.objects.filter(pk=vida.pk).exists()
