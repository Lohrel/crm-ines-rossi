# Guia para quem continua o projeto

O Claude Code lê este arquivo automaticamente, e ele serve também para qualquer pessoa que assuma o
desenvolvimento. O [README](README.md) mostra as etapas e a estrutura das pastas; aqui ficam as
regras, as convenções e o estado atual.

## O projeto

CRM web para uma corretora de seguros (vida, saúde e dental, e alguns clientes de auto e imóvel).
Quatro funcionários usam o sistema pelo navegador, cada um com seu login, num servidor dentro do
escritório. Os clientes são pessoas físicas e empresas. Uma empresa pode ser um grupo com várias
filiais (unidades), cada uma com CNPJ e contato de RH próprios, e pode ter vários contratos.

O dono do projeto é o Lohrel (GitHub: Lohrel). Ele testa cada etapa no próprio computador e faz o
merge dos PRs.

## Primeiros passos de um agente novo

1. Leia este arquivo, o README e o guia da próxima etapa (veja "Estado atual").
2. Confira no GitHub os PRs abertos e o que falta em cada um.
3. Rode os testes (veja "Rodar e testar") antes de mudar qualquer coisa.
4. Antes de começar uma etapa, confirme o escopo com o Lohrel em poucas perguntas objetivas.

## Como falar com o Lohrel

- Sempre em português, direto ao ponto e em linguagem simples. Explique assuntos de banco de dados
  sem jargão.
- Ao entregar uma etapa, mande o link do PR e os passos para testar: `git fetch`,
  `git checkout <branch>` e `docker compose up -d --build`.
- Ele usa um terminal zsh (macOS ou Linux) e a pasta do projeto tem espaços no caminho: use aspas
  nos comandos. Para o servidor do escritório (Windows, por enquanto), dê comandos do Windows.
- Quando uma decisão muda o que o escritório vê ou faz, pergunte com opções curtas e diga qual você
  recomenda. No resto, escolha o caminho razoável, diga qual foi e siga.

## Regras que não mudam

1. **Repositório público, só código.** Nunca versione dados reais de clientes, planilhas, backups,
   anexos ou segredos (`.env`). Testes, exemplos e capturas de tela usam dados fictícios.
2. **Dados reais fora do chat.** Planilhas e backups reais não são enviados em conversas. Para
   entender um layout, peça só os nomes das colunas, sem as linhas. Nunca copie valores de uma
   planilha real para testes, textos de ajuda ou documentação.
3. **Sem comissão.** A comissão da corretora não entra no sistema (dado sensível, decisão da
   direção). Não crie campos de comissão.
4. **Boleto é só lembrete de envio.** Não há controle de pagamento nem campo de pré ou
   pós-pagamento (retirado a pedido do escritório: não traga de volta). Boleto não é excluído, é
   cancelado.
5. **Exclusão com confirmação digitada.** Só administradores veem o botão, que fica numa caixa
   recolhida "Excluir registros" no fim da página. A pessoa digita o nome exato, a exclusão é
   bloqueada enquanto houver contratos ligados e fica no histórico com usuário e horário.
   Reaproveite esse padrão (`ExclusaoConfirmadaView` em `clientes/views.py`) em qualquer exclusão
   nova. Pendências são concluídas ou editadas, não excluídas.
6. **Datas em dd/mm/aaaa.** Todo campo de data usa `clientes.widgets.CampoData`, e todo campo de mês
   usa `clientes.forms.MesField` (mm/aaaa). Nunca use `type="date"` ou `type="month"`: num navegador
   em inglês eles invertem dia e mês.
7. **CNPJ com letras.** A Receita emite CNPJ alfanumérico desde julho de 2026. Todo campo, importação
   ou planilha com CNPJ precisa aceitar letras (veja `clientes/documentos.py`).
8. **Anexos são sensíveis (LGPD).** DPS e documentos têm dados de saúde: ficam fora da pasta pública
   e só são entregues por uma tela com login (não existe `MEDIA_URL`, de propósito). Não crie campos
   de doença ou CID. Vale também para os documentos de clientes e seguradoras.
