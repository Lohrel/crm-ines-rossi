from calendar import Calendar
from datetime import date, timedelta

from django.urls import reverse
from django.utils.http import urlencode
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from boletos.models import somar_meses
from calendario.agenda import Agenda, lista_por_dia
from calendario.forms import EventoForm, MesDoCalendarioForm
from calendario.historico import LinhaDoTempoDoEvento
from calendario.models import Evento
from clientes.views import ExclusaoConfirmadaView, FormularioMixin

# Semana de domingo a sábado, como nos calendários daqui.
SEMANA = Calendar(firstweekday=6)
DIAS_DA_SEMANA = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]


def url_do_mes(mes: date) -> str:
    return f"{reverse('calendario:mes')}?{urlencode({'mes': f'{mes:%m/%Y}'})}"


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
                # No celular, a lista dos dias do mês que têm alguma data.
                "dias_com_datas": lista_por_dia(
                    datas, mes, somar_meses(mes, 1) - timedelta(days=1)
                ),
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
