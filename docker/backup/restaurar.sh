#!/bin/bash
# Restaura um backup no banco. ATENÇÃO: substitui os dados atuais.
# Uso: docker compose exec backup restaurar.sh diario/crm_AAAA-MM-DD_HHMM.dump.gpg
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no arquivo .env}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

arquivo="${BACKUP_DIR:-/backups}/${1:?Informe o arquivo, ex.: diario/crm_2026-01-01_0200.dump.gpg}"
[[ -f "${arquivo}" ]] || { echo "Arquivo não encontrado: ${arquivo}" >&2; exit 1; }

gpg --batch --quiet --decrypt --passphrase-fd 3 "${arquivo}" 3<<<"${BACKUP_PASSPHRASE}" \
    | pg_restore --clean --if-exists --no-owner --host="${POSTGRES_HOST}" \
                 --port="${POSTGRES_PORT:-5432}" --username="${POSTGRES_USER}" \
                 --dbname="${POSTGRES_DB}"

echo "Backup restaurado: ${1}"
