from django import forms


class CampoData(forms.DateInput):
    """Data sempre em dia/mês/ano, qualquer que seja o idioma do navegador.

    O campo de data do próprio navegador (type="date") segue o idioma do
    computador: num navegador em inglês ele mostra mês/dia/ano e inverte as
    datas digitadas. Aqui o texto é sempre dd/mm/aaaa, e o botão de calendário
    (static/js/campos-data.js) é só um atalho para preenchê-lo.
    """

    template_name = "clientes/widgets/campo_data.html"

    def __init__(self, attrs=None):
        padrao = {
            "placeholder": "dd/mm/aaaa",
            "inputmode": "numeric",
            "autocomplete": "off",
            "maxlength": "10",
            "data-campo-data": "",
        }
        super().__init__(attrs={**padrao, **(attrs or {})}, format="%d/%m/%Y")
