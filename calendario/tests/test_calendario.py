"""Calendário: as anotações da equipe e as datas que o sistema já conhece."""

from datetime import date, time

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apolices.models import Contrato
from beneficiarios.tests.fixtures import HOJE, contrato
from calendario.agenda import Agenda, dia_no_mes, lista_por_dia
from calendario.models import Evento, mesmo_dia_no_ano
from contas.models import Usuario
from movimentacoes.models import Movimentacao
from pendencias.models import Pendencia

pytestmark = pytest.mark.django_db

OUTUBRO = date(2026, 10, 1)
FIM_DE_OUTUBRO = date(2026, 10, 31)


def evento(titulo="Reunião de equipe", inicio=date(2026, 10, 7), **extra):
    novo = Evento(titulo=titulo, inicio=inicio, **extra)
    novo.full_clean()
    novo.save()
    return novo


def dias(*numeros: int, mes: int = 10, ano: int = 2026) -> list[date]:
    return [date(ano, mes, numero) for numero in numeros]


def mudar(plano, **campos):
    Contrato.objects.filter(pk=plano.pk).update(**campos)


def titulos(itens) -> list[str]:
    return [item.titulo for item in itens]


# ------------------------------------------------------------------
# Datas de cada evento
# ------------------------------------------------------------------


def test_mesmo_dia_em_outro_ano():
    assert mesmo_dia_no_ano(date(2025, 10, 20), 2027) == date(2027, 10, 20)
    # O 29 de fevereiro vira 28 nos anos que não o têm.
    assert mesmo_dia_no_ano(date(2024, 2, 29), 2026) == date(2026, 2, 28)


def test_dia_no_mes_curto():
    assert dia_no_mes(31, date(2026, 2, 1)) == date(2026, 2, 28)
    assert dia_no_mes(5, date(2026, 10, 1)) == date(2026, 10, 5)


def test_evento_de_um_dia_e_periodo(db):
    reuniao = evento()
    ferias = evento("Férias do Bruno", date(2026, 10, 5), fim=date(2026, 10, 16), tipo="FER")
    assert reuniao.dias_entre(OUTUBRO, FIM_DE_OUTUBRO) == dias(7)
    assert ferias.dias_entre(OUTUBRO, FIM_DE_OUTUBRO) == dias(*range(5, 17))
    assert ferias.dias_entre(date(2026, 10, 10), date(2026, 10, 12)) == dias(10, 11, 12)
    assert ferias.dias_entre(date(2026, 11, 1), date(2026, 11, 30)) == []


def test_repete_todo_ano_a_partir_do_ano_anotado(db):
    aniversario = evento("Aniversário da Ana", date(2025, 10, 20), repete_todo_ano=True)
    assert aniversario.dias_entre(OUTUBRO, FIM_DE_OUTUBRO) == dias(20)
    assert aniversario.dias_entre(date(2024, 10, 1), date(2024, 10, 31)) == []
    bissexto = evento("Aniversário do Caio", date(2024, 2, 29), repete_todo_ano=True)
    assert bissexto.dias_entre(date(2026, 2, 1), date(2026, 2, 28)) == dias(28, mes=2)


def test_periodo_repetido_que_atravessa_o_ano(db):
    recesso = evento(
        "Recesso de fim de ano", date(2025, 12, 28), fim=date(2026, 1, 3), repete_todo_ano=True
    )
    janeiro = recesso.dias_entre(date(2027, 1, 1), date(2027, 1, 31))
    assert janeiro == dias(1, 2, 3, mes=1, ano=2027)


def test_ultimo_dia_antes_da_data_e_barrado(db):
    with pytest.raises(ValidationError, match="O último dia não pode ser antes da data."):
        evento(fim=date(2026, 10, 6))
    # Período de um dia só vira um dia só.
    assert evento(fim=date(2026, 10, 7)).fim is None


# ------------------------------------------------------------------
# O que entra no calendário
# ------------------------------------------------------------------


@pytest.fixture
def colega(db):
    return Usuario.objects.create_user(
        username="bruno", password="senha-forte-de-teste", first_name="Bruno", last_name="Reis"
    )


