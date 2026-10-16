#!/bin/bash
# Restaura um backup do banco e, se existir, o dos anexos feito no mesmo horário.
# ATENÇÃO: substitui os dados atuais.
# Uso: docker compose exec backup restaurar.sh diario/crm_AAAA-MM-DD_HHMM.dump.gpg
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no arquivo .env}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

arquivo="${BACKUP_DIR:-/backups}/${1:?Informe o arquivo, ex.: diario/crm_2026-01-01_0200.dump.gpg}"
[[ -f "${arquivo}" ]] || { echo "Arquivo não encontrado: ${arquivo}" >&2; exit 1; }
anexos="${arquivo%.dump.gpg}_anexos.tar.gpg"
destino="${ANEXOS_DIR:-/anexos}"

descriptografar() {
    gpg --batch --quiet --decrypt --passphrase-fd 3 "$1" 3<<<"${BACKUP_PASSPHRASE}"
}

recusar() {
    echo "ERRO: $1 Nenhum dado foi alterado." >&2
    exit 1
}

temporaria="$(mktemp -d)"
trap 'rm -rf "${temporaria}"' EXIT

# 1. Abre e confere os dois arquivos inteiros antes de mexer em qualquer dado: um backup
#    cortado (ex.: cópia interrompida para o HD externo) ou estragado não pode apagar o banco.
echo "Conferindo o backup..."
if ! descriptografar "${arquivo}" > "${temporaria}/banco.dump" \
    || ! pg_restore --list "${temporaria}/banco.dump" > /dev/null; then
    recusar "o backup do banco (${1}) está incompleto ou estragado, ou a senha está errada."
fi
if [[ -f "${anexos}" ]]; then
    if ! descriptografar "${anexos}" > "${temporaria}/anexos.tar" \
        || ! tar --list --file="${temporaria}/anexos.tar" > /dev/null; then
        recusar "o backup dos anexos (${anexos##*/}) está incompleto ou estragado."
    fi
fi

# 2. O banco é restaurado numa transação só: se algo falhar no meio, ele fica como estava.
pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error \
           --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT:-5432}" \
           --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" "${temporaria}/banco.dump"
echo "Banco restaurado: ${1}"

# 3. Os anexos, já conferidos, substituem os atuais.
if [[ -f "${temporaria}/anexos.tar" ]]; then
    find "${destino}" -mindepth 1 -delete
    tar --extract --numeric-owner --same-owner --file="${temporaria}/anexos.tar" \
        --directory="${destino}"
    echo "Anexos restaurados: ${anexos#"${BACKUP_DIR:-/backups}"/}"
else
    echo "AVISO: não há backup de anexos deste horário (${anexos##*/}). Os anexos atuais foram mantidos."
fi
