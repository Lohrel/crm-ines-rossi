"""Importação da planilha mensal de controle, no formato que o escritório já usa.

Cada linha das abas de inclusão (ex.: UNIMED, SAÚDE, DENTAL) vira um pedido de
inclusão, e cada linha da aba ALTERAÇÕES DE PLANO, um pedido de alteração. A
pessoa é achada pela matrícula (titular) ou pelo nome (dependente); o plano,
pela coluna PLANO (o "Produto/plano" do contrato); o solicitante, pelo primeiro
nome entre os contatos da empresa.

A prévia faz tudo dentro de uma transação desfeita no fim, para mostrar
exatamente o que vai acontecer; ao confirmar, faz de novo, agora gravando.
Importar a mesma planilha outra vez não repete nada: o que já está no sistema
fica como está, e o pedido que estava em aberto e na planilha já aparece como
Processado avança.
"""

import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from apolices.models import Contrato
from beneficiarios.models import Beneficiario
from clientes.models import Cliente, Contato, Unidade
from movimentacoes.models import Etapa, Movimentacao

# Nome de cada coluna da planilha (sem acento, em maiúsculas) e o dado que ela traz.
COLUNAS = {
    "SOLICITANTE": "solicitante",
    "STATUS": "status",
    "ETAPA": "status",
    "CADASTRO": "cadastro",
    "MATRICULA": "cadastro",
    "NOME": "nome",
    "CARTEIRINHA": "carteirinha",
    "DATA DIGITACAO": "digitada_em",
    "DATA DE DIGITACAO": "digitada_em",
    "DATA DE ENVIO": "digitada_em",
    "INICIO": "vigencia",
    "INICIO DE VIGENCIA": "vigencia",
    "VIGENCIA": "vigencia",
    "PLANO": "plano",
    "OBSERVACAO": "observacao",
    "OBS": "observacao",
    "FILIAL": "filial",
}
# Os dados que as colunas trazem.
DADOS = set(COLUNAS.values())
DATAS = {"digitada_em", "vigencia"}
FEITAS = {"PROCESSADO", "PROCESSADA", "CONCLUIDO", "CONCLUIDA"}
PENDENTES = {"PENDENTE", "EM ANALISE"}
# Aba das alterações de plano (ex.: ALTERAÇÕES DE PLANO); as outras são de inclusão.
ABAS_DE_ALTERACAO = ("ALTERA", "MUDANCA", "TROCA")
LIMITE_DE_LINHAS = 2000
# O .xlsx é um .zip: descompactado, uma planilha mensal fica bem abaixo disto.
LIMITE_DESCOMPACTADO = 20 * 1024 * 1024
VALIDADE_DA_PREVIA = timedelta(hours=2)
NAO_LEU = "Não foi possível ler o arquivo. Salve-o como Excel (.xlsx) e envie de novo."

# O que acontece com cada linha.
IMPORTAR = "importar"
ATUALIZAR = "atualizar"
PULAR = "pular"
UNIDADE = "unidade"
PROBLEMA = "problema"