def test_agenda_junta_anotacoes_pendencias_renovacoes_e_prazos(
    usuario, colega, pessoa, empresa, seguradora, matriz, saude, dental, vida
):
    evento("Férias do Bruno", date(2026, 10, 5), fim=date(2026, 10, 16), tipo="FER")
    evento("Reunião com a operadora", date(2026, 10, 5), hora=time(14, 30))
    evento("Reunião de equipe", date(2026, 10, 5), hora=time(9, 0))
    evento("Reunião de setembro", date(2026, 9, 30))
    Pendencia.objects.create(
        cliente=pessoa, responsavel=colega, prazo=date(2026, 10, 5), descricao="Cobrar a DPS"
    )
    Pendencia.objects.create(
        cliente=pessoa, responsavel=usuario, prazo=date(2026, 10, 2), descricao="Ligar para o RH"
    )
    Pendencia.objects.create(
        cliente=pessoa,
        responsavel=usuario,
        prazo=date(2026, 10, 6),
        descricao="Já concluída",
        concluida_em=date(2026, 10, 1),
    )
    mudar(saude, data_renovacao=date(2026, 10, 5), dia_fechamento=25)
    mudar(dental, dia_fechamento=25)
    cancelado = contrato(empresa, seguradora, "Saúde", "S-9", [matriz])
    mudar(cancelado, data_renovacao=date(2026, 10, 9), dia_fechamento=31, situacao="CAN")
    outro = contrato(empresa, seguradora, "Saúde", "S-2", [matriz])
    mudar(outro, dia_fechamento=31)

    datas = Agenda(OUTUBRO, FIM_DE_OUTUBRO, hoje=date(2026, 10, 3)).por_dia()

    # No dia 5: quem está fora, os eventos pela hora, o prazo, a renovação e a pendência.
    assert [(item.categoria, item.titulo) for item in datas[date(2026, 10, 5)]] == [
        ("ferias", "Férias do Bruno"),
        ("evento", "Reunião de equipe"),
        ("evento", "Reunião com a operadora"),
        ("prazo", "Envio da planilha do seguro de vida"),
        ("renovacao", "Renovação: Supermercados Exemplo"),
        ("pendencia", "Cobrar a DPS"),
    ]
    assert titulos(datas[date(2026, 10, 16)]) == ["Férias do Bruno"]
    assert date(2026, 10, 17) not in datas
    # A pendência vencida fica marcada; a concluída não entra.
    assert [(p.titulo, p.atrasada) for p in datas[date(2026, 10, 2)]] == [("Ligar para o RH", True)]
    assert titulos(datas[date(2026, 10, 6)]) == ["Férias do Bruno"]
    # Fechamentos: uma linha por dia, com quantos contratos vigentes fecham nele.
    assert [(p.titulo, p.detalhe) for p in datas[date(2026, 10, 25)]] == [
        ("Fechamento das movimentações", "2 contratos fecham neste dia")
    ]
    assert [p.detalhe for p in datas[date(2026, 10, 31)]] == ["1 contrato fecha neste dia"]
    # A renovação do contrato cancelado não entra, nem o que é de outro mês.
    assert titulos(datas[date(2026, 10, 9)]) == ["Férias do Bruno"]
    assert date(2026, 9, 30) not in datas


def test_sem_seguro_de_vida_nao_tem_prazo_da_planilha(usuario, saude):
    datas = Agenda(OUTUBRO, FIM_DE_OUTUBRO).por_dia()
    assert date(2026, 10, 5) not in datas


def test_movimentacoes_nao_entram(usuario, titular, saude):
    Movimentacao.objects.create(
        tipo="INC", beneficiario=titular, contrato=saude, enviada_em=OUTUBRO, vigencia=OUTUBRO
    )
    assert Agenda(OUTUBRO, FIM_DE_OUTUBRO).por_dia() == {}


