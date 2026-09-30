from datetime import date, timedelta

from django.core.paginator import Paginator
from django.utils.text import slugify
from django.views.generic import TemplateView

from apolices.models import Contrato
from boletos.models import somar_meses
from clientes.models import Unidade
from movimentacoes.forms import rotulo_do_plano
from relatorios import consultas, excel
from relatorios.excel import Coluna
from relatorios.forms import FiltroApolicesForm, FiltroMovimentacoesForm, FiltroVidasForm


class IndiceView(TemplateView):
    template_name = "relatorios/indice.html"


class RelatorioView(TemplateView):
    """Filtro, resultado na tela (em páginas) e o mesmo resultado inteiro em Excel.

    O botão "Baixar em Excel" manda os mesmos filtros com `formato=excel`.
    """

    form_class = None
    titulo = ""
    colunas: list[Coluna] = []
    por_pagina = 200

    def padrao(self) -> dict:
        """Filtro usado quando a página abre sem nenhum."""
        return {}

    def get(self, request, *args, **kwargs):
        self.filtro = self.form_class(request.GET or self.padrao())
        self.dados = self.filtro.cleaned_data if self.filtro.is_valid() else None
        if self.dados is not None and request.GET.get("formato") == "excel":
            conteudo = excel.gerar(
                f"{self.get_titulo()} · {self.descricao_do_filtro()}",
                self.titulo,
                self.colunas,
                (self.linha(registro) for registro in self.consulta().iterator(chunk_size=500)),
            )
            nome = f"{slugify(self.get_titulo())}-{date.today():%Y-%m-%d}.xlsx"
            return excel.baixar(conteudo, nome)
        return super().get(request, *args, **kwargs)

    def get_titulo(self) -> str:
        return self.titulo

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(filtro=self.filtro, titulo=self.get_titulo())
        if self.dados is not None:
            registros = self.consulta()
            pagina = Paginator(registros, self.por_pagina).get_page(self.request.GET.get("page"))
            parametros = self.request.GET.copy()
            parametros.pop("page", None)
            contexto.update(
                resumo=self.resumo(registros),
                page_obj=pagina,
                registros=pagina.object_list,
                descricao_do_filtro=self.descricao_do_filtro(),
                parametros_busca=parametros.urlencode(),
            )
        return contexto

    def consulta(self):
        raise NotImplementedError

    def resumo(self, registros) -> dict:
        raise NotImplementedError

    def linha(self, registro) -> list:
        raise NotImplementedError

    def descricao_do_filtro(self) -> str:
        raise NotImplementedError


class VidasView(RelatorioView):
    """Vidas ativas numa data: cada plano em vigor de cada pessoa, com os totais."""

    template_name = "relatorios/vidas.html"
    form_class = FiltroVidasForm
    titulo = "Vidas ativas"
    colunas = [
        Coluna("Cliente", 30),
        Coluna("Filial", 28),
        Coluna("Nome", 34),
        Coluna("Titular ou dependente", 22),
        Coluna("CPF", 16),
        Coluna("Nascimento", 12, "data"),
        Coluna("Matrícula", 12),
        Coluna("Ramo", 12),
        Coluna("Seguradora", 24),
        Coluna("Contrato", 16),
        Coluna("Produto/plano", 20),
        Coluna("Inclusão", 12, "data"),
        Coluna("Carteirinha", 22),
    ]

    def padrao(self) -> dict:
        return {"data": date.today().strftime("%d/%m/%Y")}

    def consulta(self):
        return consultas.vidas_ativas(self.dados)

    def resumo(self, registros) -> dict:
        return consultas.resumo_das_vidas(registros)

    def descricao_do_filtro(self) -> str:
        partes = [f"em {self.dados.get('data') or date.today():%d/%m/%Y}"]
        if cliente := self.dados.get("cliente"):
            partes.append(str(cliente))
        if unidade := self.dados.get("unidade"):
            partes.append(str(Unidade.objects.get(pk=unidade)))
        if contrato := self.dados.get("contrato"):
            planos = Contrato.objects.select_related("ramo", "seguradora")
            partes.append(rotulo_do_plano(planos.get(pk=contrato)))
        return " · ".join(partes)

    def linha(self, vinculo) -> list:
        pessoa = vinculo.beneficiario
        contrato = vinculo.contrato
        return [
            str(pessoa.cliente),
            str(pessoa.unidade_efetiva or ""),
            pessoa.nome,
            "Titular" if pessoa.eh_titular else pessoa.get_parentesco_display(),
            pessoa.cpf_formatado,
            pessoa.data_nascimento,
            pessoa.matricula_efetiva,
            str(contrato.ramo),
            str(contrato.seguradora),
            contrato.numero,
            contrato.produto,
            vinculo.data_inclusao,
            vinculo.carteirinha,
        ]


