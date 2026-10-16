#!/bin/bash
# Faz um backup criptografado do banco e dos anexos e aplica a política de retenção:
# 7 diários, 4 semanais (domingo) e 12 mensais (dia 1).
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no arquivo .env}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

DESTINO="${BACKUP_DIR:-/backups}"
mkdir -p "${DESTINO}/diario" "${DESTINO}/semanal" "${DESTINO}/mensal"

ANEXOS="${ANEXOS_DIR:-/anexos}"
base="crm_$(date +%Y-%m-%d_%H%M)"

# Arquivo em andamento: se o backup falhar no meio, ele é apagado, para não ocupar o disco.
parcial=""
trap '[[ -z "${parcial}" ]] || rm -f "${parcial}"' EXIT

criptografar() {
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-fd 3 --output "$1" 3<<<"${BACKUP_PASSPHRASE}"
}

descriptografar() {
    gpg --batch --quiet --decrypt --passphrase-fd 3 "$1" 3<<<"${BACKUP_PASSPHRASE}"
}

# Abre o arquivo criptografado inteiro (o gpg recusa um arquivo cortado ou alterado) e lê o
# conteúdo, para nunca publicar um backup que não restaura.
conferir_banco() {
    descriptografar "$1" | { pg_restore --list > /dev/null && cat > /dev/null; }
}

conferir_anexos() {
    descriptografar "$1" | tar --list > /dev/null
}

# Só vira backup "oficial" depois de completo e conferido.
publicar() {
    local nome="$1"
    mv "${parcial}" "${DESTINO}/diario/${nome}"
    parcial=""
    echo "Backup criado: diario/${nome}"
    if [[ "$(date +%u)" == "7" ]]; then
        cp "${DESTINO}/diario/${nome}" "${DESTINO}/semanal/${nome}"
    fi
    if [[ "$(date +%d)" == "01" ]]; then
        cp "${DESTINO}/diario/${nome}" "${DESTINO}/mensal/${nome}"
    fi
}

banco="${base}.dump.gpg"
parcial="${DESTINO}/.${banco}.parcial"
pg_dump --format=custom --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT:-5432}" \
        --username="${POSTGRES_USER}" "${POSTGRES_DB}" \
    | criptografar "${parcial}"
conferir_banco "${parcial}"
publicar "${banco}"

# Anexos (DPS, eSocial, documentos de clientes e seguradoras): mesma senha do banco.
anexos="${base}_anexos.tar.gpg"
parcial="${DESTINO}/.${anexos}.parcial"
tar --create --numeric-owner --directory="${ANEXOS}" . \
    | criptografar "${parcial}"
conferir_anexos "${parcial}"
publicar "${anexos}"

manter_mais_recentes() {
    local pasta="$1" quantidade="$2" padrao
    for padrao in '*.dump.gpg' '*_anexos.tar.gpg'; do
        find "${pasta}" -maxdepth 1 -name "${padrao}" -printf '%T@ %p\n' \
            | sort -rn | tail -n +"$(( quantidade + 1 ))" | cut -d' ' -f2- | xargs -r rm -f
    done
}
manter_mais_recentes "${DESTINO}/diario" 7
manter_mais_recentes "${DESTINO}/semanal" 4
manter_mais_recentes "${DESTINO}/mensal" 12