9. **Número de vidas é sempre calculado** a partir dos planos em vigor (`beneficiarios/vidas.py`),
   nunca digitado.
10. **Movimentação começa "Em análise".** Ela só é registrada depois de enviada à operadora, e a data
    de envio é obrigatória.

## Como trabalhar

- Etapas pequenas e seguras: cada funcionalidade é confirmada pelo Lohrel antes de começar a próxima.
- Um PR por etapa (ou subetapa, como 7a e 7b), sempre a partir do `main`. Não empilhe PRs: um PR já
  foi mergeado no branch de outro por engano. Se for inevitável, diga a ordem do merge.
- O branch leva o nome da etapa: `etapa-<número><letra>-<assunto>` (ex.: `etapa-7b-importar-vidas`).
  Se a sessão já começar com outro branch (o Claude Code na nuvem cria um `claude/...`), peça ao
  Lohrel autorização para usar o nome da convenção antes do primeiro push.
- Quem faz o merge é o Lohrel, nunca o agente.
- Antes de abrir o PR, tudo tem que passar localmente (o CI roda o mesmo):

  ```bash
  ruff check . && ruff format --check .
  DJANGO_SETTINGS_MODULE=config.settings_testes python manage.py makemigrations --check --dry-run
  pytest -q
  ```

- Confira as telas num navegador de verdade (ex.: Playwright com Chromium), com dados fictícios,
  também na largura de celular (390 px).
- Commits e PRs em português. A descrição do PR tem **Antes**, **Depois**, **Como** e **Como foi
  testado**.
- Atualize a lista de etapas do README no PR da etapa.
- Problemas de uso encontrados nos testes são corrigidos dentro da própria etapa.

## Rodar e testar

Requisitos: Python 3.11+ (o Docker usa 3.12) e PostgreSQL 16.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

- Sem `.env`, os testes usam `config.settings_testes`: banco `crm`, usuário `crm` e senha `crm` em
  `localhost`. O usuário precisa poder criar bancos (`CREATEDB`), porque o pytest cria o banco de
  teste.
- Num ambiente sem Docker (ex.: um sandbox Debian/Ubuntu na nuvem, como root), dá para subir um
  PostgreSQL 16 local assim:

  ```bash
  mkdir -p /var/tmp/pg && chown postgres /var/tmp/pg
  su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/pg/dados"
  su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/pg/dados -o '-k /var/tmp/pg' -l /var/tmp/pg/log start"
  su postgres -c "psql -h /var/tmp/pg -c \"CREATE ROLE crm LOGIN CREATEDB PASSWORD 'crm'\" -c 'CREATE DATABASE crm OWNER crm'"
  ```

- Para usar o sistema no navegador durante o desenvolvimento:

  ```bash
  export DJANGO_SETTINGS_MODULE=config.settings_testes
  python manage.py migrate
  python manage.py createsuperuser
  python manage.py runserver      # http://localhost:8000
  ```

- O sistema completo, como no servidor, sobe com Docker Compose (veja `docs/instalacao.md`). No
  computador de quem testa, o `.env` precisa de `localhost` em `CRM_HOSTNAME`,
  `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS`; sem isso, o navegador mostra
  `ERR_SSL_PROTOCOL_ERROR`. O Docker precisa do plugin Compose.
- O Caddy serve CSS e JavaScript sem hash no nome: depois de mudar um deles, recarregue a página com
  Ctrl+Shift+R.

## Convenções do código

- Django 5.2 com views baseadas em classe e templates do Django com Bootstrap 5 local (sem CDN: o
  sistema tem que funcionar sem internet). O guia das telas está em [docs/frontend.md](docs/frontend.md),
  e as cores e a fonte da corretora ficam em `static/css/crm.css`.
- Nomes em português, como no código existente: modelos, campos, views, templates e testes.
- Todas as páginas exigem login (`LoginRequiredMiddleware`); só a verificação de saúde do Docker é
  aberta.
- Todo cadastro tem histórico (`django-simple-history`, com o usuário gravado pelo middleware). Cada
  app tem um `historico.py` que alimenta a linha do tempo do cliente.