def chave(texto) -> str:
    """Texto para comparar: sem acento, em maiúsculas e com espaços simples."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", texto).upper().split())


def mesma_matricula(uma: str, outra: str) -> bool:
    """04521 e 4521 são a mesma matrícula: o Excel tira o zero da frente dos números."""
    uma, outra = chave(uma), chave(outra)
    if uma.isdigit() and outra.isdigit():
        return uma.lstrip("0") == outra.lstrip("0")
    return uma == outra


@dataclass
class Linha:
    aba: str
    indice_da_aba: int
    numero: int
    alteracao: bool
    tem_status: bool
    valores: dict[str, str]

    @property
    def id(self) -> str:
        return f"{self.indice_da_aba}-{self.numero}"

    def __getitem__(self, nome: str) -> str:
        # Só os dados das colunas; o resto (ex.: numero, no template) continua atributo.
        if nome not in DADOS:
            raise KeyError(nome)
        return self.valores.get(nome, "")

    @property
    def dependente(self) -> bool:
        return chave(self["cadastro"]) in ("DEPENDENTE", "DEP")


class PlanilhaInvalidaError(Exception):
    pass


def _texto(valor, coluna: str) -> str:
    if valor is None:
        return ""
    if coluna in DATAS:
        if isinstance(valor, (int, float)) and 20000 < valor < 80000:
            valor = from_excel(valor)  # data guardada como número
        if isinstance(valor, (datetime, date)):
            return f"{valor:%d/%m/%Y}"
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def _cabecalho(linhas: list[tuple]) -> tuple[int, dict[int, str]] | None:
    """A linha dos títulos (NOME, CADASTRO...) entre as primeiras da aba."""
    for numero, valores in enumerate(linhas, start=1):
        colunas = {i: COLUNAS[chave(v)] for i, v in enumerate(valores) if chave(v) in COLUNAS}
        if "nome" in colunas.values() and len(colunas) >= 3:
            return numero, colunas
    return None


def _conferir_tamanho(arquivo) -> None:
    """Recusa o arquivo que, descompactado, ficaria enorme (proteção contra "zip bomb")."""
    try:
        with zipfile.ZipFile(arquivo) as pacote:
            total = sum(item.file_size for item in pacote.infolist())
    except zipfile.BadZipFile as erro:
        raise PlanilhaInvalidaError(NAO_LEU) from erro
    finally:
        arquivo.seek(0)
    if total > LIMITE_DESCOMPACTADO:
        raise PlanilhaInvalidaError("A planilha é grande demais para importar.")


def ler_planilha(arquivo) -> tuple[list[Linha], list[str]]:
    """As linhas com nome de todas as abas, e avisos sobre as abas que ficaram de fora."""
    _conferir_tamanho(arquivo)
    try:
        livro = load_workbook(arquivo, read_only=True, data_only=True, keep_links=False)
        try:
            linhas, avisos = _ler_abas(livro)
        finally:
            livro.close()
    except PlanilhaInvalidaError:
        raise
    except Exception as erro:  # o openpyxl levanta erros de vários tipos com arquivo estragado
        raise PlanilhaInvalidaError(NAO_LEU) from erro
    if not linhas:
        raise PlanilhaInvalidaError("Nenhuma linha com NOME foi encontrada na planilha.")
    return linhas, avisos


def _ler_abas(livro) -> tuple[list[Linha], list[str]]:
    linhas, avisos = [], []
    for indice, folha in enumerate(livro.worksheets):
        cabecalho = _cabecalho(list(folha.iter_rows(max_row=10, values_only=True)))
        if cabecalho is None:
            avisos.append(f'Aba "{folha.title}" ficou de fora: não tem a linha com NOME.')
            continue
        numero_do_cabecalho, colunas = cabecalho
        tem_status = "status" in colunas.values()
        alteracao = any(palavra in chave(folha.title) for palavra in ABAS_DE_ALTERACAO)
        dados = folha.iter_rows(min_row=numero_do_cabecalho + 1, values_only=True)
        for numero, valores in enumerate(dados, start=numero_do_cabecalho + 1):
            lidos = {
                nome: _texto(valores[i], nome) for i, nome in colunas.items() if i < len(valores)
            }
            if not lidos.get("nome"):
                continue
            linhas.append(Linha(folha.title, indice, numero, alteracao, tem_status, lidos))
            if len(linhas) > LIMITE_DE_LINHAS:
                raise PlanilhaInvalidaError(f"A planilha passa de {LIMITE_DE_LINHAS} linhas.")
    return linhas, avisos


def empacotar(cliente: Cliente, arquivo: str, linhas: list[Linha], avisos: list[str]) -> str:
    """As linhas lidas, assinadas, para a confirmação não depender de reenviar o arquivo."""
    dados = {
        "cliente": cliente.pk,
        "arquivo": arquivo,
        "linhas": [asdict(linha) for linha in linhas],
        "avisos": avisos,
    }
    return signing.dumps(dados, salt="movimentacoes.importacao", compress=True)


def desempacotar(texto: str) -> dict:
    """Levanta signing.BadSignature se o conteúdo foi alterado ou a prévia expirou."""
    dados = signing.loads(
        texto, salt="movimentacoes.importacao", max_age=VALIDADE_DA_PREVIA.total_seconds()
    )
    dados["linhas"] = [Linha(**linha) for linha in dados["linhas"]]
    return dados


@dataclass
class Resultado:
    linha: Linha
    situacao: str
    mensagem: str
    avisos: list[str] = field(default_factory=list)
    # Titular novo numa empresa com mais de uma unidade: as opções e a escolhida.
    unidades: list[Unidade] = field(default_factory=list)
    escolhida: int | None = None


class NaoImportarError(Exception):
    """A linha já está no sistema (ou não é importada): fica como está."""


class FaltaUnidadeError(Exception):
    """Titular novo sem como saber a unidade: a escolha fica para a prévia."""


class Importacao:
    """Aplica as linhas lidas da planilha no cadastro de um cliente."""

    def __init__(self, cliente: Cliente, linhas: list[Linha], usuario, unidades_escolhidas=None):
        self.cliente = cliente
        self.linhas = linhas
        self.usuario = usuario
        self.unidades = list(cliente.unidades.all()) if cliente.eh_empresa else []
        por_pk = {unidade.pk: unidade for unidade in self.unidades}
        self.unidades_escolhidas = {
            linha: por_pk[pk] for linha, pk in (unidades_escolhidas or {}).items() if pk in por_pk
        }
        self.contratos = list(
            Contrato.objects.filter(cliente=cliente).select_related("ramo", "seguradora")
        )
        self.contatos = (
            list(Contato.objects.filter(cliente=cliente).prefetch_related("unidades"))
            if cliente.eh_empresa
            else []
        )

    def previa(self) -> list[Resultado]:
        """O que aconteceria com cada linha, sem gravar nada."""
        with transaction.atomic():
            resultados = self._processar()
            transaction.set_rollback(True)
        return resultados

    def gravar(self) -> list[Resultado]:
        with transaction.atomic():
            # Duas importações do mesmo cliente ao mesmo tempo (ex.: clique duplo) vão em fila.
            Cliente.objects.select_for_update().get(pk=self.cliente.pk)
            return self._processar()

    def _processar(self) -> list[Resultado]:
        self._carregar_pessoas()
        # Unidade de cada titular novo, escolhida na primeira linha em que ele aparece.
        self.unidades_novas: dict[str, tuple[Linha, Unidade | None]] = {}
        # Titulares antes dos dependentes, e inclusões antes das alterações.
        ordem = sorted(self.linhas, key=lambda linha: (linha.alteracao, linha.dependente))
        resultados = {linha.id: self._processar_linha(linha) for linha in ordem}
        return [resultados[linha.id] for linha in self.linhas]

    def _carregar_pessoas(self) -> None:
        self.pessoas = list(
            Beneficiario.objects.filter(cliente=self.cliente).select_related("titular")
        )

    def _processar_linha(self, linha: Linha) -> Resultado:
        self.avisos, self.opcoes, self.escolhida = [], [], None
        try:
            with transaction.atomic():
                situacao, mensagem = self._importar(linha)
        except (NaoImportarError, FaltaUnidadeError, ValidationError, DatabaseError) as motivo:
            # A linha foi desfeita no banco: as pessoas em memória voltam a ser as do banco.
            self._carregar_pessoas()
            situacao, mensagem = self._sem_importar(motivo)
        return Resultado(linha, situacao, mensagem, self.avisos, self.opcoes, self.escolhida)

    @staticmethod
    def _sem_importar(motivo: Exception) -> tuple[str, str]:
        if isinstance(motivo, NaoImportarError):
            return PULAR, str(motivo)
        if isinstance(motivo, FaltaUnidadeError):
            return UNIDADE, str(motivo)
        if isinstance(motivo, ValidationError):
            return PROBLEMA, " ".join(motivo.messages)
        return PROBLEMA, "Não foi possível gravar esta linha. Confira a pessoa e o plano."

    # ------------------------------------------------------------------
    # Uma linha
    # ------------------------------------------------------------------

    def _importar(self, linha: Linha) -> tuple[str, str]:
        etapa = self._etapa(linha)
        digitada_em = self._data(linha, "digitada_em", "DATA DIGITAÇÃO")
        if digitada_em is None:
            raise ValidationError("Falta a DATA DIGITAÇÃO.")
        vigencia = self._data(linha, "vigencia", "INICIO")
        contrato = self._plano(linha)
        solicitante = self._solicitante(linha)
        pessoa = self._pessoa(linha, solicitante)
        carteirinha, observacao = self._carteirinha_e_observacao(linha)
        pedido = Movimentacao(
            tipo=Movimentacao.Tipo.ALTERACAO if linha.alteracao else Movimentacao.Tipo.INCLUSAO,
            cliente=self.cliente,
            beneficiario=pessoa,
            contrato=contrato,
            solicitante=solicitante,
            recebida_em=digitada_em,
            enviada_em=digitada_em,
            vigencia=vigencia or contrato.vigencia_sugerida(digitada_em),
            carteirinha="" if linha.alteracao else carteirinha,
            observacao=observacao,
            registrada_por=self.usuario,
        )
        registrado = self._ja_registrado(pedido)
        if registrado:
            return self._atualizar(registrado, etapa, pedido.carteirinha)
        if not contrato.vigente:
            situacao = contrato.get_situacao_display().lower()
            raise ValidationError(f"O contrato do plano {contrato.nome_do_plano} está {situacao}.")
        if linha.alteracao:
            pedido.contrato_anterior = self._plano_anterior(linha, pessoa, contrato)
        else:
            self._avisar_se_ja_tem_plano_do_ramo(pessoa, contrato)
        pedido.full_clean()
        pedido.save()
        plano = contrato.nome_do_plano
        if pedido.eh_alteracao:
            descricao = f"Alteração de {pedido.contrato_anterior.nome_do_plano} para {plano}"
        else:
            descricao = f"Inclusão em {plano}"
        if etapa == Etapa.EM_ANALISE:
            return IMPORTAR, f"{descricao}, em análise."
        return IMPORTAR, f"{descricao}, {self._concluir(pedido)}."

    def _atualizar(self, pedido: Movimentacao, etapa: str, carteirinha: str) -> tuple[str, str]:
        """Pedido em aberto no sistema que a planilha já dá como processado: avança."""
        antes = f"Já registrada, {pedido.get_etapa_display().lower()}"
        pedido.carteirinha = carteirinha or pedido.carteirinha
        sem_carteirinha = pedido.eh_inclusao and not pedido.carteirinha
        if etapa == Etapa.EM_ANALISE or (pedido.etapa == Etapa.APROVADA and sem_carteirinha):
            raise NaoImportarError(f"{antes}.")
        pedido.full_clean()
        return ATUALIZAR, f"{antes}; agora {self._concluir(pedido)}."

    @staticmethod
    def _concluir(pedido: Movimentacao) -> str:
        """Aprova (a pessoa entra no plano na vigência) e, com a carteirinha, conclui."""
        if pedido.etapa == Etapa.EM_ANALISE:
            pedido.mudar_etapa(Etapa.APROVADA)
        if pedido.eh_inclusao and not pedido.carteirinha:
            return "aprovada: falta a carteirinha para concluir"
        pedido.mudar_etapa(Etapa.CONCLUIDA)
        # A planilha não diz quando a carteirinha foi enviada.
        Movimentacao.objects.filter(pk=pedido.pk).update(carteirinha_enviada_em=None)
        return f"concluída: no plano desde {pedido.vigencia:%d/%m/%Y}"

    def _etapa(self, linha: Linha) -> str:
        status = chave(linha["status"])
        if status in FEITAS:
            return Etapa.CONCLUIDA
        if status in PENDENTES or (linha.tem_status and not status):
            return Etapa.EM_ANALISE
        if not linha.tem_status:
            # Aba sem STATUS (ex.: DENTAL, de inclusão imediata): com carteirinha, está feita.
            return Etapa.CONCLUIDA if self._carteirinha_e_observacao(linha)[0] else Etapa.EM_ANALISE
        raise NaoImportarError(
            f"STATUS {linha['status']}: só Pendente e Processado são importados."
        )

    @staticmethod
    def _data(linha: Linha, nome: str, coluna: str) -> date | None:
        texto = linha[nome]
        if not texto:
            return None
        for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(texto, formato).date()
            except ValueError:
                continue
        raise ValidationError(f"{coluna} inválida: {texto}.")

    @staticmethod
    def _carteirinha_e_observacao(linha: Linha) -> tuple[str, str]:
        carteirinha, observacao = linha["carteirinha"], linha["observacao"]
        if re.search(r"[A-Za-z]", carteirinha):
            # Ex.: "INCLUIR NO DENTAL" é um lembrete, não o número da carteirinha.
            lembrete = f"Lembrete da planilha: {carteirinha}."
            return "", f"{observacao} {lembrete}".strip()
        return carteirinha, observacao

    def _plano(self, linha: Linha) -> Contrato:
        """Pelo PLANO (produto ou número do contrato); sem ele, o único plano da aba."""
        nome = chave(linha["plano"])
        if nome:
            achados = [c for c in self.contratos if nome in (chave(c.produto), chave(c.numero))]
            if len(achados) > 1:
                achados = self._da_aba(linha, achados) or achados
            if len(achados) > 1:
                achados = [c for c in achados if c.vigente] or achados
            if len(achados) == 1:
                return achados[0]
            if achados:
                raise ValidationError(f"Há mais de um plano {linha['plano']} neste cliente.")
            raise ValidationError(
                f"Plano {linha['plano']} não encontrado: confira o Produto/plano dos contratos."
            )
        da_aba = self._da_aba(linha, self.contratos)
        if len(da_aba) > 1:
            da_aba = [c for c in da_aba if c.vigente] or da_aba
        if len(da_aba) == 1:
            return da_aba[0]
        raise ValidationError(f'Informe o PLANO: a aba "{linha.aba}" tem mais de um plano.')

    @staticmethod
    def _da_aba(linha: Linha, contratos: list[Contrato]) -> list[Contrato]:
        """Os contratos cujo ramo ou seguradora aparece no nome da aba (ex.: DENTAL, UNIMED)."""
        if linha.alteracao:
            return contratos
        palavras = set(chave(linha.aba).split())
        return [
            c
            for c in contratos
            if chave(c.ramo) in palavras or set(chave(c.seguradora).split()[:1]) & palavras
        ]

    def _solicitante(self, linha: Linha) -> Contato | None:
        nome = chave(linha["solicitante"])
        if not nome or not self.cliente.eh_empresa:
            return None
        achados = [c for c in self.contatos if chave(c.nome) == nome]
        if not achados:
            primeiro = nome.split()[0]
            achados = [c for c in self.contatos if chave(c.nome).split()[:1] == [primeiro]]
        if len(achados) == 1:
            return achados[0]
        situacao = "mais de um contato" if achados else "nenhum contato"
        self.avisos.append(
            f"Solicitante {linha['solicitante']}: {situacao} com este nome; fica em branco."
        )
        return None

    def _pessoa(self, linha: Linha, solicitante: Contato | None) -> Beneficiario:
        nome = chave(linha["nome"])
        if linha.dependente:
            achados = [p for p in self.pessoas if not p.eh_titular and chave(p.nome) == nome]
            if len(achados) == 1:
                return achados[0]
            if achados:
                raise ValidationError("Há mais de um dependente com este nome.")
            raise ValidationError(
                "Dependente sem cadastro: cadastre pela página do titular e importe de novo."
            )
        titulares = [p for p in self.pessoas if p.eh_titular]
        matricula = linha["cadastro"]
        if matricula:
            achados = [p for p in titulares if mesma_matricula(p.matricula, matricula)]
            if len(achados) > 1:
                raise ValidationError(f"Há mais de um titular com a matrícula {matricula}.")
            if achados:
                pessoa = achados[0]
                if chave(pessoa.nome) != nome:
                    self.avisos.append(f"No sistema, a matrícula {matricula} é de {pessoa.nome}.")
                return pessoa
        achados = [p for p in titulares if chave(p.nome) == nome]
        if len(achados) > 1:
            raise ValidationError("Há mais de um titular com este nome: informe a matrícula.")
        if achados:
            return self._completar_matricula(achados[0], matricula)
        if linha.alteracao:
            raise ValidationError("Titular sem cadastro: na alteração, a pessoa já tem um plano.")
        return self._novo_titular(linha, matricula, solicitante)

    def _completar_matricula(self, pessoa: Beneficiario, matricula: str) -> Beneficiario:
        if matricula and pessoa.matricula and not mesma_matricula(pessoa.matricula, matricula):
            raise ValidationError(f"No sistema, {pessoa.nome} tem a matrícula {pessoa.matricula}.")
        if matricula and not pessoa.matricula:
            pessoa.matricula = matricula
            pessoa.save(update_fields=["matricula", "atualizado_em"])
            self.avisos.append("Matrícula preenchida no cadastro da pessoa.")
        return pessoa

    def _novo_titular(self, linha: Linha, matricula: str, solicitante) -> Beneficiario:
        unidade = self._unidade_do_titular_novo(linha, solicitante)
        pessoa = Beneficiario(
            cliente=self.cliente, nome=linha["nome"], matricula=matricula, unidade=unidade
        )
        pessoa.full_clean()
        pessoa.save()
        self.pessoas.append(pessoa)
        onde = f", na unidade {unidade}" if unidade else ""
        self.avisos.append(f"Titular novo: cadastrado só com nome e matrícula{onde}.")
        return pessoa

    def _unidade_do_titular_novo(self, linha: Linha, solicitante) -> Unidade | None:
        """Com mais de uma unidade, a prévia deixa escolher, já marcando a mais provável."""
        if len(self.unidades) <= 1:
            return self.unidades[0] if self.unidades else None
        # A mesma pessoa pode vir em mais de uma aba (ex.: saúde e dental): escolhe-se uma vez.
        quem = chave(linha["cadastro"]).lstrip("0") or chave(linha["nome"])
        if quem in self.unidades_novas:
            primeira, unidade = self.unidades_novas[quem]
            if unidade is None:
                raise FaltaUnidadeError(
                    f"Titular novo: escolha a unidade na linha {primeira.numero} "
                    f"da aba {primeira.aba}."
                )
            return unidade
        self.opcoes = self.unidades
        unidade = self.unidades_escolhidas.get(linha.id) or self._unidade_provavel(
            linha, solicitante
        )
        self.unidades_novas[quem] = (linha, unidade)
        if unidade is None:
            raise FaltaUnidadeError("Titular novo: escolha a unidade em que trabalha.")
        self.escolhida = unidade.pk
        return unidade

    def _unidade_provavel(self, linha: Linha, solicitante: Contato | None) -> Unidade | None:
        """A da coluna FILIAL ou, se o solicitante atende uma unidade só, a dele."""
        filial = chave(linha["filial"])
        if filial:
            pela_filial = [
                u
                for u in self.unidades
                if filial in (chave(u), chave(u.razao_social), chave(u.nome_fantasia))
            ]
            if len(pela_filial) == 1:
                return pela_filial[0]
        do_solicitante = list(solicitante.unidades.all()) if solicitante else []
        return do_solicitante[0] if len(do_solicitante) == 1 else None

    def _avisar_se_ja_tem_plano_do_ramo(self, pessoa: Beneficiario, contrato: Contrato) -> None:
        """Inclusão de quem já tem plano do ramo pode ser troca de plano lançada na aba errada."""
        outros = pessoa.vinculos.filter(
            data_exclusao__isnull=True, contrato__ramo=contrato.ramo_id
        ).exclude(contrato=contrato)
        planos = ", ".join(v.contrato.nome_do_plano for v in outros.select_related("contrato"))
        if planos:
            self.avisos.append(
                f"A pessoa já está no plano {planos}, de {contrato.ramo}. Se é troca de plano, "
                "lance na aba ALTERAÇÕES DE PLANO."
            )

    def _plano_anterior(self, linha: Linha, pessoa: Beneficiario, novo: Contrato) -> Contrato:
        """O plano atual da pessoa no mesmo ramo (ex.: PLENO, em "Pleno para Flex")."""
        atuais = [
            vinculo.contrato
            for vinculo in pessoa.vinculos.filter(data_exclusao__isnull=True).select_related(
                "contrato__ramo"
            )
            if vinculo.contrato.ramo_id == novo.ramo_id and vinculo.contrato_id != novo.pk
        ]
        if len(atuais) > 1:
            de = chave(linha["observacao"]).split(" PARA ")[0]
            atuais = [c for c in atuais if chave(c.nome_do_plano) == de] or atuais
        if len(atuais) == 1:
            return atuais[0]
        if atuais:
            raise ValidationError(f"A pessoa está em mais de um plano de {novo.ramo}.")
        raise ValidationError(
            f"A pessoa não está em nenhum outro plano de {novo.ramo}: lance o plano atual antes."
        )

    @staticmethod
    def _ja_registrado(pedido: Movimentacao) -> Movimentacao | None:
        """O pedido em aberto desta linha, se já está no sistema; pula o que já foi feito."""
        pessoa, plano = pedido.beneficiario, pedido.contrato
        entrando = pessoa.movimentacoes.filter(
            contrato=plano, tipo__in=[Movimentacao.Tipo.INCLUSAO, Movimentacao.Tipo.ALTERACAO]
        )
        em_aberto = entrando.em_aberto().first()
        if em_aberto and em_aberto.tipo == pedido.tipo:
            return em_aberto
        if em_aberto:
            raise NaoImportarError(f"Já há um pedido em aberto para o plano {plano.nome_do_plano}.")
        if pessoa.vinculos.filter(contrato=plano, data_exclusao__isnull=True).exists():
            raise NaoImportarError(f"Já está no plano {plano.nome_do_plano}.")
        if entrando.filter(enviada_em=pedido.enviada_em).exists():
            raise NaoImportarError("Já registrada no sistema.")
        return None
