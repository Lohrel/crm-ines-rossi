from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from calendario.models import Evento
from clientes.forms import BootstrapFormMixin, MesField
from clientes.widgets import CampoData


class EventoForm(BootstrapFormMixin, forms.ModelForm):
    hora = forms.TimeField(
        required=False,
        input_formats=["%H:%M", "%Hh%M", "%Hh", "%H"],
        widget=forms.TextInput(
            attrs={"placeholder": "hh:mm", "inputmode": "numeric", "maxlength": "5"}
        ),
        help_text="Ex.: 14:30. Em branco, o dia todo.",
        error_messages={"invalid": "Hora inválida. Use hh:mm, por exemplo 14:30."},
    )

    class Meta:
        model = Evento
        fields = [
            "titulo",
            "tipo",
            "inicio",
            "fim",
            "hora",
            "funcionario",
            "repete_todo_ano",
            "observacao",
        ]
        widgets = {
            "inicio": CampoData(),
            "fim": CampoData(),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hora"].widget.format = "%H:%M"
        funcionario = self.fields["funcionario"]
        funcionario.queryset = get_user_model().objects.filter(
            Q(is_active=True) | Q(pk=self.instance.funcionario_id)
        )
        funcionario.empty_label = "Ninguém"


class MesDoCalendarioForm(forms.Form):
    mes = MesField(required=False)
