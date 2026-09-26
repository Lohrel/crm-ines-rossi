#!/bin/bash
# Faz um backup criptografado do banco e aplica a política de retenção:
# 7 diários, 4 semanais (domingo) e 12 mensais (dia 1).
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no arquivo .env}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

DESTINO="${BACKUP_DIR:-/backups}"
mkdir -p "${DESTINO}/diario" "${DESTINO}/semanal" "${DESTINO}/mensal"

nome="crm_$(date +%Y-%m-%d_%H%M).dump.gpg"
temporario="${DESTINO}/.${nome}.parcial"

pg_dump --format=custom --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT:-5432}" \
        --username="${POSTGRES_USER}" "${POSTGRES_DB}" \
    | gpg --batch --yes --symmetric --cipher-algo AES256 \
          --passphrase-fd 3 --output "${temporario}" 3<<<"${BACKUP_PASSPHRASE}"

# Só vira backup "oficial" depois de completo.
mv "${temporario}" "${DESTINO}/diario/${nome}"
echo "Backup criado: diario/${nome}"

if [[ "$(date +%u)" == "7" ]]; then
    cp "${DESTINO}/diario/${nome}" "${DESTINO}/semanal/${nome}"
fi
if [[ "$(date +%d)" == "01" ]]; then
    cp "${DESTINO}/diario/${nome}" "${DESTINO}/mensal/${nome}"
fi

manter_mais_recentes() {
    local pasta="$1" quantidade="$2"
    find "${pasta}" -maxdepth 1 -name '*.dump.gpg' -printf '%T@ %p\n' \
        | sort -rn | tail -n +"$(( quantidade + 1 ))" | cut -d' ' -f2- | xargs -r rm -f
}
manter_mais_recentes "${DESTINO}/diario" 7
manter_mais_recentes "${DESTINO}/semanal" 4
manter_mais_recentes "${DESTINO}/mensal" 12
