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

# 2. O backup é restaurado num banco novo, vazio, ao lado do atual. Assim ele não esbarra nas
#    tabelas que o sistema ganhou depois do backup (ex.: uma etapa nova), e o banco atual não é
#    tocado até a troca. Se algo falhar, o banco novo é descartado e nada muda.
novo="${POSTGRES_DB}_restaurando"
anterior="${POSTGRES_DB}_antes_da_restauracao"

administrar() {
    psql --quiet --no-psqlrc --set=ON_ERROR_STOP=1 --host="${POSTGRES_HOST}" \
         --port="${POSTGRES_PORT:-5432}" --username="${POSTGRES_USER}" --dbname=postgres "$@"
}

administrar --command="DROP DATABASE IF EXISTS \"${novo}\"" \
            --command="CREATE DATABASE \"${novo}\""
if ! pg_restore --no-owner --single-transaction --exit-on-error \
                --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT:-5432}" \
                --username="${POSTGRES_USER}" --dbname="${novo}" "${temporaria}/banco.dump"; then
    administrar --command="DROP DATABASE IF EXISTS \"${novo}\""
    recusar "o backup do banco não pôde ser restaurado."
fi

# 3. Troca: o banco atual fica guardado como "${anterior}" (o de uma restauração anterior é
#    apagado) e o restaurado passa a ser o do sistema. As duas trocas de nome vão juntas.
administrar --command="DROP DATABASE IF EXISTS \"${anterior}\""
administrar --single-transaction \
    --command="ALTER DATABASE \"${POSTGRES_DB}\" WITH ALLOW_CONNECTIONS false" \
    --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity
               WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid()"
administrar --single-transaction \
    --command="ALTER DATABASE \"${POSTGRES_DB}\" RENAME TO \"${anterior}\"" \
    --command="ALTER DATABASE \"${novo}\" RENAME TO \"${POSTGRES_DB}\""
echo "Banco restaurado: ${1}"
echo "O banco de antes da restauração ficou guardado como ${anterior}."

# 4. Os anexos, já conferidos, substituem os atuais.
if [[ -f "${temporaria}/anexos.tar" ]]; then
    find "${destino}" -mindepth 1 -delete
    tar --extract --numeric-owner --same-owner --file="${temporaria}/anexos.tar" \
        --directory="${destino}"
    echo "Anexos restaurados: ${anexos#"${BACKUP_DIR:-/backups}"/}"
else
    echo "AVISO: não há backup de anexos deste horário (${anexos##*/}). Os anexos atuais foram mantidos."
fi