class MovimentacoesView(RelatorioView):
    """Inclusões (ou exclusões e alterações de plano) de um período, com a etapa de cada uma."""

    template_name = "relatorios/movimentacoes.html"
    form_class = FiltroMovimentacoesForm
    titulo = "Inclusões por período"
    colunas = [
        Coluna("Nome", 34),
        Coluna("Titular ou dependente", 22),
        Coluna("Cliente", 30),
        Coluna("Filial", 28),
        Coluna("Tipo", 18),
        Coluna("Ramo", 12),
        Coluna("Seguradora", 24),
        Coluna("Plano", 30),
        Coluna("Recebida em", 12, "data"),
        Coluna("Enviada em", 12, "data"),
        Coluna("Vigência", 12, "data"),
        Coluna("Etapa", 12),
        Coluna("Motivo da rejeição", 26),
        Coluna("Carteirinha", 22),
        Coluna("Observação", 40),
    ]

    def padrao(self) -> dict:
        inicio = date.today().replace(day=1)
        fim = somar_meses(inicio, 1) - timedelta(days=1)
        return {"de": f"{inicio:%d/%m/%Y}", "ate": f"{fim:%d/%m/%Y}"}

    def get_titulo(self) -> str:
        if self.dados is None:
            return self.titulo
        tipo = dict(FiltroMovimentacoesForm.TIPOS)[self.dados["tipo"]]
        return (
            f"{tipo} por período" if self.dados["tipo"] != "todos" else "Movimentações por período"
        )

    def consulta(self):
        return consultas.movimentacoes_do_periodo(self.dados)

    def resumo(self, registros) -> dict:
        return consultas.resumo_das_movimentacoes(registros)

    def descricao_do_filtro(self) -> str:
        pela = "pelo envio à operadora" if self.dados["contar_por"] == "envio" else "pela vigência"
        partes = [f"{self.dados['de']:%d/%m/%Y} a {self.dados['ate']:%d/%m/%Y}, {pela}"]
        if situacao := self.dados.get("situacao"):
            partes.append(dict(FiltroMovimentacoesForm.SITUACOES)[situacao].lower())
        if cliente := self.dados.get("cliente"):
            partes.append(str(cliente))
        if contrato := self.dados.get("contrato"):
            planos = Contrato.objects.select_related("ramo", "seguradora")
            partes.append(rotulo_do_plano(planos.get(pk=contrato)))
        return " · ".join(partes)

    def linha(self, mov) -> list:
        pessoa = mov.beneficiario
        contrato = mov.contrato
        plano = contrato.nome_do_plano
        if mov.eh_alteracao:
            plano = f"{mov.contrato_anterior.nome_do_plano} para {contrato.nome_do_plano}"
        return [
            pessoa.nome,
            "Titular" if pessoa.eh_titular else pessoa.get_parentesco_display(),
            str(mov.cliente),
            str(pessoa.unidade_efetiva or ""),
            mov.get_tipo_display(),
            str(contrato.ramo),
            str(contrato.seguradora),
            plano,
            mov.recebida_em,
            mov.enviada_em,
            mov.vigencia,
            mov.get_etapa_display(),
            mov.get_motivo_rejeicao_display(),
            mov.carteirinha,
            mov.observacao,
        ]


class ApolicesView(RelatorioView):
    """Contratos com os dados do cliente, pelo período de renovação."""

    template_name = "relatorios/apolices.html"
    form_class = FiltroApolicesForm
    titulo = "Apólices"
    colunas = [
        Coluna("Cliente", 30),
        Coluna("CPF/CNPJ", 20),
        Coluna("Contato", 24),
        Coluna("Telefone", 16),
        Coluna("E-mail", 28),
        Coluna("Cidade", 20),
        Coluna("Seguradora", 24),
        Coluna("Contrato", 16),
        Coluna("Ramo", 12),
        Coluna("Produto/plano", 20),
        Coluna("Situação", 14),
        Coluna("Início da vigência", 14, "data"),
        Coluna("Renovação", 12, "data"),
        Coluna("Vence dia", 10),
        Coluna("Valor mensal", 14, "dinheiro"),
        Coluna("Vidas", 8),
    ]

    def consulta(self):
        return consultas.apolices(self.dados)

    def resumo(self, registros) -> dict:
        return consultas.resumo_das_apolices(registros)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        if "registros" in contexto:
            contexto["registros"] = [
                (contrato, consultas.dados_do_cliente(contrato.cliente))
                for contrato in contexto["registros"]
            ]
        return contexto

    def descricao_do_filtro(self) -> str:
        situacao = self.dados.get("situacao", "")
        partes = [
            "vigentes"
            if situacao == ""
            else dict(self.filtro.fields["situacao"].choices)[situacao].lower()
        ]
        de, ate = self.dados.get("renovacao_de"), self.dados.get("renovacao_ate")
        if de and ate:
            partes.append(f"renovação de {de:%d/%m/%Y} a {ate:%d/%m/%Y}")
        elif de:
            partes.append(f"renovação a partir de {de:%d/%m/%Y}")
        elif ate:
            partes.append(f"renovação até {ate:%d/%m/%Y}")
        for campo in ("seguradora", "ramo"):
            if self.dados.get(campo):
                partes.append(str(self.dados[campo]))
        return " · ".join(partes)

    def linha(self, contrato) -> list:
        cliente = consultas.dados_do_cliente(contrato.cliente)
        return [
            str(contrato.cliente),
            cliente["documento"],
            cliente["contato"],
            cliente["telefone"],
            cliente["email"],
            cliente["cidade"],
            str(contrato.seguradora),
            contrato.numero,
            str(contrato.ramo),
            contrato.produto,
            contrato.get_situacao_display(),
            contrato.inicio_vigencia,
            contrato.data_renovacao,
            contrato.dia_vencimento,
            contrato.valor_mensal,
            contrato.vidas,
        ]
