# CRM para corretora de seguros

Sistema web para uma corretora de seguros (vida, saúde, dental, auto e imóvel) centralizar a carteira de clientes: apólices, beneficiários, movimentações de inclusão, exclusão e alteração de plano, pendências e a planilha mensal de inclusões.

> Este repositório contém **apenas código**. Nenhum dado real de clientes, planilha, backup ou senha é versionado (veja `.gitignore`). Os testes usam dados fictícios.

## Tecnologias

| Camada | Escolha |
|---|---|
| Backend | Python 3.12 + Django 5.2 LTS |
| Banco de dados | PostgreSQL 16 |
| Interface | Templates do Django + Bootstrap 5 (HTMX nas próximas etapas) |
| Servidor | Docker Compose: Gunicorn, Caddy (HTTPS) e PostgreSQL |
| Backup | `pg_dump` e anexos, diários, criptografados com GPG (AES-256), retenção 7/4/12 |
| Planilhas | openpyxl (arquivos do Excel), com defusedxml protegendo a leitura |
| Qualidade | pytest, ruff e GitHub Actions |

## Etapas

Cada etapa só começa quando a anterior está testada e em uso.

- [x] **0. Fundação**: login por usuário, HTTPS, backup diário, testes automáticos
- [x] **1.** Clientes, seguradoras, ramos e apólices
  - [x] 1a. Clientes: pessoa física e empresas com unidades (CNPJ por filial) e contatos
  - [x] 1b. Seguradoras, ramos e contratos (vencimento da fatura, boleto pela corretora, coparticipação, filiais cobertas)
- [x] **2.** Beneficiários (titulares e dependentes, cada um nos planos escolhidos), anexos como DPS e eSocial, e número de vidas por grupo, filial e contrato
- [x] **3.** Movimentações de inclusão e exclusão: etapas até a carteirinha enviada, rejeição com motivo e nova inclusão, dia de fechamento por contrato
- [x] **4.** Boletos a enviar: lembrete dos boletos que a corretora envia, geração das mensalidades de um mês ou do ano todo, boleto fora do vencimento, reajuste e coparticipação
- [x] **5.** Pendências do dia a dia: responsável, prazo e "marcar como concluída", sempre ligadas ao cliente e, nas empresas, à filial
- [x] **6.** Planilha mensal de inclusões, no formato da planilha de controle do escritório
  - [x] 6a. Baixar a planilha do mês (uma aba por ramo, com o plano de cada pessoa, e a aba de alterações de plano) e a movimentação "Alteração de plano"
  - [x] 6b. Importar a planilha do mês, com prévia de cada linha antes de gravar: titular novo entra com nome e matrícula, e o pedido em aberto que a planilha dá como Processado avança
- [x] **7.** Planilha do seguro de vida, no layout que vai para a Tokio Marine
  - [x] 7a. Salário (opcional) no plano de vida, capital e taxa no contrato, subfatura de cada filial e a planilha do mês, com o resumo da fatura para conferir a cobrança
  - [x] 7b. Importar a planilha atual da seguradora, com prévia de cada vida: pessoas, salários e subfaturas entram de uma vez, e o capital e a fatura de cada vida são conferidos com o contrato
- [ ] **8.** Painel e relatórios
- [ ] **9.** Campos específicos de auto e imóvel
- [ ] **10.** Acabamento visual: cores e logo da corretora, menu, painel inicial e ajustes para celular

Até a etapa 10, cada tela usa o visual padrão do Bootstrap. Problemas de uso encontrados nos testes são corrigidos na própria etapa.

## Instalar no servidor do escritório

Veja o passo a passo em [docs/instalacao.md](docs/instalacao.md).

## Desenvolver localmente

Pré-requisitos: Python 3.11+ e um PostgreSQL 16 acessível.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Sem .env, os testes usam banco "crm", usuário "crm" e senha "crm" em localhost.
pytest                              # testes
ruff check . && ruff format .       # estilo
```

Para rodar o sistema completo como no servidor, use o Docker (veja `docs/instalacao.md`).

Quem for continuar o projeto, pessoa ou agente de IA, começa pelo [CLAUDE.md](CLAUDE.md): regras,
convenções e estado atual. As telas estão descritas em [docs/frontend.md](docs/frontend.md), e a
próxima etapa em [docs/etapa-8-painel-e-relatorios.md](docs/etapa-8-painel-e-relatorios.md).

## Estrutura

```
config/          Configurações do Django (lidas do arquivo .env)
contas/          Usuários, login e página inicial
clientes/        Clientes PF/PJ, unidades (filiais) e contatos, com histórico
apolices/        Seguradoras, ramos, contratos e subfaturas das filiais
beneficiarios/   Titulares, dependentes, planos de cada pessoa, anexos, contagem de vidas e a planilha
                 do seguro de vida (baixar e importar)
movimentacoes/   Pedidos de inclusão, exclusão e alteração de plano, com etapas, fechamento do mês,
                 histórico e a planilha mensal (baixar e importar)
boletos/         Boletos que a corretora envia: a enviar, enviados e fora do vencimento
pendencias/      Pendências com responsável e prazo, ligadas ao cliente, filial, contrato ou movimentação
templates/       Layout base e tela de login
static/          Bootstrap servido localmente (funciona sem internet) e campos de data
docker/          Entrypoint, Caddy (HTTPS) e scripts de backup/restauração
```