- Formulários herdam `BootstrapFormMixin` (`clientes/forms.py`), que aplica as classes do Bootstrap
  e marca os campos com erro. As telas de cadastro e edição usam o `FormularioMixin`
  (`clientes/views.py`), e o endereço de volta em `proximo` passa sempre por `destino_seguro`.
- Importação de planilha sempre tem prévia antes de gravar: a prévia roda numa transação desfeita no
  fim, a planilha lida vai assinada no formulário (`django.core.signing`) e a confirmação grava tudo
  numa transação só. Há limites de tamanho, de arquivo descompactado e de linhas. Veja
  `movimentacoes/importacao.py` (planilha mensal) e `beneficiarios/importacao_de_vidas.py` (seguro
  de vida); as partes comuns ficam em `clientes/planilhas.py`.
- Planilhas do Excel com openpyxl (a leitura é protegida pelo `defusedxml`). Na exportação, texto que
  começa com `=` não pode virar fórmula.
- Testes com pytest-django. Fixtures compartilhados ficam em `*/tests/fixtures.py`, carregados pelo
  `conftest.py` da raiz (`pytest_plugins`). Não importe fixtures de outro módulo de teste (o ruff
  acusa F811).
- ruff: linhas de até 100 caracteres, regras `E, F, W, I, B, UP, DJ, S, SIM, N`.

## Estado atual (30/09/2026)

- As etapas 0 a 8 estão no `main`: a 8a (painel na página inicial), a 8b (calendário) e a 8c
  (relatórios, PR #19), com o [guia da etapa 8](docs/etapa-8-painel-e-relatorios.md).
- A etapa 7b (importar a planilha atual do seguro de vida, com prévia de cada vida) entrou no `main`
  pelo PR #11 antes do teste com a planilha real, que o Lohrel faz no computador dele (a importação
  ignora linhas sem nome). Se ele achar um problema, corrija num branch novo a partir do `main`, com
  um PR novo. A descrição do PR #11 explica como a importação funciona.
