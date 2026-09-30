from calendar import Calendar
from datetime import date

from django.urls import reverse
from django.utils.http import urlencode
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from boletos.models import somar_meses
from calendario.agenda import Agenda
from calendario.forms import EventoForm, MesDoCalendarioForm
from calendario.historico import LinhaDoTempoDoEvento
from calendario.models import Evento
from clientes.views import ExclusaoConfirmadaView, FormularioMixin

# Semana de domingo a sábado, como nos calendários daqui.
SEMANA = Calendar(firstweekday=6)
DIAS_DA_SEMANA = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]


def url_do_mes(mes: date) -> str:
    return f"{reverse('calendario:mes')}?{urlencode({'mes': f'{mes:%m/%Y}'})}"


def lista_do_mes(datas: dict, mes: date) -> list[tuple[date, list]]:
    """Lista do celular: os dias do mês com alguma data, em ordem.

    Um evento de vários dias (ex.: férias) aparece só no primeiro dia do mês em que
    está, com o período no detalhe, para a lista não repetir o mesmo evento dia após dia.
    """
    lista = []
    for dia, itens in sorted(datas.items()):
        if dia.month != mes.month:
            continue
        do_dia = [
            item
            for item in itens
            if item.inicio_do_periodo is None or dia == max(item.inicio_do_periodo, mes)
        ]
        if do_dia:
            lista.append((dia, do_dia))
    return lista


class CalendarioView(TemplateView):
    """O mês inteiro, como o quadro branco: a grade no computador e a lista no celular."""

    template_name = "calendario/mes.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = date.today()
        filtro = MesDoCalendarioForm(self.request.GET or None)
        mes = (filtro.is_valid() and filtro.cleaned_data["mes"]) or hoje.replace(day=1)
        semanas = SEMANA.monthdatescalendar(mes.year, mes.month)
        datas = Agenda(semanas[0][0], semanas[-1][-1], hoje).por_dia()
        contexto.update(
            {
                "mes": mes,
                "hoje": hoje,
                "dias_da_semana": DIAS_DA_SEMANA,
                "semanas": [
                    [
                        {
                            "data": dia,
                            "itens": datas.get(dia, []),
                            "do_mes": dia.month == mes.month,
                            "hoje": dia == hoje,
                        }
                        for dia in semana
                    ]
                    for semana in semanas
                ],
                "dias_com_datas": lista_do_mes(datas, mes),
                "url_anterior": url_do_mes(somar_meses(mes, -1)),
                "url_seguinte": url_do_mes(somar_meses(mes, 1)),
                "eh_este_mes": mes == hoje.replace(day=1),
            }
        )
        return contexto


class EventoDetailView(DetailView):
    model = Evento
    template_name = "calendario/evento.html"

    def get_queryset(self):
        return Evento.objects.select_related("funcionario", "registrado_por")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["historico"] = LinhaDoTempoDoEvento(self.object).eventos()
        contexto["url_do_mes"] = url_do_mes(self.object.inicio.replace(day=1))
        return contexto


class EventoCreateView(FormularioMixin, CreateView):
    model = Evento
    form_class = EventoForm
    titulo = "Novo evento no calendário"
    mensagem_sucesso = "Evento anotado no calendário."

    def get_initial(self):
        # O "+" de cada dia do calendário já traz a data.
        try:
            return {"inicio": date.fromisoformat(self.request.GET.get("data", ""))}
        except ValueError:
            return {"inicio": date.today()}

    def form_valid(self, form):
        form.instance.registrado_por = self.request.user
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return url_do_mes(self.object.inicio.replace(day=1))

    def get_url_cancelar(self) -> str:
        return url_do_mes(self.get_initial()["inicio"].replace(day=1))


class EventoUpdateView(FormularioMixin, UpdateView):
    model = Evento
    form_class = EventoForm
    mensagem_sucesso = "Evento atualizado."

    def get_titulo(self) -> str:
        return f"Editar {self.object}"

    def get_success_url(self) -> str:
        return url_do_mes(self.object.inicio.replace(day=1))

    def get_url_cancelar(self) -> str:
        return self.object.get_absolute_url()


class EventoDeleteView(ExclusaoConfirmadaView):
    model = Evento
    permission_required = "calendario.delete_evento"

    def get_success_url(self) -> str:
        return url_do_mes(self.object.inicio.replace(day=1))
