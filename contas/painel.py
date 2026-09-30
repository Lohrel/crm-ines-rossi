"""Painel da página inicial: o que precisa de atenção hoje, sem abrir tela por tela.

Cada quadro mostra um número e leva à lista já filtrada, que mostra os mesmos
registros. As contas são feitas no banco: cada quadro faz duas consultas,
qualquer que seja o tamanho da carteira.
"""

from calendar import monthrange
from datetime import date, timedelta
from functools import cached_property

from django.db.models import Count, Q
from django.urls import reverse
from django.utils.http import urlencode

from apolices.models import DIAS_PARA_RENOVACAO, Contrato
from beneficiarios.seguro_de_vida import DIA_LIMITE_DE_ENVIO
from boletos.forms import FiltroBoletosForm
from boletos.models import DIAS_DE_ANTECEDENCIA as DIAS_DOS_BOLETOS
from boletos.models import Boleto, somar_meses
from calendario.agenda import Agenda, lista_por_dia
from clientes.prazos import quando, texto_do_prazo
from movimentacoes.models import Etapa, Movimentacao
from pendencias.forms import FiltroPendenciasForm
from pendencias.models import DIAS_DE_ANTECEDENCIA as DIAS_DAS_PENDENCIAS
from pendencias.models import Pendencia

# Quantos registros cada quadro lista, os mais urgentes primeiro.
ITENS_POR_QUADRO = 3
# Quantos dias antes os prazos do mês (fechamento e planilha do seguro de vida) ficam em amarelo.
DIAS_DE_AVISO_DOS_PRAZOS = 5
# Quantos dias o quadro do calendário mostra, contando hoje.
DIAS_DA_SEMANA = 7


def url(nome: str, **filtros) -> str:
    """Endereço de uma lista, já com os filtros."""
    endereco = reverse(nome)
    return f"{endereco}?{urlencode(filtros)}" if filtros else endereco


def proxima_data(dia: int, hoje: date) -> date:
    """Próxima data com este dia do mês, contando hoje; em meses mais curtos, o último dia."""

    def no_mes(mes: date) -> date:
        return mes.replace(day=min(dia, monthrange(mes.year, mes.month)[1]))

    data = no_mes(hoje)
    return data if data >= hoje else no_mes(somar_meses(hoje, 1))


