"""Busca rápida do menu: acha pessoas, clientes, contratos e veículos de uma vez."""

import re
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Exists, OuterRef, Prefetch, Q

from apolices.models import BemSegurado, Contrato
from beneficiarios.models import Beneficiario, Vinculo
from clientes.models import Cliente

# Menos que isso acharia meia carteira (ex.: "a").
TAMANHO_MINIMO = 2
# Quantos resultados de cada grupo aparecem; o resto pede uma busca mais precisa.
LIMITE = 30


def palavras_do_nome(termo: str, campo: str) -> Q:
    """Cada palavra precisa aparecer no nome, em qualquer ordem ("maria silva" acha
    "Maria da Silva")."""
    filtro = Q()
    for palavra in termo.split():
        filtro &= Q(**{f"{campo}__icontains": palavra})
    return filtro


def so_letras_e_numeros(termo: str) -> str:
    """CPF, CNPJ (que pode ter letras) e placa ficam guardados sem pontuação, em maiúsculas."""
    return re.sub(r"[^0-9A-Za-z]", "", termo).upper()


@dataclass
class Grupo:
    titulo: str
    itens: list
    total: int

    @property
    def tem_mais(self) -> bool:
        return self.total > len(self.itens)


@dataclass
class ResultadoDaBusca:
    termo: str
    grupos: list[Grupo] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(grupo.total for grupo in self.grupos)

    @property
    def unico(self):
        """O único registro encontrado, para abrir direto a página dele."""
        if self.total != 1:
            return None
        return next(grupo.itens[0] for grupo in self.grupos if grupo.itens)


class BuscaRapida:
    def __init__(self, termo: str):
        self.termo = " ".join((termo or "").split())
        self.documento = so_letras_e_numeros(self.termo)
        self.tem_digito = bool(re.search(r"\d", self.termo))

    @property
    def curta_demais(self) -> bool:
        return len(self.termo) < TAMANHO_MINIMO

    def resultado(self) -> ResultadoDaBusca:
        resultado = ResultadoDaBusca(self.termo)
        if self.curta_demais:
            return resultado
        for titulo, consulta in [
            ("Pessoas (beneficiários)", self.pessoas()),
            ("Clientes", self.clientes()),
            ("Contratos", self.contratos()),
            ("Veículos", self.veiculos()),
        ]:
            total = consulta.count()
            if total:
                resultado.grupos.append(Grupo(titulo, list(consulta[:LIMITE]), total))
        return resultado

    def pessoas(self):
        termo = self.termo
        filtro = (
            palavras_do_nome(termo, "nome")
            | Q(matricula__iexact=termo)
            | Q(vinculos__carteirinha__iexact=termo)
        )
        if self.tem_digito and len(self.documento) >= 3:
            filtro |= Q(cpf__contains=self.documento)
        hoje = date.today()
        planos = Vinculo.objects.filter(beneficiario=OuterRef("pk"))
        em_vigor = planos.filter(Q(data_exclusao__isnull=True) | Q(data_exclusao__gt=hoje))
        ids = Beneficiario.objects.filter(filtro).values("pk")
        return (
            Beneficiario.objects.filter(pk__in=ids)
            # Como na lista de beneficiários: inativo é quem saiu de todos os planos.
            .annotate(tem_plano=Exists(planos), em_algum_plano=Exists(em_vigor))
            .select_related("cliente", "titular__unidade", "unidade")
            .prefetch_related(
                Prefetch(
                    "vinculos",
                    queryset=Vinculo.objects.ativos().select_related("contrato__ramo", "plano"),
                    to_attr="planos",
                )
            )
            .order_by("nome", "pk")
        )

    def clientes(self):
        ids = Cliente.objects.buscar(self.termo).values("pk")
        por_palavras = Cliente.objects.filter(palavras_do_nome(self.termo, "nome")).values("pk")
        return (
            Cliente.objects.filter(Q(pk__in=ids) | Q(pk__in=por_palavras))
            .prefetch_related("unidades")
            .order_by("nome", "pk")
        )

    def contratos(self):
        # Sem algarismo, só o número exato: "Exemplo" não traz os contratos de cada cliente
        # já encontrado pelo nome.
        filtro = Q(numero__iexact=self.termo)
        if self.tem_digito and len(self.documento) >= 3:
            filtro |= Q(numero__icontains=self.termo)
        return (
            Contrato.objects.filter(filtro)
            .select_related("cliente", "ramo", "seguradora")
            .order_by("cliente__nome", "numero")
        )

    def veiculos(self):
        if not self.tem_digito or len(self.documento) < 3:
            return BemSegurado.objects.none()
        return (
            BemSegurado.objects.filter(placa__contains=self.documento)
            .select_related("contrato__cliente", "contrato__seguradora")
            .order_by("placa")
        )


def endereco(registro) -> str:
    """Página que a busca abre para o registro (o contrato fica na página do cliente)."""
    if isinstance(registro, Contrato):
        return f"{registro.cliente.get_absolute_url()}#contratos"
    return registro.get_absolute_url()
