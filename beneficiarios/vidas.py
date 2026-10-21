"""Número de vidas: pessoas ativas em cada plano, por contrato, unidade (filial) e grupo.

Uma vida é um beneficiário (titular ou dependente) com o plano em vigor na data.
Quem está na saúde e no dental conta uma vez em cada contrato e uma vez só no
total de pessoas do grupo.
"""

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce

from beneficiarios.models import Vinculo
from clientes.models import Cliente


def anotar_vidas(contratos, em: date | None = None):
    """Acrescenta `vidas` a cada contrato do queryset."""
    ativos = (
        Vinculo.objects.ativos(em)
        .filter(contrato=OuterRef("pk"))
        .order_by()
        .values("contrato")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return contratos.annotate(vidas=Coalesce(Subquery(ativos), 0))


@dataclass
class VidasDoCliente:
    """Quadro de vidas de um cliente: filial x contrato, com totais."""

    cliente: Cliente
    em: date | None = None
    por_celula: dict[tuple[int | None, int], int] = field(init=False)
    pessoas_por_unidade: dict[int | None, int] = field(init=False)
    por_contrato: dict[int, int] = field(init=False)
    total_pessoas: int = field(init=False)

    def __post_init__(self) -> None:
        ativos = Vinculo.objects.ativos(self.em).filter(beneficiario__cliente=self.cliente)
        ativos = ativos.annotate(
            unidade_efetiva=Coalesce("beneficiario__unidade", "beneficiario__titular__unidade")
        )
        linhas = ativos.values("unidade_efetiva", "contrato").annotate(
            vidas=Count("pk"), pessoas=Count("beneficiario", distinct=True)
        )
        self.por_celula = {(ln["unidade_efetiva"], ln["contrato"]): ln["vidas"] for ln in linhas}
        self.por_contrato = {}
        for (_, contrato), vidas in self.por_celula.items():
            self.por_contrato[contrato] = self.por_contrato.get(contrato, 0) + vidas
        pessoas = ativos.values("unidade_efetiva").annotate(
            total=Count("beneficiario", distinct=True)
        )
        self.pessoas_por_unidade = {ln["unidade_efetiva"]: ln["total"] for ln in pessoas}
        self.total_pessoas = ativos.values("beneficiario").distinct().count()

    def quadro(self, contratos, unidades) -> list[dict]:
        """Linhas prontas para a tabela: uma por unidade, uma coluna por contrato."""
        linhas = []
        for unidade in [*unidades, None]:
            chave = unidade.pk if unidade else None
            if unidade is None and chave not in self.pessoas_por_unidade:
                continue
            linhas.append(
                {
                    "unidade": unidade,
                    "celulas": [self.por_celula.get((chave, c.pk), 0) for c in contratos],
                    "pessoas": self.pessoas_por_unidade.get(chave, 0),
                }
            )
        return linhas

    def da_unidade(self, unidade_pk: int) -> int:
        return self.pessoas_por_unidade.get(unidade_pk, 0)
