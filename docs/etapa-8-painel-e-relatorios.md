# Etapa 8: painel, calendário e relatórios

**Situação: 8a (painel na página inicial), 8b (calendário) e 8c (relatórios) feitas.** O plano
inicial do projeto dizia só "resumo por mês, pendências vencidas e movimentações por usuário", com
entrega "conforme a necessidade". Os detalhes abaixo vêm do que o escritório contou nas etapas
anteriores. As regras gerais estão no [CLAUDE.md](../CLAUDE.md).

## Objetivo

Ao entrar no sistema, cada pessoa vê o que precisa de atenção hoje, sem abrir tela por tela. A
corretora ganha relatórios simples para acompanhar a carteira mês a mês.

## O que já se sabe do escritório

- O número de vidas por grupo, filial e contrato é essencial, para acompanhar as inclusões do mês em
  cada plano.
- As movimentações do mês chegam até o dia de fechamento do contrato (ex.: 25) e valem a partir do
  dia 1º seguinte. As que ficam em análise (carência, entrevista médica) são acompanhadas até a
  carteirinha ser enviada.
- Nos boletos, o importante é não esquecer de enviar: vencidos em vermelho, próximos 7 dias em
  amarelo.
- A planilha do seguro de vida vai para a seguradora do dia 1º ao dia 5.
- Cada pendência tem responsável e prazo, e cada pessoa quer ver as suas.
- Comissão não entra no sistema.

## Proposta

Um PR por subetapa, cada um a partir do `main`.

### 8a. Painel na página inicial (feita)

O painel substitui a página de Início (`contas/templates/contas/inicio.html`, com um arquivo por
quadro em `contas/templates/contas/painel/`) e mantém os atalhos de novo cliente. É o mesmo para
todos, com as pendências de quem entrou em destaque. Cada quadro mostra um número, que leva à lista
já filtrada com os mesmos registros, e embaixo os até 3 mais urgentes:

| Quadro | O que mostra | Leva para |
|---|---|---|
| Movimentações em aberto | em análise e aprovadas (falta concluir, ex.: enviar a carteirinha), com as há mais tempo em aberto (dias desde que o pedido chegou, como na lista) | Movimentações, com os filtros novos "Em análise" e "Aprovadas" |
| Boletos a enviar | vencidos e dos próximos 7 dias | Boletos, filtro novo "A enviar (7 dias)" |
| Suas pendências | as de quem entrou, vencidas e dos próximos 3 dias; no rodapé, quantas da equipe | Pendências, filtro novo "Pedem atenção (3 dias)", com o responsável |
| Prazos do mês | os próximos fechamentos das movimentações (o dia de fechamento de cada contrato vigente) e o envio da planilha do seguro de vida (até o dia 5), em amarelo a 5 dias ou menos | Movimentações e Planilha mensal |
| Renovações | contratos vigentes que renovam nos próximos 60 dias, e quantos estão com a data de renovação já passada | Contratos, filtro novo "Renovam nos próximos 60 dias", que traz também as datas já passadas |
| Próximos 7 dias (entrou na 8b) | o que a equipe anotou no calendário para os próximos 7 dias (férias, reuniões, aniversários); um evento de vários dias aparece uma vez, com o período | Calendário |

A tabela de contratos passou a mostrar a data de renovação dos vigentes, em vermelho quando já
passou (falta pôr a data da próxima). As contas ficam em `contas/painel.py`: 11 consultas ao todo,
qualquer que seja o tamanho da carteira. Os testes (`contas/tests/test_painel.py`) conferem cada
número, o número de consultas e se cada número bate com a lista para onde leva.

A proposta tinha também um quadro de vidas (total da carteira e saldo do mês). O Lohrel pediu para
tirá-lo (30/09/2026): não é informação que o escritório consulta todo dia. As vidas ficam na lista
de contratos, na página de cada cliente e no relatório de vidas proposto abaixo.

### 8b. Calendário (feita)

Pedido do Lohrel (30/09/2026): um calendário que todos veem, no lugar do quadro branco em que a
chefe anotava as datas importantes. O escopo combinado com ele:

- Item "Calendário" no menu, com o mês inteiro como o quadro: grade de domingo a sábado no
  computador e lista dos dias no celular.
- A equipe anota férias ou ausências, reuniões, aniversários e outros eventos: de um dia (com hora,
  se quiser) ou de um período, e os que se repetem todo ano. É o modelo `Evento`, no app
  `calendario`.
- Entram sozinhos os prazos das pendências em aberto, as renovações dos contratos vigentes e os
  prazos do mês: uma linha por dia de fechamento das movimentações, com quantos contratos fecham, e
  o envio da planilha do seguro de vida no dia 5.
- As movimentações não entram, para não encher o calendário.
- O quadro "Próximos 7 dias" do painel, no lugar do de vidas, mostra o que a equipe anotou; as
  pendências, as renovações e os prazos já têm quadro próprio.
- Qualquer pessoa anota e edita. Excluir é só para administradores, com confirmação digitada.

As datas de um período são montadas em `calendario/agenda.py`, com cinco consultas qualquer que
seja o mês. Os testes ficam em `calendario/tests/test_calendario.py`.

### 8c. Relatórios (feita)

O Lohrel escolheu três relatórios (30/09/2026), todos liberados para toda a equipe. Um item
"Relatórios" no menu leva a uma página com os três, e cada um tem filtros, um resumo, a tabela e o
botão "Baixar em Excel", que usa os mesmos filtros (openpyxl, no estilo das planilhas que o sistema
já gera):

1. **Vidas ativas:** cada pessoa em cada plano em vigor numa data (hoje, se não escolher), por
   empresa, filial ou contrato, com os totais de vidas, pessoas, titulares e dependentes e as vidas de
   cada contrato. Conta como `beneficiarios/vidas.py`: o dependente fica na filial do titular.
2. **Inclusões por período:** as inclusões de um período (o mês atual, se não escolher), contado pela
   vigência ou pelo envio à operadora, com a etapa de cada uma e os totais por etapa. O filtro de
   tipo também mostra exclusões, alterações de plano ou todas; a alteração entra no plano de onde a
   pessoa sai e no plano para onde vai.
3. **Apólices:** os contratos (vigentes, se não escolher outra situação) com os dados do cliente
   (CPF ou CNPJ da matriz, contato principal, telefone, e-mail e cidade), filtrados pelo período de
   renovação, pela seguradora e pelo ramo, com o valor mensal e as vidas de hoje.

As consultas ficam em `relatorios/consultas.py`, com um número fixo de consultas ao banco qualquer
que seja o tamanho da carteira, e o Excel em `relatorios/excel.py`. A tela mostra 200 linhas por
página; o Excel traz todas. Os testes ficam em `relatorios/tests/test_relatorios.py`.

Ficaram de fora da proposta inicial, até o escritório pedir: o resumo do mês com as vidas no início e
no fim, as movimentações por usuário e as pendências por responsável.

## Cuidados

- As contas são feitas no banco com o ORM (`annotate`, `Count`, `Subquery`), sem uma consulta por
  linha. Teste o número de consultas dos quadros do painel (`django_assert_num_queries`).
- Nos testes, calcule as datas a partir de hoje (ou fixe o dia) para o resultado não depender da data
  em que rodam.
- Nada de comissão ou de outro dado sensível: os relatórios mostram só o que as telas já mostram.
- Telas no visual da corretora (etapa 10a), já usáveis no celular (veja [frontend.md](frontend.md)).
- Testes com dados fictícios para cada número do painel e cada relatório. Os arquivos Excel são
  conferidos lendo-os de volta com openpyxl.
