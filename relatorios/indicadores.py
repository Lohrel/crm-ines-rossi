"""Indicadores: como o trabalho do escritório anda, mês a mês, com o que o sistema já registra.

Cada mês junta quatro grupos: as movimentações recebidas no mês, as pendências com prazo no
mês, os boletos com vencimento no mês e o que foi cadastrado no mês. Os números são da equipe
inteira, sem separar por funcionário, e não mostram nenhum dado pessoal.

As contas são feitas aqui, depois de um número fixo de consultas (só datas e etapas).
"""

from calendar import monthrange
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta

from django.utils import timezone

from apolices.models import Contrato
from beneficiarios.models import Beneficiario, Vinculo
from boletos.models import Boleto, meses_entre, somar_meses
from clientes.models import Cliente
from movimentacoes.models import Etapa, Movimentacao
from pendencias.models import Pendencia

# Mais que isto não cabe bem na tela; a planilha de um período maior sai em duas vezes.
MAXIMO_DE_MESES = 36


def prazo_de_fechamento(recebida_em: date, dia_fechamento: int) -> date:
    """O próximo fechamento do contrato, contado do dia em que o pedido chegou.

    Pedido que chega depois do fechamento do mês tem até o fechamento do mês seguinte.
    """
    mes = recebida_em.replace(day=1)
    if recebida_em.day > dia_fechamento:
        mes = somar_meses(mes, 1)
    return mes.replace(day=min(dia_fechamento, monthrange(mes.year, mes.month)[1]))


def porcentagem(parte: int, total: int) -> int | None:
    return round(100 * parte / total) if total else None


def media(soma: int, quantos: int) -> float | None:
    return round(soma / quantos, 1) if quantos else None


@dataclass
class Numeros:
    """Os números de um mês (ou a soma do período)."""

    # Movimentações recebidas no mês (as canceladas ficam de fora).
    movimentacoes: int = 0
    enviadas: int = 0
    dias_ate_o_envio: int = 0
    com_fechamento: int = 0
    ate_o_fechamento: int = 0
    decididas: int = 0
    rejeitadas: int = 0
    com_carteirinha: int = 0
    dias_ate_a_carteirinha: int = 0
    # Pendências com prazo no mês.
    pendencias: int = 0
    pendencias_no_prazo: int = 0
    pendencias_com_atraso: int = 0
    pendencias_vencidas: int = 0
    # Boletos com vencimento no mês (os cancelados ficam de fora).
    boletos: int = 0
    boletos_ate_o_vencimento: int = 0
    boletos_depois: int = 0
    boletos_vencidos: int = 0
    # Cadastrados no mês.
    clientes_novos: int = 0
    pessoas_novas: int = 0
    contratos_novos: int = 0

    def somar(self, outro: "Numeros") -> None:
        for campo in fields(self):
            setattr(self, campo.name, getattr(self, campo.name) + getattr(outro, campo.name))

    @property
    def media_ate_o_envio(self) -> float | None:
        return media(self.dias_ate_o_envio, self.enviadas)

    @property
    def pct_ate_o_fechamento(self) -> int | None:
        return porcentagem(self.ate_o_fechamento, self.com_fechamento)

    @property
    def pct_rejeitadas(self) -> int | None:
        return porcentagem(self.rejeitadas, self.decididas)

    @property
    def media_ate_a_carteirinha(self) -> float | None:
        return media(self.dias_ate_a_carteirinha, self.com_carteirinha)

    @property
    def pendencias_em_dia(self) -> int:
        """Em aberto e ainda dentro do prazo: não entram na porcentagem."""
        return (
            self.pendencias
            - self.pendencias_no_prazo
            - self.pendencias_com_atraso
            - self.pendencias_vencidas
        )

    @property
    def pct_pendencias_no_prazo(self) -> int | None:
        return porcentagem(self.pendencias_no_prazo, self.pendencias - self.pendencias_em_dia)

    @property
    def boletos_a_enviar(self) -> int:
        """Ainda não enviados e não vencidos: não entram na porcentagem."""
        return (
            self.boletos
            - self.boletos_ate_o_vencimento
            - self.boletos_depois
            - self.boletos_vencidos
        )

    @property
    def pct_boletos_ate_o_vencimento(self) -> int | None:
        return porcentagem(self.boletos_ate_o_vencimento, self.boletos - self.boletos_a_enviar)


@dataclass
class Mes:
    mes: date
    numeros: Numeros
    # Planos em vigor no último dia do mês (no mês atual, hoje).
    vidas: int = 0


@dataclass
class Indicadores:
    meses: list[Mes]
    total: Numeros
    # Motivo da rejeição e quantas vezes apareceu no período, do mais comum para o menos.
    motivos: list[tuple[str, int]]

    @property
    def vazio(self) -> bool:
        return not any(
            getattr(self.total, campo)
            for campo in ("movimentacoes", "pendencias", "boletos", "pessoas_novas")
        )


