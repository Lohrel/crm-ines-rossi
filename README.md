# CRM para corretora de seguros

Sistema web para uma corretora de seguros (vida, saúde, dental, auto e imóvel) centralizar a carteira de clientes: apólices, beneficiários, movimentações de inclusão e exclusão, pendências e a planilha mensal de inclusões.

> Este repositório contém **apenas código**. Nenhum dado real de clientes, planilha, backup ou senha é versionado (veja `.gitignore`). Os testes usam dados fictícios.

## Tecnologias

| Camada | Escolha |
|---|---|
| Backend | Python 3.12 + Django 5.2 LTS |
| Banco de dados | PostgreSQL 16 |
| Interface | Templates do Django + Bootstrap 5 (HTMX nas próximas etapas) |
| Servidor | Docker Compose: Gunicorn, Caddy (HTTPS) e PostgreSQL |
| Backup | `pg_dump` e anexos, diários, criptografados com GPG (AES-256), retenção 7/4/12 |
| Qualidade | pytest, ruff e GitHub Actions |

## Etapas

Cada etapa só começa quando a anterior está testada e em uso.

- [x] **0. Fundação**: login por usuário, HTTPS, backup diário, testes automáticos
- [x] **1.** Clientes, seguradoras, ramos e apólices
  - [x] 1a. Clientes: pessoa física e empresas com unidades (CNPJ por filial) e contatos
  - [x] 1b. Seguradoras, ramos e contratos (vencimento da fatura, boleto pela corretora, coparticipação, filiais cobertas)
- [x] **2.** Beneficiários (titulares e dependentes, cada um nos planos escolhidos), anexos como DPS e eSocial, e número de vidas por grupo, filial e contrato
- [x] **3.** Movimentações de inclusão e exclusão: etapas até a carteirinha enviada, rejeição com motivo e nova inclusão, dia de fechamento por contrato
- [x] **4.** Boletos a enviar: lembrete dos boletos que a corretora envia, geração das mensalidades de um mês ou do ano todo, pré e pós-pagamento, boleto fora do vencimento, reajuste e coparticipação
- [ ] **5.** Pendências com "marcar como concluído"
- [ ] **6.** Importação e exportação da planilha mensal de inclusão
- [ ] **7.** Painel e relatórios
- [ ] **8.** Campos específicos de auto e imóvel
- [ ] **9.** Acabamento visual: cores e logo da corretora, menu, painel inicial e ajustes para celular

Até a etapa 9, cada tela usa o visual padrão do Bootstrap. Problemas de uso encontrados nos testes são corrigidos na própria etapa.

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

## Estrutura

```
config/          Configurações do Django (lidas do arquivo .env)
contas/          Usuários, login e página inicial
clientes/        Clientes PF/PJ, unidades (filiais) e contatos, com histórico
apolices/        Seguradoras, ramos e contratos
beneficiarios/   Titulares, dependentes, planos de cada pessoa, anexos e contagem de vidas
movimentacoes/   Pedidos de inclusão e exclusão, com etapas, fechamento do mês e histórico
boletos/         Boletos que a corretora envia: a enviar, enviados e fora do vencimento
templates/       Layout base e tela de login
static/          Bootstrap servido localmente (funciona sem internet) e campos de data
docker/          Entrypoint, Caddy (HTTPS) e scripts de backup/restauração
```