class Painel:
    """Os quadros da página inicial, para quem está logado."""

    def __init__(self, usuario, hoje: date | None = None):
        self.usuario = usuario
        self.hoje = hoje or date.today()

    def _dias_ate(self, data: date) -> int:
        return (data - self.hoje).days

    def _com_prazo(self, registro, prazo: date) -> dict:
        """Boleto ou pendência com o texto do prazo, ex.: "vence em 3 dias"."""
        dias = self._dias_ate(prazo)
        return {"registro": registro, "venceu": dias < 0, "prazo": texto_do_prazo(dias)}

    @cached_property
    def movimentacoes(self) -> dict:
        """Em análise e aprovadas (falta concluir), com as há mais tempo em aberto."""
        em_aberto = Movimentacao.objects.em_aberto()
        numeros = em_aberto.aggregate(
            total=Count("pk"),
            em_analise=Count("pk", filter=Q(etapa=Etapa.EM_ANALISE)),
            aprovadas=Count("pk", filter=Q(etapa=Etapa.APROVADA)),
        )
        mais_antigas = em_aberto.select_related(
            "beneficiario", "cliente", "contrato__ramo", "contrato__seguradora"
        ).order_by("recebida_em", "pk")[:ITENS_POR_QUADRO]
        return {
            **numeros,
            "itens": [
                {"movimentacao": mov, "dias": (self.hoje - mov.recebida_em).days}
                for mov in mais_antigas
            ],
            "url": url("movimentacoes:lista"),
            "url_em_analise": url("movimentacoes:lista", situacao=Etapa.EM_ANALISE),
            "url_aprovadas": url("movimentacoes:lista", situacao=Etapa.APROVADA),
        }

    @cached_property
    def boletos(self) -> dict:
        """A enviar, vencidos e dos próximos dias."""
        limite = self.hoje + timedelta(days=DIAS_DOS_BOLETOS)
        pedem_atencao = Boleto.objects.a_enviar().filter(vencimento__lte=limite)
        numeros = pedem_atencao.aggregate(
            total=Count("pk"), vencidos=Count("pk", filter=Q(vencimento__lt=self.hoje))
        )
        primeiros = pedem_atencao.select_related(
            "contrato__cliente", "contrato__seguradora"
        ).order_by("vencimento", "contrato__cliente__nome", "pk")[:ITENS_POR_QUADRO]
        return {
            **numeros,
            "vencendo": numeros["total"] - numeros["vencidos"],
            "dias": DIAS_DOS_BOLETOS,
            "itens": [self._com_prazo(boleto, boleto.vencimento) for boleto in primeiros],
            "url": url("boletos:lista", situacao=FiltroBoletosForm.ATENCAO),
        }

    @cached_property
    def pendencias(self) -> dict:
        """As da pessoa logada vencidas e dos próximos dias; as da equipe só contadas."""
        limite = self.hoje + timedelta(days=DIAS_DAS_PENDENCIAS)
        em_aberto = Pendencia.objects.em_aberto()
        minhas = Q(responsavel=self.usuario)
        pedem_atencao = Q(prazo__lte=limite)
        vencidas = Q(prazo__lt=self.hoje)
        numeros = em_aberto.aggregate(
            minhas_em_aberto=Count("pk", filter=minhas),
            minhas=Count("pk", filter=minhas & pedem_atencao),
            minhas_vencidas=Count("pk", filter=minhas & vencidas),
            equipe=Count("pk", filter=pedem_atencao),
            equipe_vencidas=Count("pk", filter=vencidas),
        )
        primeiras = (
            em_aberto.filter(minhas & pedem_atencao)
            .select_related("cliente", "unidade", "contrato__seguradora")
            .order_by("prazo", "criado_em", "pk")[:ITENS_POR_QUADRO]
        )
        atencao = FiltroPendenciasForm.ATENCAO
        return {
            **numeros,
            "minhas_vencendo": numeros["minhas"] - numeros["minhas_vencidas"],
            "dias": DIAS_DAS_PENDENCIAS,
            "itens": [self._com_prazo(pendencia, pendencia.prazo) for pendencia in primeiras],
            "url": url("pendencias:lista", responsavel=self.usuario.pk, situacao=atencao),
            "url_minhas_em_aberto": url("pendencias:lista", responsavel=self.usuario.pk),
            "url_equipe": url("pendencias:lista", situacao=atencao),
        }

    @cached_property
    def prazos(self) -> list[dict]:
        """Próximos fechamentos das movimentações e o envio da planilha do seguro de vida."""
        vigentes = Contrato.objects.vigentes()
        fechamentos = (
            vigentes.de_pessoas()
            .filter(dia_fechamento__isnull=False)
            .order_by()
            .values("dia_fechamento")
            .annotate(contratos=Count("pk"))
        )
        # Os contratos podem fechar em dias diferentes: entram os próximos fechamentos.
        linhas = sorted(
            (
                {
                    "titulo": "Fechamento das movimentações",
                    "data": proxima_data(grupo["dia_fechamento"], self.hoje),
                    "contratos": grupo["contratos"],
                    "url": url("movimentacoes:lista"),
                }
                for grupo in fechamentos
            ),
            key=lambda linha: linha["data"],
        )[:ITENS_POR_QUADRO]
        if contratos_de_vida := vigentes.com_capital().count():
            envio = proxima_data(DIA_LIMITE_DE_ENVIO, self.hoje)
            linhas.append(
                {
                    "titulo": "Envio da planilha do seguro de vida",
                    "data": envio,
                    "contratos": contratos_de_vida,
                    "url": url("movimentacoes:planilha"),
                }
            )
        for linha in linhas:
            dias = self._dias_ate(linha["data"])
            linha["quando"] = quando(dias)
            linha["perto"] = dias <= DIAS_DE_AVISO_DOS_PRAZOS
        return sorted(linhas, key=lambda linha: linha["data"])

    @cached_property
    def semana(self) -> dict:
        """O que a equipe anotou no calendário (férias, reuniões...) para os próximos dias.

        Pendências, renovações e prazos do mês já têm quadro próprio, então não se repetem
        aqui. Um evento de vários dias aparece uma vez só, no primeiro dia da semana.
        """
        ate = self.hoje + timedelta(days=DIAS_DA_SEMANA - 1)
        datas = Agenda(self.hoje, ate, self.hoje).anotacoes_por_dia()
        return {
            "dias": [
                {"data": dia, "dias": self._dias_ate(dia), "itens": itens}
                for dia, itens in lista_por_dia(datas, self.hoje, ate)
            ],
            "total_de_dias": DIAS_DA_SEMANA,
            "url": url("calendario:mes"),
            "url_novo": url("calendario:novo"),
        }

    @cached_property
    def renovacoes(self) -> dict:
        """Vigentes que renovam nos próximos dias; os com a data já passada, só contados."""
        limite = self.hoje + timedelta(days=DIAS_PARA_RENOVACAO)
        renovam = Contrato.objects.renovam_ate(limite)
        passou = Q(data_renovacao__lt=self.hoje)
        numeros = renovam.aggregate(
            total=Count("pk", filter=~passou), passadas=Count("pk", filter=passou)
        )
        proximos = (
            renovam.exclude(passou)
            .select_related("cliente", "ramo", "seguradora")
            .order_by("data_renovacao", "cliente__nome", "pk")[:ITENS_POR_QUADRO]
        )
        return {
            **numeros,
            "dias": DIAS_PARA_RENOVACAO,
            "itens": [
                {"contrato": contrato, "quando": quando(self._dias_ate(contrato.data_renovacao))}
                for contrato in proximos
            ],
            "url": url("apolices:contratos", renovacao="on"),
        }