def test_agenda_faz_as_mesmas_consultas_com_mais_datas(
    django_assert_num_queries, usuario, pessoa, saude, dental, vida
):
    def registros(dia: int):
        evento(f"Reunião {dia}", date(2026, 10, dia))
        evento(f"Férias {dia}", date(2026, 10, dia), fim=date(2026, 10, dia + 3), tipo="FER")
        Pendencia.objects.create(
            cliente=pessoa, responsavel=usuario, prazo=date(2026, 10, dia), descricao=f"P {dia}"
        )

    mudar(saude, data_renovacao=date(2026, 10, 9), dia_fechamento=25)
    registros(3)
    with django_assert_num_queries(5):
        Agenda(OUTUBRO, FIM_DE_OUTUBRO).por_dia()
    mudar(dental, data_renovacao=date(2026, 10, 19), dia_fechamento=20)
    registros(10)
    registros(20)
    with django_assert_num_queries(5):
        Agenda(OUTUBRO, FIM_DE_OUTUBRO).por_dia()


# ------------------------------------------------------------------
# Telas
# ------------------------------------------------------------------


def test_calendario_mostra_o_mes_pedido(logado):
    evento("Férias do Bruno", date(2026, 10, 5), fim=date(2026, 10, 7), tipo="FER")
    resposta = logado.get(reverse("calendario:mes"), {"mes": "10/2026"})
    pagina = resposta.content.decode()
    assert "Outubro de 2026" in pagina
    assert resposta.context["url_anterior"] == "/calendario/?mes=09%2F2026"
    assert resposta.context["url_seguinte"] == "/calendario/?mes=11%2F2026"
    # Na grade, o período aparece em todos os dias.
    celulas = [dia for semana in resposta.context["semanas"] for dia in semana]
    com_ferias = [c["data"] for c in celulas if "Férias do Bruno" in titulos(c["itens"])]
    assert com_ferias == dias(5, 6, 7)
    # A grade começa no domingo, com os dias do mês anterior.
    assert celulas[0]["data"] == date(2026, 9, 27) and not celulas[0]["do_mes"]
    assert f'href="{reverse("calendario:novo")}?data=2026-10-12"' in pagina


def test_sem_mes_ou_mes_invalido_mostra_o_mes_atual(logado):
    este_mes = HOJE.replace(day=1)
    resposta = logado.get(reverse("calendario:mes"))
    assert resposta.context["mes"] == este_mes and resposta.context["eh_este_mes"]
    assert logado.get(reverse("calendario:mes"), {"mes": "13/2026"}).context["mes"] == este_mes


def test_lista_do_celular_mostra_o_periodo_so_no_primeiro_dia(usuario):
    evento("Férias do Bruno", date(2026, 10, 5), fim=date(2026, 10, 16), tipo="FER")
    evento("Férias da Ana", date(2026, 9, 28), fim=date(2026, 10, 2), tipo="FER")
    evento("Reunião de equipe", date(2026, 10, 7))
    datas = Agenda(date(2026, 9, 27), date(2026, 11, 7)).por_dia()
    lista = lista_por_dia(datas, OUTUBRO, FIM_DE_OUTUBRO)
    assert [(dia, titulos(itens)) for dia, itens in lista] == [
        (date(2026, 10, 1), ["Férias da Ana"]),
        (date(2026, 10, 5), ["Férias do Bruno"]),
        (date(2026, 10, 7), ["Reunião de equipe"]),
    ]
    assert lista[1][1][0].detalhe == "de 05/10 a 16/10"


def test_menu_tem_o_calendario(logado):
    resposta = logado.get(reverse("calendario:mes"))
    abertos = [item["texto"] for item in resposta.context["menu_principal"] if item["aberto"]]
    assert abertos == ["Calendário"]


def test_novo_evento_ja_vem_com_a_data_do_dia(logado):
    pagina = logado.get(reverse("calendario:novo"), {"data": "2026-10-12"}).content.decode()
    assert 'value="12/10/2026"' in pagina
    hoje = logado.get(reverse("calendario:novo"), {"data": "ontem"}).content.decode()
    assert f'value="{HOJE:%d/%m/%Y}"' in hoje


