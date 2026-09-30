# Telas (front end)

Guia para quem for mexer nas telas, inclusive na etapa 10 (acabamento visual). As regras gerais do
projeto estão no [CLAUDE.md](../CLAUDE.md).

## Como as telas são feitas

- Templates do Django. O layout comum é `templates/base.html`: barra de menu, mensagens e o bloco
  `conteudo` (o título da aba vem do bloco `titulo`). Cada app guarda os seus em
  `<app>/templates/<app>/`.
- Bootstrap 5.3 servido pelo próprio sistema (`static/vendor/bootstrap/`), sem CDN: o servidor fica
  na rede do escritório e as telas têm que funcionar sem internet.
- O único JavaScript próprio é `static/js/campos-data.js`, dos campos de data e de mês. O HTMX
  estava previsto, mas ainda não é usado: as telas são páginas normais com formulários.
- As mensagens do Django viram alertas do Bootstrap (`MESSAGE_TAGS` troca `error` por `danger`).
- A validação é feita no servidor: os formulários usam `novalidate`, e os erros aparecem em
  `.invalid-feedback d-block`, com o campo marcado `is-invalid` pelo `BootstrapFormMixin`.

## Padrões em uso

Até a etapa 10, as telas novas seguem o que já existe:

| Elemento | Como é feito |
|---|---|
| Título da página | `<h1 class="h3">`, com uma linha `.text-body-secondary` embaixo quando precisa |
| Caminho | `breadcrumb` nas páginas que ficam dentro de um cliente (cliente › contrato › ...) |
| Blocos | `card shadow-sm mb-4`, com `card-header fw-semibold` |
| Tabelas | `table table-sm align-middle` dentro de `.table-responsive`, cabeçalho `table-light` |
| Botões | ação principal `btn-primary`; as demais `btn-outline-primary` ou `btn-outline-secondary`; vermelho só para excluir |
| Prazos | vencido em vermelho e perto de vencer em amarelo (boletos: 7 dias; pendências: 3 dias), com o texto de `clientes/prazos.py` ("vence em 3 dias") |
| Formulários | cadastros e edições usam o `FormularioMixin` (`clientes/views.py`), com a tela comum `clientes/formulario.html`; os campos saem de `clientes/_campos.html`, com asterisco vermelho nos obrigatórios |
| Datas e meses | `CampoData` e `MesField`: a barra entra sozinha, o primeiro clique seleciona a data inteira (para digitar por cima) e há um botão de calendário |
| Exclusão | caixa `<details>` "Excluir registros" no fim da página, à direita, e página de confirmação digitada (`ExclusaoConfirmadaView` com `clientes/excluir.html`) |
| Importação | prévia de cada linha antes de gravar; se a prévia tem um campo de texto, o primeiro botão do formulário (escondido) só atualiza a prévia, para o Enter nunca confirmar |

O escritório valoriza economizar digitação e cliques. Atalhos que já abrem o formulário certo são
bem-vindos, como "Nova pendência" dentro do cliente ou "preencher" o salário na linha do plano.

## Onde fica cada tela

O menu tem Clientes, Contratos, Movimentações, Boletos e Pendências. Algumas telas ficam dentro de
outras:

- Seguradoras: botão na página de Contratos.
- Beneficiários: botão na página do cliente.
- Planilha mensal (baixar e importar): botão em Movimentações.
- Planilha do seguro de vida: "Planilha de vidas" na tabela de contratos e na Planilha mensal.
- Início (`contas/templates/contas/inicio.html`): hoje só tem atalhos. O painel da etapa 8 entra
  aqui.

## Problemas conhecidos

- **Menu no celular.** A barra usa `navbar-expand`, que nunca recolhe, e na largura de celular a
  página inteira rola para o lado. A correção é `navbar-expand-lg` com o botão `navbar-toggler` e o
  menu dentro de um `collapse`.
- **Cache dos arquivos estáticos.** O Caddy serve CSS e JavaScript sem hash no nome, então depois de
  uma mudança é preciso recarregar com Ctrl+Shift+R. O `ManifestStaticFilesStorage` do Django
  resolve isso (o `collectstatic` já roda no `docker/entrypoint.sh`).

## Etapa 10: acabamento visual

Escopo combinado com o escritório: cores e logo da corretora, organização do menu, painel inicial com
o visual final e ajustes para celular. A etapa termina quando a equipe aprova as telas.

- Peça ao Lohrel os arquivos do logo e as cores da corretora. O repositório é público: confirme com
  ele antes de versionar o logo ou pôr o nome da corretora nas telas. Hoje o sistema aparece como
  "CRM Corretora".
- Cores: prefira um `static/css/crm.css`, carregado depois do Bootstrap, que redefine as variáveis
  do tema (`--bs-primary` e afins), em vez de editar o CSS do Bootstrap. Confira o contraste do
  texto (WCAG AA).
- Menu: reorganize com o Lohrel, incluindo "Relatórios" se a etapa 8 criar esse item.
- Celular: corrija o menu primeiro e depois confira cada tela a 390 px sem rolagem lateral. Tabelas
  largas continuam dentro de `.table-responsive`.
- Tela de login e ícone da aba (favicon) com o logo.
- Nesta etapa muda só a aparência, não o comportamento: os testes existentes continuam passando.

## Conferir as telas

Use um navegador headless (Playwright com Chromium) e dados fictícios:

- tire capturas a 1280 px e a 390 px de largura;
- no celular, `document.documentElement.scrollWidth` maior que a largura da janela indica rolagem
  lateral;
- na importação da planilha do seguro de vida (PR #11), o botão escondido tem o mesmo texto de um
  botão visível: procure pelo texto e pela classe (ex.:
  `button.btn-outline-primary:has-text("Atualizar prévia")`);
- capturas com dados reais nunca vão para o repositório nem para o chat.
