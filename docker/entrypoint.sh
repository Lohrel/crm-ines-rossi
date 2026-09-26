#!/bin/sh
# Prepara o sistema antes de iniciar: aplica as migrações do banco
# e copia os arquivos estáticos para o Caddy servir.
set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear -v 0

exec "$@"
