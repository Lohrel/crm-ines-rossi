"""Movimentações: pedidos de inclusão, exclusão e alteração de plano enviados às operadoras.

O pedido só é registrado depois de enviado à operadora, então já começa em
análise. Quando a operadora aprova, a pessoa entra no plano (ou sai dele) a
partir da data de vigência, e só então passa a contar (ou deixa de contar)
como vida. Na alteração de plano, sai de um plano e entra no outro na mesma data.
"""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from simple_history.models import HistoricalRecords

from apolices.models import Contrato, Plano
from beneficiarios.models import Beneficiario, Vinculo
from clientes.models import Contato, Registro


class Etapa(models.TextChoices):
    EM_ANALISE = "ANA", "Em análise"
    APROVADA = "APR", "Aprovada"
    CONCLUIDA = "CON", "Concluída"
    REJEITADA = "REJ", "Rejeitada"
    CANCELADA = "CAN", "Cancelada"


ETAPAS_EM_ABERTO = [Etapa.EM_ANALISE, Etapa.APROVADA]
EM_ABERTO_NO_PLANO = "Já existe uma movimentação em aberto desta pessoa neste plano."
AVISO_DO_DEPENDENTE = "Se o titular também está entrando neste plano, aprove-o primeiro."

# Para onde cada etapa pode ir.
PROXIMAS_ETAPAS = {
    Etapa.EM_ANALISE: [Etapa.APROVADA, Etapa.REJEITADA, Etapa.CANCELADA],
    Etapa.APROVADA: [Etapa.CONCLUIDA],
    Etapa.CONCLUIDA: [],
    Etapa.REJEITADA: [],
    Etapa.CANCELADA: [],
}


class MovimentacaoQuerySet(models.QuerySet):
    def em_aberto(self):
        return self.filter(etapa__in=ETAPAS_EM_ABERTO)

    def com_vigencia_no_mes(self, ano: int, mes: int):
        return self.filter(vigencia__year=ano, vigencia__month=mes)

    def buscar(self, termo: str):
        termo = (termo or "").strip()
        if not termo:
            return self
        return self.filter(
            Q(beneficiario__nome__icontains=termo)
            | Q(beneficiario__matricula__iexact=termo)
            | Q(beneficiario__titular__matricula__iexact=termo)
            | Q(carteirinha__iexact=termo)
            | Q(cliente__nome__icontains=termo)
        )


