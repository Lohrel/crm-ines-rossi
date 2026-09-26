from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from boletos.forms import (
    BoletoForm,
    EdicaoBoletoForm,
    EnvioForm,
    FiltroBoletosForm,
    GerarMensalidadesForm,
    este_mes,
)
from boletos.historico import LinhaDoTempoDoBoleto
from boletos.models import DIAS_DE_ANTECEDENCIA, Boleto
from clientes.views import FormularioMixin


def _quantos(numero: int, singular: str, plural: str) -> str:
    return f"{numero} {singular if numero == 1 else plural}"


class BoletoListView(ListView):
    """Por padrão, o que falta enviar, de qualquer mês, pelo vencimento."""

    template_name = "boletos/lista.html"
    paginate_by = 100

    def get_queryset(self):
        self.filtro = FiltroBoletosForm(self.request.GET or None)
        self.dados = self.filtro.cleaned_data if self.filtro.is_valid() else {}
        boletos = Boleto.objects.select_related(
            "contrato__cliente",
            "contrato__ramo",
            "contrato__seguradora",
            "enviado_para",
            "enviado_por",
        )
        situacao = self.dados.get("situacao", "")
        if situacao == "":
            boletos = boletos.a_enviar()
        else:
            if situacao != "todos":
                boletos = boletos.na_situacao(situacao)
            boletos = boletos.order_by("-vencimento", "contrato__cliente__nome")
        if mes := self.dados.get("mes"):
            boletos = boletos.filter(referencia=mes)
        if tipo := self.dados.get("tipo"):
            boletos = boletos.filter(tipo=tipo)
        if self.dados.get("fora"):
            boletos = boletos.filter(fora_do_vencimento=True)
        if contrato := self.dados.get("contrato"):
            boletos = boletos.filter(contrato=contrato)
        if termo := self.dados.get("q", "").strip():
            boletos = boletos.filter(
                Q(contrato__cliente__nome__icontains=termo) | Q(contrato__numero__icontains=termo)
            )
        return boletos

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = date.today()
        contexto["filtro"] = self.filtro
        contexto["contrato"] = self.dados.get("contrato")
        contexto["resumo"] = {
            "a_enviar": Boleto.objects.a_enviar().count(),
            "vencidos": Boleto.objects.vencidos(hoje).count(),
            "vencendo": Boleto.objects.vencendo(hoje).count(),
        }
        contexto["dias_de_antecedencia"] = DIAS_DE_ANTECEDENCIA
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        contexto["parametros_busca"] = parametros.urlencode()
        return contexto


class BoletoDetailView(DetailView):
    model = Boleto
    template_name = "boletos/detalhe.html"

    def get_queryset(self):
        return Boleto.objects.select_related(
            "contrato__cliente", "contrato__ramo", "contrato__seguradora", "enviado_para"
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempoDoBoleto(self.object).eventos()
        return contexto


class BoletoCreateView(FormularioMixin, CreateView):
    model = Boleto
    form_class = BoletoForm
    titulo = "Novo boleto"
    mensagem_sucesso = "Boleto registrado."

    def get_initial(self):
        contrato = self.request.GET.get("contrato", "")
        return {"contrato": contrato} if contrato.isdigit() else {}

    def form_valid(self, form):
        form.instance.registrado_por = self.request.user
        return super().form_valid(form)

    def get_url_cancelar(self) -> str:
        return reverse("boletos:lista")


class BoletoUpdateView(FormularioMixin, UpdateView):
    model = Boleto
    form_class = EdicaoBoletoForm
    mensagem_sucesso = "Boleto atualizado."

    def form_valid(self, form):
        if "enviado_em" in form.changed_data:
            form.instance.enviado_por = self.request.user if form.instance.enviado_em else None
        return super().form_valid(form)

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class RegistrarEnvioView(FormularioMixin, UpdateView):
    model = Boleto
    form_class = EnvioForm
    mensagem_sucesso = "Envio registrado."

    def get_queryset(self):
        return Boleto.objects.a_enviar()

    def form_valid(self, form):
        form.instance.enviado_por = self.request.user
        return super().form_valid(form)

    def get_titulo(self) -> str:
        return f"Registrar envio: {self.object}"

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class EnviadoHojeView(SingleObjectMixin, View):
    """Atalho da lista: registra que o boleto foi enviado hoje e volta para a lista."""

    model = Boleto
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        boleto = self.get_object()
        try:
            boleto.registrar_envio(request.user)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        else:
            messages.success(request, f"Envio registrado: {boleto}.")
        proximo = request.POST.get("proximo", "")
        seguro = url_has_allowed_host_and_scheme(
            proximo, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        return redirect(proximo if seguro else reverse("boletos:lista"))


class GerarMensalidadesView(FormularioMixin, FormView):
    form_class = GerarMensalidadesForm
    titulo = "Gerar boletos do mês"

    def get_initial(self):
        return {"referencia": este_mes()}

    def form_valid(self, form):
        referencia = form.cleaned_data["referencia"]
        criados, existentes = Boleto.gerar_mensalidades(referencia, self.request.user)
        mes = f"{referencia:%m/%Y}"
        if criados or existentes:
            texto = f"{_quantos(criados, 'boleto criado', 'boletos criados')} para {mes}."
            if existentes:
                texto += f" {_quantos(existentes, 'já existia', 'já existiam')}."
            messages.success(self.request, texto)
        else:
            messages.warning(
                self.request,
                "Nenhum contrato vigente está marcado com “a corretora envia o boleto”.",
            )
        return redirect(f"{reverse('boletos:lista')}?mes={mes}")

    def get_url_cancelar(self) -> str:
        return reverse("boletos:lista")
