"""O que cada relatório busca no banco, a partir dos filtros já conferidos pelo formulário.

Cada relatório faz um número fixo de consultas, qualquer que seja o tamanho da carteira.
"""

from datetime import date

from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce, NullIf

from apolices.models import Contrato
from beneficiarios.models import Vinculo
from beneficiarios.vidas import anotar_vidas
from clientes.models import Contato
from movimentacoes.models import ETAPAS_EM_ABERTO, Etapa, Movimentacao


def vidas_ativas(dados: dict):
    """Cada plano em vigor na data (uma vida), como na contagem de `beneficiarios/vidas.py`."""
    vinculos = Vinculo.objects.ativos(dados.get("data") or date.today()).select_related(
        "beneficiario__cliente",
        "beneficiario__unidade",
        "beneficiario__titular__unidade",
        "contrato__ramo",
        "contrato__seguradora",
        "plano",
    )
    if cliente := dados.get("cliente"):
        vinculos = vinculos.filter(beneficiario__cliente=cliente)
    if unidade := dados.get("unidade"):
        # O dependente fica na unidade do titular.
        vinculos = vinculos.filter(
            Q(beneficiario__unidade=unidade) | Q(beneficiario__titular__unidade=unidade)
        )
    if contrato := dados.get("contrato"):
        vinculos = vinculos.filter(contrato=contrato)
    # Por cliente e filial, com cada família junta: o titular e, logo abaixo, os dependentes.
    return vinculos.annotate(
        # O nome que aparece: o fantasia ou, sem ele, a razão social da unidade do titular.
        filial=Coalesce(
            NullIf("beneficiario__unidade__nome_fantasia", Value("")),
            "beneficiario__unidade__razao_social",
            NullIf("beneficiario__titular__unidade__nome_fantasia", Value("")),
            "beneficiario__titular__unidade__razao_social",
        ),
        familia=Coalesce("beneficiario__titular__nome", "beneficiario__nome"),
        dependente=Case(
            When(beneficiario__titular__isnull=False, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by(
        "beneficiario__cliente__nome",
        F("filial").asc(nulls_last=True),
        "familia",
        "dependente",
        "beneficiario__nome",
        "contrato__ramo__nome",
    )


def resumo_das_vidas(vinculos) -> dict:
    numeros = vinculos.aggregate(
        vidas=Count("pk"),
        pessoas=Count("beneficiario", distinct=True),
        titulares=Count("beneficiario", distinct=True, filter=Q(dependente=0)),
    )
    por_contrato = (
        vinculos.order_by(
            "contrato__cliente__nome", "contrato__ramo__nome", "contrato__numero", "plano__nome"
        )
        .values(
            "contrato",
            "contrato__cliente__nome",
            "contrato__ramo__nome",
            "contrato__seguradora__nome",
            "contrato__numero",
            "contrato__produto",
            # Nos contratos com vários planos, uma linha por plano.
            "plano__nome",
        )
        .annotate(vidas=Count("pk"))
    )
    return {
        **numeros,
        "dependentes": numeros["pessoas"] - numeros["titulares"],
        "por_contrato": list(por_contrato),
    }


def movimentacoes_do_periodo(dados: dict):
    campo = "enviada_em" if dados["contar_por"] == "envio" else "vigencia"
    movimentacoes = Movimentacao.objects.select_related(
        "cliente",
        "beneficiario__unidade",
        "beneficiario__titular__unidade",
        "contrato__ramo",
        "contrato__seguradora",
        "contrato_anterior",
        "plano",
        "plano_anterior",
    ).filter(**{f"{campo}__range": (dados["de"], dados["ate"])})
    if dados["tipo"] != "todos":
        movimentacoes = movimentacoes.filter(tipo=dados["tipo"])
    situacao = dados.get("situacao")
    if situacao == "aberto":
        movimentacoes = movimentacoes.filter(etapa__in=ETAPAS_EM_ABERTO)
    elif situacao:
        movimentacoes = movimentacoes.filter(etapa=situacao)
    if cliente := dados.get("cliente"):
        movimentacoes = movimentacoes.filter(cliente=cliente)
    if contrato := dados.get("contrato"):
        # Na alteração de plano, vale o plano de onde a pessoa sai e o plano para onde vai.
        movimentacoes = movimentacoes.filter(Q(contrato=contrato) | Q(contrato_anterior=contrato))
    return movimentacoes.order_by(campo, "cliente__nome", "beneficiario__nome", "pk")


NOMES_DAS_ETAPAS = {
    Etapa.EM_ANALISE: ("em análise", "em análise"),
    Etapa.APROVADA: ("aprovada", "aprovadas"),
    Etapa.CONCLUIDA: ("concluída", "concluídas"),
    Etapa.REJEITADA: ("rejeitada", "rejeitadas"),
    Etapa.CANCELADA: ("cancelada", "canceladas"),
}


def resumo_das_movimentacoes(movimentacoes) -> dict:
    por_etapa = dict(movimentacoes.order_by().values_list("etapa").annotate(quantas=Count("pk")))
    etapas = [
        f"{por_etapa[etapa]} {NOMES_DAS_ETAPAS[etapa][por_etapa[etapa] != 1]}"
        for etapa in Etapa
        if etapa in por_etapa
    ]
    return {"total": sum(por_etapa.values()), "por_etapa": por_etapa, "etapas": etapas}


def apolices(dados: dict):
    contratos = Contrato.objects.select_related("cliente", "ramo", "seguradora").prefetch_related(
        "cliente__unidades",
        Prefetch(
            "cliente__contatos",
            queryset=Contato.objects.filter(principal=True),
            to_attr="contatos_principais",
        ),
    )
    situacao = dados.get("situacao", "")
    if situacao == "":
        contratos = contratos.vigentes()
    elif situacao != "todas":
        contratos = contratos.filter(situacao=situacao)
    if seguradora := dados.get("seguradora"):
        contratos = contratos.filter(seguradora=seguradora)
    if ramo := dados.get("ramo"):
        contratos = contratos.filter(ramo=ramo)
    if de := dados.get("renovacao_de"):
        contratos = contratos.filter(data_renovacao__gte=de)
    if ate := dados.get("renovacao_ate"):
        contratos = contratos.filter(data_renovacao__lte=ate)
    return anotar_vidas(contratos).order_by(
        F("data_renovacao").asc(nulls_last=True), "cliente__nome", "numero"
    )


def resumo_das_apolices(contratos) -> dict:
    numeros = contratos.aggregate(total=Count("pk"), valor=Sum("valor_mensal"))
    numeros["vidas"] = Vinculo.objects.ativos().filter(contrato__in=contratos.values("pk")).count()
    return numeros


def dados_do_cliente(cliente) -> dict:
    """Documento e contato do cliente, como no relatório de apólices.

    Na empresa, o telefone e o e-mail são os do contato principal e, na falta deles, os da
    matriz; a cidade é a da matriz. Na pessoa física, tudo vem do próprio cadastro.
    """
    contato = next(iter(getattr(cliente, "contatos_principais", [])), None)
    base = cliente
    if cliente.eh_empresa:
        unidades = sorted(
            cliente.unidades.all(), key=lambda unidade: (not unidade.matriz, unidade.pk)
        )
        base = unidades[0] if unidades else cliente
    telefone = contato and (contato.telefone or contato.whatsapp)
    return {
        "documento": cliente.documento_principal,
        "contato": contato.nome if contato else "",
        "telefone": telefone or base.telefone or base.whatsapp,
        "email": (contato and contato.email) or base.email,
        "cidade": f"{base.cidade}/{base.uf}" if base.cidade and base.uf else base.cidade,
    }
