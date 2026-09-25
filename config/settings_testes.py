"""Configurações usadas pelos testes automáticos.

Define valores padrão para rodar os testes sem arquivo .env.
Variáveis de ambiente já definidas (ex.: no GitHub Actions) têm prioridade.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "chave-apenas-para-testes")
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("POSTGRES_DB", "crm")
os.environ.setdefault("POSTGRES_USER", "crm")
os.environ.setdefault("POSTGRES_PASSWORD", "crm")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from config.settings import *  # noqa: E402, F403
