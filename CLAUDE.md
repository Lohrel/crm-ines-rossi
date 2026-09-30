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
   de doença ou CID.
9. **Número de vidas é sempre calculado** a partir dos planos em vigor (`beneficiarios/vidas.py`),
   nunca digitado.
10. **Movimentação começa "Em análise".** Ela só é registrada depois de enviada à operadora, e a data
    de envio é obrigatória.

## Como trabalhar

- Etapas pequenas e seguras: cada funcionalidade é confirmada pelo Lohrel antes de começar a próxima.
- Um PR por etapa (ou subetapa, como 7a e 7b), sempre a partir do `main`. Não empilhe PRs: um PR já
  foi mergeado no branch de outro por engano. Se for inevitável, diga a ordem do merge.
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
  sistema tem que funcionar sem internet). O guia das telas está em [docs/frontend.md](docs/frontend.md).
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
  numa transação só. Há limites de tamanho, de arquivo descompactado e de linhas. O modelo é
  `movimentacoes/importacao.py`; o PR #11 separa as partes comuns em `clientes/planilhas.py`.
- Planilhas do Excel com openpyxl (a leitura é protegida pelo `defusedxml`). Na exportação, texto que
  começa com `=` não pode virar fórmula.
- Testes com pytest-django. Fixtures compartilhados ficam em `*/tests/fixtures.py`, carregados pelo
  `conftest.py` da raiz (`pytest_plugins`). Não importe fixtures de outro módulo de teste (o ruff
  acusa F811).
- ruff: linhas de até 100 caracteres, regras `E, F, W, I, B, UP, DJ, S, SIM, N`.

## Estado atual (30/09/2026)

- As etapas 0 a 7a estão no `main`.
- **7b**, importar a planilha atual do seguro de vida com prévia de cada vida: PR #11, branch
  `etapa-7b-importar-vidas`. Está esperando o Lohrel testar com a planilha real no computador dele
  (a importação ignora linhas sem nome). Se ele achar um problema, corrija nesse mesmo branch. A
  descrição do PR explica como a importação funciona. Com o merge, a etapa 7 termina.
- A instalação no servidor do escritório, com os 4 logins, ainda não foi confirmada.
- Próximas etapas:
  - **8. Painel e relatórios**: proposta em
    [docs/etapa-8-painel-e-relatorios.md](docs/etapa-8-painel-e-relatorios.md).
  - **9. Campos de auto e imóvel**: poucos clientes. Os campos (dados do veículo, endereço do imóvel)
    ainda precisam ser levantados com o Lohrel.
  - **10. Acabamento visual**: cores e logo da corretora, menu, painel inicial e celular. Veja
    [docs/frontend.md](docs/frontend.md).

## Decisões do escritório que valem para as próximas etapas

- Uma pessoa costuma estar em mais de um plano (ex.: saúde e dental), e o dependente pode estar em um
  ou nos dois planos do titular.
- Cada plano de uma operadora é um contrato próprio, com o nome do plano em "Produto/plano".
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
