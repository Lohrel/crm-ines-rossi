# Etapa 8: painel e relatórios

**Situação: proposta, a confirmar com o Lohrel antes de começar.** O plano inicial do projeto dizia só
"resumo por mês, pendências vencidas e movimentações por usuário", com entrega "conforme a
necessidade". Os detalhes abaixo vêm do que o escritório contou nas etapas anteriores. As regras
gerais estão no [CLAUDE.md](../CLAUDE.md).

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

### 8a. Painel na página inicial

O painel substitui a página de Início (`contas/templates/contas/inicio.html`) e mantém os atalhos de
novo cliente. Cada quadro mostra um número e leva à lista já filtrada:

| Quadro | O que mostra | Leva para |
|---|---|---|
| Movimentações em aberto | em análise e aprovadas sem carteirinha, com as mais paradas (dias parado) | Movimentações |
| Boletos a enviar | vencidos e dos próximos 7 dias | Boletos |
| Pendências | vencidas e dos próximos 3 dias, com destaque para as da pessoa logada | Pendências, filtradas pelo responsável |
| Prazos do mês | dias até o fechamento das movimentações e até o envio da planilha do seguro de vida (dia 5) | Movimentações e Planilha mensal |
| Vidas | total da carteira hoje e o saldo do mês (entradas e saídas) | Relatório de vidas (8b) |
| Renovações | contratos com data de renovação nos próximos 60 dias | Contratos |

As listas já têm filtros (ex.: situação e responsável nas pendências; situação, tipo e "só fora do
vencimento" nos boletos). Onde faltar um filtro, acrescente-o na lista em vez de criar uma tela nova.

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
- Telas no visual padrão do Bootstrap, já usáveis no celular. O acabamento visual é a etapa 10 (veja
  [frontend.md](frontend.md)).
- Testes com dados fictícios para cada número do painel e cada relatório. Os arquivos Excel são
  conferidos lendo-os de volta com openpyxl.

## Perguntas para o Lohrel antes de começar

1. Quais números vocês olham todo dia? Os quadros acima cobrem isso?
2. Quais relatórios são mais urgentes, e quais precisam sair em Excel?
3. O resumo do mês conta pelo mês de início da vigência ou pelo mês em que o pedido foi enviado à
   operadora?
4. Todos veem todos os relatórios, ou algum é só para a gestão?
