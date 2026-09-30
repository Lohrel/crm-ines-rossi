# Telas (front end)

Guia para quem for mexer nas telas, inclusive na etapa 10 (acabamento visual). As regras gerais do
projeto estão no [CLAUDE.md](../CLAUDE.md).

## Como as telas são feitas

- Templates do Django. O layout comum é `templates/base.html`: barra de menu, mensagens e o bloco
  `conteudo` (o título da aba vem do bloco `titulo`). Cada app guarda os seus em
  `<app>/templates/<app>/`.
- Bootstrap 5.3 servido pelo próprio sistema (`static/vendor/bootstrap/`), sem CDN: o servidor fica
  na rede do escritório e as telas têm que funcionar sem internet.
- As cores, a fonte e a organização dos textos ficam em `static/css/crm.css`, carregado depois do
  Bootstrap. Ele redefine as variáveis do tema (`--bs-primary` e afins) e as cores que o Bootstrap
  fixa em cada componente (botões, campos, paginação); não edite o CSS do Bootstrap. A fonte
  Montserrat fica em `static/fonts/montserrat/`, com a licença (SIL OFL), e os logos e o ícone da
  aba, em `static/img/`.
- Os itens do menu ficam em `contas/menu.py`. O item da página aberta é marcado pelo app da URL: os
  beneficiários ficam em Clientes e as seguradoras em Contratos.
- O único JavaScript próprio é `static/js/campos-data.js`, dos campos de data e de mês. O HTMX
  estava previsto, mas ainda não é usado: as telas são páginas normais com formulários.
- As mensagens do Django viram alertas do Bootstrap (`MESSAGE_TAGS` troca `error` por `danger`).
- A validação é feita no servidor: os formulários usam `novalidate`, e os erros aparecem em
  `.invalid-feedback d-block`, com o campo marcado `is-invalid` pelo `BootstrapFormMixin`.

## Padrões em uso

As telas novas seguem o que já existe:

| Elemento | Como é feito |
|---|---|
| Cores | marinho `#1E2242` (`--crm-marinho`) é a cor principal: menu, botões, títulos e links. O vermelho da marca (`#E62A2B`) fica só no logo e em detalhes finos, nunca em botões, porque no sistema vermelho quer dizer excluir ou vencido. Os avisos usam `--crm-alerta` (`#D42426`), mais legível em letra pequena |
| Texto | Montserrat nos títulos, no menu, nos cabeçalhos dos quadros e no caminho; o resto na fonte do sistema. Rótulos dos campos pequenos, em seminegrito e sem dois pontos; ajuda menor e em cinza; cabeçalho das tabelas pequeno, em maiúsculas; nas páginas de detalhe (`dl.row`), o nome do campo discreto e o valor em destaque |
| Links | nomes nas tabelas, caminho e títulos sem sublinhado, que aparece ao passar o mouse; no meio de um texto, continuam sublinhados |
| Título da página | `<h1 class="h3">`, com uma linha `.text-body-secondary` embaixo quando precisa |
| Caminho | `breadcrumb` nas páginas que ficam dentro de um cliente (cliente › contrato › ...) |
| Blocos | `card shadow-sm mb-4`, com `card-header fw-semibold` |
| Tabelas | `table table-sm align-middle` dentro de `.table-responsive`, cabeçalho `table-light` |
| Botões | ação principal `btn-primary`; as demais `btn-outline-primary` ou `btn-outline-secondary`; vermelho só para excluir |
| Prazos | vencido em vermelho e perto de vencer em amarelo (boletos: 7 dias; pendências: 3 dias), com o texto de `clientes/prazos.py` ("vence em 3 dias") |
| Formulários | cadastros e edições usam o `FormularioMixin` (`clientes/views.py`), com a tela comum `clientes/formulario.html`; os campos saem de `clientes/_campos.html`, com asterisco vermelho nos obrigatórios. Nas listas de escolha, a opção vazia é "Escolha" (o `BootstrapFormMixin` troca o "---------" do Django). Botão ao lado de campos com rótulo: ponha em cima dele um `<div class="form-label invisible" aria-hidden="true">.</div>`, da altura do rótulo |
| Selos de movimentação | Inclusão em marinho, Alteração de plano em marinho claro e Exclusão com contorno escuro (`movimentacoes/_tipo.html`) |
| Datas e meses | `CampoData` e `MesField`: a barra entra sozinha, o primeiro clique seleciona a data inteira (para digitar por cima) e há um botão de calendário |
| Exclusão | caixa `<details>` "Excluir registros" no fim da página, à direita, e página de confirmação digitada (`ExclusaoConfirmadaView` com `clientes/excluir.html`) |
| Importação | prévia de cada linha antes de gravar; se a prévia tem um campo de texto, o primeiro botão do formulário (escondido) só atualiza a prévia, para o Enter nunca confirmar |

