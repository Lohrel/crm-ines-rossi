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
| Backup | `pg_dump` diário, criptografado com GPG (AES-256), retenção 7/4/12 |
| Qualidade | pytest, ruff e GitHub Actions |

## Etapas

Cada etapa só começa quando a anterior está testada e em uso.

- [x] **0. Fundação**: login por usuário, HTTPS, backup diário, testes automáticos
- [ ] **1.** Clientes, seguradoras, ramos e apólices
- [ ] **2.** Beneficiários (titulares e dependentes)
- [ ] **3.** Movimentações de inclusão e exclusão, com solicitante, executor e datas
- [ ] **4.** Pendências com "marcar como concluído"
- [ ] **5.** Importação e exportação da planilha mensal de inclusão
- [ ] **6.** Painel e relatórios
- [ ] **7.** Campos específicos de auto e imóvel

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
templates/       Layout base e tela de login
static/vendor/   Bootstrap servido localmente (funciona sem internet)
docker/          Entrypoint, Caddy (HTTPS) e scripts de backup/restauração
```