def calcular(de: date, ate: date, hoje: date | None = None) -> Indicadores:
    """Os indicadores de cada mês, de `de` até `ate` (o dia 1º de cada um)."""
    hoje = hoje or date.today()
    inicio, fim = de, somar_meses(ate, 1)
    por_mes = {mes: Numeros() for mes in meses_entre(de, ate)}
    motivos: dict[str, int] = {}

    movimentacoes = (
        Movimentacao.objects.filter(recebida_em__gte=inicio, recebida_em__lt=fim)
        .exclude(etapa=Etapa.CANCELADA)
        .values_list(
            "recebida_em",
            "enviada_em",
            "carteirinha_enviada_em",
            "etapa",
            "motivo_rejeicao",
            "contrato__dia_fechamento",
        )
    )
    nomes_dos_motivos = dict(Movimentacao.Motivo.choices)
    for recebida, enviada, carteirinha, etapa, motivo, fechamento in movimentacoes:
        numeros = por_mes[recebida.replace(day=1)]
        numeros.movimentacoes += 1
        if enviada:
            numeros.enviadas += 1
            numeros.dias_ate_o_envio += max((enviada - recebida).days, 0)
        if fechamento:
            prazo = prazo_de_fechamento(recebida, fechamento)
            # Sem envio e ainda dentro do prazo: fica de fora até o prazo passar.
            if enviada or prazo < hoje:
                numeros.com_fechamento += 1
                numeros.ate_o_fechamento += bool(enviada and enviada <= prazo)
        if etapa != Etapa.EM_ANALISE:
            numeros.decididas += 1
        if etapa == Etapa.REJEITADA:
            numeros.rejeitadas += 1
            nome = nomes_dos_motivos.get(motivo, "Sem motivo informado")
            motivos[nome] = motivos.get(nome, 0) + 1
        if enviada and carteirinha:
            numeros.com_carteirinha += 1
            numeros.dias_ate_a_carteirinha += max((carteirinha - enviada).days, 0)

    pendencias = Pendencia.objects.filter(prazo__gte=inicio, prazo__lt=fim)
    for prazo, concluida in pendencias.values_list("prazo", "concluida_em"):
        numeros = por_mes[prazo.replace(day=1)]
        numeros.pendencias += 1
        if concluida:
            if concluida <= prazo:
                numeros.pendencias_no_prazo += 1
            else:
                numeros.pendencias_com_atraso += 1
        elif prazo < hoje:
            numeros.pendencias_vencidas += 1

    boletos = Boleto.objects.filter(cancelado=False, vencimento__gte=inicio, vencimento__lt=fim)
    for vencimento, enviado in boletos.values_list("vencimento", "enviado_em"):
        numeros = por_mes[vencimento.replace(day=1)]
        numeros.boletos += 1
        if enviado:
            if enviado <= vencimento:
                numeros.boletos_ate_o_vencimento += 1
            else:
                numeros.boletos_depois += 1
        elif vencimento < hoje:
            numeros.boletos_vencidos += 1

    # `criado_em` tem hora: o mês é o do horário do escritório.
    inicio_com_hora = timezone.make_aware(datetime(inicio.year, inicio.month, 1))
    fim_com_hora = timezone.make_aware(datetime(fim.year, fim.month, 1))
    for modelo, campo in (
        (Cliente, "clientes_novos"),
        (Beneficiario, "pessoas_novas"),
        (Contrato, "contratos_novos"),
    ):
        criados = modelo.objects.filter(criado_em__gte=inicio_com_hora, criado_em__lt=fim_com_hora)
        for (criado_em,) in criados.values_list("criado_em"):
            mes = timezone.localtime(criado_em).date().replace(day=1)
            numeros = por_mes[mes]
            setattr(numeros, campo, getattr(numeros, campo) + 1)

    total = Numeros()
    for numeros in por_mes.values():
        total.somar(numeros)

    meses = [Mes(mes, numeros) for mes, numeros in por_mes.items()]
    vinculos = list(
        Vinculo.objects.filter(data_inclusao__lt=fim).values_list("data_inclusao", "data_exclusao")
    )
    for mes in meses:
        if mes.mes > hoje:
            continue  # Mês que ainda não começou.
        # A mesma regra de `Vinculo.objects.ativos`, no último dia do mês.
        em = min(somar_meses(mes.mes, 1) - timedelta(days=1), hoje)
        mes.vidas = sum(
            1
            for inclusao, exclusao in vinculos
            if inclusao <= em and (exclusao is None or exclusao > em)
        )

    return Indicadores(
        meses=meses,
        total=total,
        motivos=sorted(motivos.items(), key=lambda item: (-item[1], item[0])),
    )