O escritório valoriza economizar digitação e cliques. Atalhos que já abrem o formulário certo são
bem-vindos, como "Nova pendência" dentro do cliente ou "preencher" o salário na linha do plano.

## Onde fica cada tela

O menu (`contas/menu.py`) tem Clientes, Contratos, Movimentações, Boletos e Pendências. Algumas
telas ficam dentro de outras:

- Seguradoras: botão na página de Contratos.
- Beneficiários: botão na página do cliente.
- Planilha mensal (baixar e importar): botão em Movimentações.
- Planilha do seguro de vida: "Planilha de vidas" na tabela de contratos e na Planilha mensal.
- Início (`contas/templates/contas/inicio.html`): hoje só tem atalhos. O painel da etapa 8 entra
  aqui.

## Problemas conhecidos

- **Cache dos arquivos estáticos.** O Caddy serve CSS e JavaScript sem hash no nome, então depois de
  uma mudança é preciso recarregar com Ctrl+Shift+R. O `ManifestStaticFilesStorage` do Django
  resolve isso (o `collectstatic` já roda no `docker/entrypoint.sh`).

## Etapa 10: acabamento visual

Escopo combinado com o escritório: cores e logo da corretora, organização do menu, painel inicial com
o visual final e ajustes para celular. A etapa termina quando a equipe aprova as telas.

**10a (feita).** Entre duas propostas feitas a partir do cartão de visita e dos envelopes da
corretora, o Lohrel escolheu o menu marinho com o logo branco e a tela de entrada escura. Entraram as
cores, a fonte e o logo, o ícone da aba, o menu que recolhe no celular e a organização dos textos
(rótulos, tabelas e páginas de detalhe), que ele pediu para as telas de movimentações e de cadastro.
Na lista de movimentações, o tipo e o plano viraram a coluna "Pedido", o solicitante foi para baixo
do cliente e a carteirinha para baixo da etapa, e a tabela passou a caber na tela.

- Identidade: marinho C100 M93 Y43 K44 (`#1E2242`), vermelho C0 M93 Y84 K0 (`#E62A2B`) e a fonte
  Montserrat. O cartão e os envelopes usam a curva vermelha sobre uma faixa marinho (repetida na tela
  de entrada) e fundos com formas diagonais suaves. Confira o contraste do texto (WCAG AA).
- O logo e o nome da corretora estão no repositório com autorização do Lohrel (30/09/2026). Se o
  software passar a ser proprietário, eles podem sair daqui. Os SVGs foram tirados do arquivo `.ai`
  do envelope; os originais (cartão e envelopes) não vão para o repositório.

Falta:

- Menu: reorganizar com o Lohrel, incluindo "Relatórios" se a etapa 8 criar esse item.
- Painel inicial com o visual final, depois da etapa 8.
- Celular: nenhuma tela rola mais para o lado a 390 px, mas os filtros ocupam a primeira tela e, nas
  tabelas largas (que rolam dentro de `.table-responsive`), os botões da última coluna (ex.: "Enviado
  hoje", "Concluir") ficam escondidos à direita.
- Nesta etapa muda só a aparência, não o comportamento: os testes existentes continuam passando.

## Conferir as telas

Use um navegador headless (Playwright com Chromium) e dados fictícios:

- tire capturas a 1280 px e a 390 px de largura;
- no celular, `document.documentElement.scrollWidth` maior que a largura da janela indica rolagem
  lateral;
- na importação da planilha do seguro de vida (`beneficiarios/importar_vidas.html`), o botão
  escondido tem o mesmo texto de um botão visível: procure pelo texto e pela classe (ex.:
  `button.btn-outline-primary:has-text("Atualizar prévia")`);
- capturas com dados reais nunca vão para o repositório nem para o chat.
