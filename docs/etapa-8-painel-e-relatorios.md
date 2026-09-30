# Etapa 8: painel e relatórios

**Situação: 8a feita (painel na página inicial); 8b é proposta, a confirmar com o Lohrel antes de
começar.** O plano inicial do projeto dizia só "resumo por mês, pendências vencidas e movimentações
por usuário", com entrega "conforme a necessidade". Os detalhes abaixo vêm do que o escritório contou
nas etapas anteriores. As regras gerais estão no [CLAUDE.md](../CLAUDE.md).

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

Dois PRs, cada um a partir do `main`.

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
| Vidas | vidas e pessoas nos contratos vigentes hoje, e as entradas e saídas do mês (a alteração de plano não conta como entrada nem saída) | Contratos, até o relatório de vidas (8b) |
| Renovações | contratos vigentes que renovam nos próximos 60 dias, e quantos estão com a data de renovação já passada | Contratos, filtro novo "Renovam nos próximos 60 dias", que traz também as datas já passadas |

A tabela de contratos passou a mostrar a data de renovação dos vigentes, em vermelho quando já
passou (falta pôr a data da próxima). As contas ficam em `contas/painel.py`: 11 consultas ao todo,
qualquer que seja o tamanho da carteira. Os testes (`contas/tests/test_painel.py`) conferem cada
número, o número de consultas e se cada número bate com a lista para onde leva.

Os quadros seguem a proposta; no teste, o Lohrel confirma se cobrem o que o escritório olha todo dia.

### 8b. Relatórios

Um item "Relatórios" no menu, com filtro de período e, quando fizer sentido, download em Excel
(openpyxl, no estilo das planilhas que o sistema já gera):

1. **Resumo do mês:** inclusões, exclusões e alterações de plano por cliente e plano, separadas em
   concluídas, em aberto e rejeitadas (com o motivo), e as vidas de cada contrato no início e no fim
   do mês.
2. **Vidas da carteira:** vidas por cliente, filial e contrato numa data, com os totais. Reaproveite
   `beneficiarios/vidas.py`.
3. **Movimentações por usuário:** quem registrou cada pedido e quem fez cada passo no período (campo
   `registrada_por` e o histórico do `django-simple-history`).
4. **Pendências por responsável:** em aberto, vencidas e concluídas no período.

## Cuidados

- As contas são feitas no banco com o ORM (`annotate`, `Count`, `Subquery`), sem uma consulta por
  linha. Teste o número de consultas dos quadros do painel (`django_assert_num_queries`).
- Nos testes, calcule as datas a partir de hoje (ou fixe o dia) para o resultado não depender da data
  em que rodam.
- Nada de comissão ou de outro dado sensível: os relatórios mostram só o que as telas já mostram.
- Telas no visual da corretora (etapa 10a), já usáveis no celular (veja [frontend.md](frontend.md)).
- Testes com dados fictícios para cada número do painel e cada relatório. Os arquivos Excel são
  conferidos lendo-os de volta com openpyxl.

## Perguntas para o Lohrel antes da 8b

1. Quais relatórios são mais urgentes, e quais precisam sair em Excel?
2. O resumo do mês conta pelo mês de início da vigência ou pelo mês em que o pedido foi enviado à
   operadora?
3. Todos veem todos os relatórios, ou algum é só para a gestão?