def test_anotar_ferias(logado, usuario, colega):
    resposta = logado.post(
        reverse("calendario:novo"),
        {
            "titulo": "Férias do Bruno",
            "tipo": "FER",
            "inicio": "05/10/2026",
            "fim": "16/10/2026",
            "hora": "",
            "funcionario": colega.pk,
            "observacao": "Volta no dia 19.",
        },
    )
    assert resposta.status_code == 302
    assert resposta.url == "/calendario/?mes=10%2F2026"
    ferias = Evento.objects.get()
    assert (ferias.inicio, ferias.fim, ferias.funcionario) == (
        date(2026, 10, 5),
        date(2026, 10, 16),
        colega,
    )
    assert ferias.registrado_por == usuario and not ferias.repete_todo_ano


@pytest.mark.parametrize(("digitada", "hora"), [("14:30", time(14, 30)), ("9h", time(9, 0))])
def test_hora_da_reuniao(logado, digitada, hora):
    dados = {"titulo": "Reunião", "tipo": "REU", "inicio": "07/10/2026", "hora": digitada}
    assert logado.post(reverse("calendario:novo"), dados).status_code == 302
    assert Evento.objects.get().hora == hora


def test_hora_invalida(logado):
    dados = {"titulo": "Reunião", "tipo": "REU", "inicio": "07/10/2026", "hora": "25:00"}
    resposta = logado.post(reverse("calendario:novo"), dados)
    assert resposta.status_code == 200
    assert "Hora inválida. Use hh:mm, por exemplo 14:30." in resposta.content.decode()
    assert not Evento.objects.exists()


def test_pagina_do_evento_editar_e_historico(logado, usuario):
    reuniao = evento(registrado_por=usuario)
    pagina = logado.get(reuniao.get_absolute_url()).content.decode()
    assert "Reunião de equipe" in pagina and "07/10/2026" in pagina
    resposta = logado.post(
        reverse("calendario:editar", args=[reuniao.pk]),
        {"titulo": "Reunião de equipe", "tipo": "REU", "inicio": "08/10/2026", "hora": "10:00"},
    )
    assert resposta.url == "/calendario/?mes=10%2F2026"
    reuniao.refresh_from_db()
    assert reuniao.inicio == date(2026, 10, 8) and reuniao.hora == time(10, 0)
    pagina = logado.get(reuniao.get_absolute_url()).content.decode()
    assert "alterou o evento" in pagina and "Excluir registros" not in pagina


def test_funcionario_nao_exclui(logado):
    reuniao = evento()
    assert logado.get(reverse("calendario:excluir", args=[reuniao.pk])).status_code == 403
    assert Evento.objects.exists()


def test_administrador_exclui_digitando_o_titulo(admin):
    reuniao = evento()
    assert "Excluir registros" in admin.get(reuniao.get_absolute_url()).content.decode()
    url = reverse("calendario:excluir", args=[reuniao.pk])
    assert admin.post(url, {"confirmacao": "outra coisa"}).status_code == 200
    resposta = admin.post(url, {"confirmacao": "Reunião de equipe"})
    assert resposta.status_code == 302 and resposta.url == "/calendario/?mes=10%2F2026"
    assert not Evento.objects.exists()
    assert Evento.history.filter(history_type="-").count() == 1


def test_navegar_entre_os_meses(logado):
    # Um mês do passado, para o "Hoje" não aparecer marcado.
    pagina = logado.get(reverse("calendario:mes"), {"mes": "10/2020"}).content.decode()
    assert '<span aria-hidden="true">‹</span> Setembro</a>' in pagina
    assert 'Novembro <span aria-hidden="true">›</span></a>' in pagina
    assert (
        f'<a href="{reverse("calendario:mes")}" class="btn btn-outline-secondary">Hoje</a>'
        in pagina
    )
    # No mês atual, o "Hoje" fica marcado.
    atual = logado.get(reverse("calendario:mes")).content.decode()
    assert 'class="btn btn-outline-secondary active" aria-current="date">Hoje</a>' in atual