class Movimentacao(Registro):
    class Tipo(models.TextChoices):
        INCLUSAO = "INC", "Inclusão"
        EXCLUSAO = "EXC", "Exclusão"
        ALTERACAO = "ALT", "Alteração de plano"

    class Motivo(models.TextChoices):
        RASURA = "RAS", "Rasura ou erro no formulário"
        ENTREVISTA = "ENT", "Prazo da entrevista médica"
        DOCUMENTOS = "DOC", "Documentação incompleta"
        OUTRO = "OUT", "Outro"

    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    # Repete o cliente da pessoa, para filtrar e listar por empresa sem juntar tabelas.
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="movimentacoes"
    )
    beneficiario = models.ForeignKey(
        Beneficiario, on_delete=models.PROTECT, related_name="movimentacoes"
    )
    contrato = models.ForeignKey(
        Contrato, on_delete=models.PROTECT, related_name="movimentacoes", verbose_name="plano"
    )
    contrato_anterior = models.ForeignKey(
        Contrato,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alteracoes_de_saida",
        verbose_name="plano anterior",
        help_text="Só na alteração de plano: o plano de onde a pessoa sai.",
    )
    plano = models.ForeignKey(
        Plano,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimentacoes",
        verbose_name="plano do contrato",
        help_text="Só nos contratos com mais de um plano (ex.: TNPQ ou TNP4).",
    )
    plano_anterior = models.ForeignKey(
        Plano,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="plano anterior do contrato",
        help_text="Só na alteração: o plano de onde a pessoa sai, se o contrato tem planos.",
    )
    solicitante = models.ForeignKey(
        Contato,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes",
        help_text="Quem pediu (ex.: o RH da filial).",
    )
    etapa = models.CharField(max_length=3, choices=Etapa.choices, default=Etapa.EM_ANALISE)
    recebida_em = models.DateField("recebida em", default=date.today)
    enviada_em = models.DateField("enviada à operadora em", null=True, blank=True)
    vigencia = models.DateField(
        "início de vigência (ou data da exclusão)",
        help_text="Se ficar em branco, usa o dia 1º do mês seguinte, conforme o fechamento.",
    )
    carteirinha = models.CharField("número da carteirinha", max_length=60, blank=True)
    carteirinha_enviada_em = models.DateField("carteirinha enviada em", null=True, blank=True)
    motivo_rejeicao = models.CharField(
        "motivo da rejeição", max_length=3, choices=Motivo.choices, blank=True
    )
    observacao = models.TextField("observação", blank=True)
    origem = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refeitas",
        help_text="Movimentação rejeitada que esta refaz.",
    )
    vinculo = models.ForeignKey(
        Vinculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes",
        verbose_name="plano da pessoa",
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    history = HistoricalRecords()
    objects = MovimentacaoQuerySet.as_manager()

    class Meta:
        verbose_name = "movimentação"
        verbose_name_plural = "movimentações"
        ordering = ["vigencia", "beneficiario__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "beneficiario", "contrato"],
                condition=Q(etapa__in=ETAPAS_EM_ABERTO),
                name="movimentacao_uma_em_aberto_por_plano",
                violation_error_message=EM_ABERTO_NO_PLANO,
            ),
            models.CheckConstraint(
                condition=Q(tipo="ALT", contrato_anterior__isnull=False)
                | ~Q(tipo="ALT") & Q(contrato_anterior__isnull=True),
                name="movimentacao_plano_anterior_so_na_alteracao",
                violation_error_message=(
                    "Só a alteração de plano tem plano anterior, e ela precisa dele."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} de {self.beneficiario} em {self.contrato.ramo}"

    def get_absolute_url(self) -> str:
        return reverse("movimentacoes:detalhe", args=[self.pk])

    @property
    def eh_inclusao(self) -> bool:
        return self.tipo == self.Tipo.INCLUSAO

    @property
    def eh_alteracao(self) -> bool:
        return self.tipo == self.Tipo.ALTERACAO

    @property
    def entra_no_plano(self) -> bool:
        """Inclusão e alteração põem a pessoa no plano do pedido."""
        return self.tipo in (self.Tipo.INCLUSAO, self.Tipo.ALTERACAO)

    @property
    def nome_do_plano(self) -> str:
        """O plano do pedido: o do contrato (ex.: TNPQ) ou, sem ele, o nome do contrato."""
        return self.plano.nome if self.plano_id else self.contrato.nome_do_plano

    @property
    def nome_do_plano_anterior(self) -> str:
        if self.plano_anterior_id:
            return self.plano_anterior.nome
        return self.contrato_anterior.nome_do_plano if self.contrato_anterior_id else ""

    @property
    def no_mesmo_contrato(self) -> bool:
        """Alteração entre dois planos do mesmo contrato (ex.: de TNPQ para TNP4)."""
        return self.eh_alteracao and self.contrato_anterior_id == self.contrato_id

    @property
    def plano_de_saida_id(self) -> int | None:
        """Plano de onde a pessoa sai: o da exclusão ou o anterior, na alteração."""
        if self.eh_alteracao:
            return self.contrato_anterior_id
        return self.contrato_id if self.tipo == self.Tipo.EXCLUSAO else None

    @property
    def em_aberto(self) -> bool:
        return self.etapa in ETAPAS_EM_ABERTO

    @property
    def proximas_etapas(self) -> list[str]:
        return PROXIMAS_ETAPAS[self.etapa]

    @property
    def apos_o_fechamento(self) -> bool:
        """Chegou depois do dia de fechamento do mês (vigência vai para o outro mês)."""
        fechamento = self.contrato.dia_fechamento
        return bool(fechamento and self.recebida_em.day > fechamento)

    @property
    def dias_em_aberto(self) -> int | None:
        return (date.today() - self.recebida_em).days if self.em_aberto else None

    def clean(self) -> None:
        super().clean()
        if not (self.beneficiario_id and self.contrato_id):
            return
        pessoa = self.beneficiario
        if self.contrato.cliente_id != pessoa.cliente_id:
            raise ValidationError({"contrato": "O plano deve ser do mesmo cliente da pessoa."})
        if self.plano_id and self.plano.contrato_id != self.contrato_id:
            raise ValidationError({"contrato": "O plano escolhido é de outro contrato."})
        if self.solicitante_id and self.solicitante.cliente_id != pessoa.cliente_id:
            raise ValidationError({"solicitante": "O solicitante deve ser desta empresa."})
        if self._state.adding:
            if self.eh_alteracao:
                self._validar_troca_de_plano()
            self._validar_planos_da_pessoa()

    def _validar_troca_de_plano(self) -> None:
        anterior = self.contrato_anterior
        if anterior is None:
            raise ValidationError({"contrato_anterior": "Informe o plano de onde a pessoa sai."})
        if not self.plano_anterior_id:
            # O plano de onde a pessoa sai é o que ela tem hoje no contrato.
            atual = self.beneficiario.vinculos.filter(contrato=anterior, data_exclusao__isnull=True)
            self.plano_anterior_id = atual.values_list("plano", flat=True).first()
        if anterior.pk == self.contrato_id and self.plano_id == self.plano_anterior_id:
            raise ValidationError({"contrato": "Escolha um plano diferente do atual."})
        if anterior.cliente_id != self.beneficiario.cliente_id:
            raise ValidationError(
                {"contrato_anterior": "O plano deve ser do mesmo cliente da pessoa."}
            )
        if anterior.ramo_id != self.contrato.ramo_id:
            raise ValidationError(
                {"contrato": f"A alteração é entre planos do mesmo ramo ({anterior.ramo})."}
            )

    def _validar_planos_da_pessoa(self) -> None:
        """Quem entra não pode já estar no plano, quem sai precisa estar, e um pedido por vez."""
        pessoa = self.beneficiario
        saida = self.plano_de_saida_id
        campo_da_saida = "contrato_anterior" if self.eh_alteracao else "contrato"
        ativos = pessoa.vinculos.filter(data_exclusao__isnull=True)
        if (
            self.entra_no_plano
            and not self.no_mesmo_contrato
            and ativos.filter(contrato=self.contrato_id).exists()
        ):
            raise ValidationError({"contrato": "Esta pessoa já está neste plano."})
        if saida and not ativos.filter(contrato=saida).exists():
            raise ValidationError({campo_da_saida: "Esta pessoa não está neste plano."})
        # Um pedido em aberto por vez para entrar em cada plano, e outro para sair dele.
        em_aberto = pessoa.movimentacoes.em_aberto()
        entrando = Q(tipo__in=[self.Tipo.INCLUSAO, self.Tipo.ALTERACAO], contrato=self.contrato_id)
        if self.entra_no_plano and em_aberto.filter(entrando).exists():
            raise ValidationError({"contrato": EM_ABERTO_NO_PLANO})
        saindo = Q(tipo=self.Tipo.EXCLUSAO, contrato=saida) | Q(
            tipo=self.Tipo.ALTERACAO, contrato_anterior=saida
        )
        if saida and em_aberto.filter(saindo).exists():
            raise ValidationError({campo_da_saida: EM_ABERTO_NO_PLANO})

    def save(self, *args, **kwargs):
        self.cliente_id = self.beneficiario.cliente_id
        if self.vigencia is None:
            self.vigencia = self.contrato.vigencia_sugerida(self.recebida_em)
        super().save(*args, **kwargs)

    def mudar_etapa(self, nova: str, **dados) -> None:
        """Avança o pedido. Aprovar mexe no plano da pessoa; o resto só registra."""
        if nova not in self.proximas_etapas:
            raise ValidationError(
                f"Não é possível passar de {self.get_etapa_display()} para {Etapa(nova).label}."
            )
        for campo, valor in dados.items():
            setattr(self, campo, valor)
        with transaction.atomic():
            # Duas pessoas mudando a etapa ao mesmo tempo (ex.: aprovando o mesmo pedido) vão
            # em fila, e a segunda vê que o pedido já mudou.
            gravada = type(self).objects.select_for_update().values_list("etapa", flat=True)
            if self.pk and gravada.get(pk=self.pk) != self.etapa:
                raise ValidationError(
                    "Outra pessoa mudou a etapa deste pedido enquanto você editava. "
                    "Abra o pedido de novo para ver como ele está."
                )
            if nova == Etapa.REJEITADA and not self.motivo_rejeicao:
                raise ValidationError("Informe o motivo da rejeição.")
            if nova == Etapa.APROVADA:
                self._aplicar_no_plano()
            if nova == Etapa.CONCLUIDA:
                self._concluir()
            self.etapa = nova
            self.save()

    def _aplicar_no_plano(self) -> None:
        if self.eh_inclusao:
            self.vinculo = self._entrar_no_plano(self.beneficiario, self.vigencia, self.carteirinha)
        elif self.eh_alteracao:
            self.vinculo = self._trocar_de_plano()
        else:
            self.vinculo = self._sair_do_plano()

    def _entrar_no_plano(
        self, pessoa: Beneficiario, inicio: date, carteirinha: str, salario=None
    ) -> Vinculo:
        vinculo = Vinculo(
            beneficiario=pessoa,
            contrato=self.contrato,
            plano=self.plano,
            data_inclusao=inicio,
            carteirinha=carteirinha,
            salario=salario if self.contrato.usa_salario else None,
        )
        try:
            vinculo.full_clean()
        except ValidationError as erro:
            mensagens = erro.messages
            if pessoa != self.beneficiario:
                mensagens = [f"{pessoa}: {mensagem}" for mensagem in mensagens]
            elif not pessoa.eh_titular:
                mensagens.append(AVISO_DO_DEPENDENTE)
            raise ValidationError(mensagens) from erro
        vinculo.save()
        return vinculo

    def _sair_do_plano(self) -> Vinculo:
        do_plano = self.beneficiario.vinculos.filter(contrato=self.contrato)
        vinculo = do_plano.filter(data_exclusao__isnull=True).first()
        if vinculo:
            vinculo.encerrar(self.vigencia)
            return vinculo
        # Já saiu (ex.: junto com o titular): só liga o pedido ao plano encerrado.
        vinculo = do_plano.order_by("-data_exclusao").first()
        if vinculo is None:
            raise ValidationError("Esta pessoa não está neste plano.")
        return vinculo

    def _trocar_de_plano(self) -> Vinculo:
        """Sai do plano anterior e entra no novo na mesma data; os dependentes vão junto.

        A carteirinha continua a mesma; se a operadora emitir outra, corrige-se no plano.
        No seguro de vida, o salário também passa para o novo plano. Na troca dentro do
        mesmo contrato (ex.: de TNPQ para TNP4), só vão junto os dependentes que estavam
        no mesmo plano do titular.
        """
        pessoa = self.beneficiario
        anterior = pessoa.vinculos.filter(
            contrato=self.contrato_anterior, data_exclusao__isnull=True
        ).first()
        ja_mudou = (
            anterior is not None and self.no_mesmo_contrato and anterior.plano_id == self.plano_id
        )
        if anterior is None or ja_mudou:
            # Já mudou (ex.: junto com o titular): só liga o pedido ao novo plano.
            vinculo = pessoa.vinculos.filter(
                contrato=self.contrato, data_exclusao__isnull=True
            ).first()
            if vinculo is None:
                raise ValidationError("Esta pessoa não está mais no plano anterior.")
            return vinculo
        novos = []
        # O titular vem primeiro, para os dependentes já o encontrarem no novo plano.
        for saiu in anterior.encerrar(self.vigencia, so_do_mesmo_plano=self.no_mesmo_contrato):
            quem = saiu.beneficiario
            ja_no_novo = quem.vinculos.filter(contrato=self.contrato, data_exclusao__isnull=True)
            if quem != pessoa and ja_no_novo.exists():
                continue
            inicio = max(self.vigencia, saiu.data_inclusao)
            novos.append(self._entrar_no_plano(quem, inicio, saiu.carteirinha, saiu.salario))
        return novos[0]

    def _concluir(self) -> None:
        if not self.eh_inclusao:
            return
        if not self.carteirinha:
            raise ValidationError("Informe o número da carteirinha para concluir.")
        if not self.carteirinha_enviada_em:
            self.carteirinha_enviada_em = date.today()
        if self.vinculo_id and self.vinculo.carteirinha != self.carteirinha:
            self.vinculo.carteirinha = self.carteirinha
            self.vinculo.save(update_fields=["carteirinha", "atualizado_em"])

    def refazer(self, usuario) -> "Movimentacao":
        """Nova movimentação a partir de uma rejeitada (ex.: rasura, prazo da entrevista)."""
        if self.etapa != Etapa.REJEITADA:
            raise ValidationError("Só é possível refazer uma movimentação rejeitada.")
        hoje = date.today()
        nova = Movimentacao(
            tipo=self.tipo,
            cliente=self.cliente,
            beneficiario=self.beneficiario,
            contrato=self.contrato,
            contrato_anterior=self.contrato_anterior,
            plano=self.plano,
            plano_anterior=self.plano_anterior,
            solicitante=self.solicitante,
            recebida_em=hoje,
            enviada_em=hoje,
            vigencia=self.contrato.vigencia_sugerida(hoje),
            origem=self,
            registrada_por=usuario,
            observacao=f"Refaz a movimentação rejeitada ({self.get_motivo_rejeicao_display()}).",
        )
        nova.full_clean()
        nova.save()
        return nova