- A etapa 9 (auto e imóvel) está no `main` (PR #20).
- **10c**, acabamento no computador: branch `etapa-10c-computador`, esperando o Lohrel testar. O
  escopo foi escolhido por ele a partir de uma análise das telas (veja
  [docs/frontend.md](docs/frontend.md)). Se ele pedir ajustes, corrija nesse mesmo branch.
- O sistema está **em produção** no escritório (16/10/2026). Nenhuma atualização pode quebrar o
  sistema ou perder dados: migração que mexe em dados existentes precisa de teste de migração
  (veja `clientes/tests/test_migracoes.py`), e todo arquivo enviado fica em `MEDIA_ROOT`, a pasta
  que o backup copia.
- **11. Documentos anexados** (seguradoras e clientes): esperando o Lohrel testar. Os arquivos herdam
  `ArquivoAnexado` (`clientes/models.py`); reaproveite essa base em anexos novos.
- **13. Tipos de contrato e vários planos**: 13a (PME, SPG e coletivo por adesão, PR #28) e 13b
  (vários planos no mesmo contrato), esperando o Lohrel testar. As correções da LGPD propostas
  antes passam a ser a etapa 14.
- **15. Telefone e e-mail nos cadastros**: branch `etapa-15-telefone-e-email`, esperando o Lohrel
  testar. Telefone, WhatsApp e e-mail ficam num grupo próprio, separado do endereço (empresa,
  unidade, pessoa física e contato). Sem migração. O número 14 está reservado para as correções da
  LGPD.
- Próxima etapa:
  - **10d. Celular**, depois do merge da 10c: as listas viram fichas abaixo de 576 px e os filtros
    ficam recolhidos num botão (combinado com o Lohrel). Com ela e a aprovação do painel pela
    equipe, a etapa 10 termina. Veja [docs/frontend.md](docs/frontend.md).

## Decisões do escritório que valem para as próximas etapas

- Uma pessoa costuma estar em mais de um plano (ex.: saúde e dental), e o dependente pode estar em um
  ou nos dois planos do titular.
- Cada plano de uma operadora costuma ser um contrato próprio, com o nome do plano em
  "Produto/plano". Quando a mesma apólice tem vários planos (ex.: TNPQ e TNP4 na Bradesco), eles
  são cadastrados no contrato (`Plano`, etapa 13b) e cada pessoa fica num deles (`Vinculo.plano`).
  Contrato sem planos cadastrados funciona como antes. O dependente pode ficar num plano diferente
  do titular, e a troca entre planos do mesmo contrato é uma movimentação de alteração de plano.
- O RH manda as movimentações do mês até o dia de fechamento do contrato (ex.: dia 25), e a vigência
  começa no dia 1º do mês seguinte. Pedidos com carência ficam em análise até a carteirinha ser
  enviada. Pedido rejeitado (rasura, prazo da entrevista médica) vira uma nova inclusão.
- A pendência é sempre ligada a um cliente e, nas empresas com filiais, à filial. Movimentações em
  aberto não são pendências: ficam no menu Movimentações.
- O dia de vencimento de cada contrato é o que mais importa nos boletos. Boletos fora do vencimento
  (reajuste, coparticipação, casos especiais) aparecem marcados.
- Seguro de vida: o salário é opcional e só aparece no plano de vida do titular. Ele serve para
  conferir se a cobrança da seguradora está certa. A planilha vai para a seguradora do dia 1º ao
  dia 5, e Local e subfatura (SUB) são de cada filial no contrato.
- Visual (etapa 10a): menu marinho com o logo branco e tela de entrada escura, a partir do cartão de
  visita e dos envelopes da corretora. O logo e o nome da corretora podem ficar no repositório
  (autorizado pelo Lohrel em 30/09/2026); se o software passar a ser proprietário, eles saem.
- Painel (etapa 8a): o número de vidas não fica na página inicial, porque o escritório não consulta
  todo dia.
- Calendário (etapa 8b): a equipe anota férias ou ausências, reuniões, aniversários e outros eventos
  (de um dia ou de um período, e os que se repetem todo ano). Entram sozinhos os prazos das
  pendências em aberto, as renovações dos contratos vigentes e os prazos do mês (uma linha por dia de
  fechamento e o envio da planilha do seguro de vida). As movimentações não entram, para não encher o
  calendário. No painel, o quadro "Próximos 7 dias" mostra só o que a equipe anotou.
- Relatórios (etapa 8c): vidas ativas numa data (por empresa, filial ou contrato), inclusões por
  período (pela vigência ou pelo envio à operadora) e apólices com os dados do cliente e o período de
  renovação. Todos veem todos os relatórios, e cada um também sai em Excel.
- Auto e imóvel (etapa 9): poucos clientes, e os dados servem só para consulta. Cada apólice de
  auto ou imóvel guarda os seus veículos ou imóveis (`BemSegurado`, vários por apólice, como numa
  frota), com os campos da planilha do escritório. A vigência, a seguradora e o número ficam no
  contrato. O ramo diz se a apólice guarda veículos ou imóveis (campo "bem segurado" do ramo, no
  admin). Eles aparecem na página do cliente, e a placa entra na busca de clientes e de contratos.
- Acabamento (etapa 10c): o menu fica numa linha a partir de 992 px, com o nome de quem entrou num
  botão com o Sair. As telas usam tons azul-acinzentados claros (o Lohrel achou as telas brancas
  demais e escolheu esta entre três opções). Nas listas, selo só para a exceção (ex.: "Inativo"),
  não para o que vale para quase todas as linhas, e os planos da pessoa ficam em selos neutros. As
  explicações das listas ficam recolhidas em "Como funciona esta lista". A versão para imprimir foi
  oferecida e não foi pedida.
- Cada seguradora tem uma cor, escolhida no cadastro, para a equipe saber qual portal abrir sem ler.
  Ela aparece como uma faixa discreta à esquerda da linha nas listas (o Lohrel preferiu a faixa a uma
  etiqueta colorida, menos poluída) e como um ponto antes do nome nas outras telas.
