#!/bin/bash
# Restaura um backup do banco e, se existir, o dos anexos feito no mesmo horário.
# ATENÇÃO: substitui os dados atuais.
# Uso: docker compose exec backup restaurar.sh diario/crm_AAAA-MM-DD_HHMM.dump.gpg
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no arquivo .env}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

arquivo="${BACKUP_DIR:-/backups}/${1:?Informe o arquivo, ex.: diario/crm_2026-01-01_0200.dump.gpg}"
[[ -f "${arquivo}" ]] || { echo "Arquivo não encontrado: ${arquivo}" >&2; exit 1; }

descriptografar() {
    gpg --batch --quiet --decrypt --passphrase-fd 3 "$1" 3<<<"${BACKUP_PASSPHRASE}"
}

descriptografar "${arquivo}" \
    | pg_restore --clean --if-exists --no-owner --host="${POSTGRES_HOST}" \
                 --port="${POSTGRES_PORT:-5432}" --username="${POSTGRES_USER}" \
                 --dbname="${POSTGRES_DB}"
echo "Banco restaurado: ${1}"

anexos="${arquivo%.dump.gpg}_anexos.tar.gpg"
destino="${ANEXOS_DIR:-/anexos}"
if [[ -f "${anexos}" ]]; then
    # Confere o arquivo inteiro antes de apagar os anexos atuais.
    temporario="$(mktemp)"
    trap 'rm -f "${temporario}"' EXIT
    descriptografar "${anexos}" > "${temporario}"
    tar --list --file="${temporario}" > /dev/null
    find "${destino}" -mindepth 1 -delete
    tar --extract --numeric-owner --same-owner --file="${temporario}" --directory="${destino}"
    echo "Anexos restaurados: ${anexos#"${BACKUP_DIR:-/backups}"/}"
else
    echo "AVISO: não há backup de anexos deste horário (${anexos##*/}). Os anexos atuais foram mantidos."
fi
