#!/bin/bash
# Espera até o horário BACKUP_TIME e faz um backup, todos os dias.
set -euo pipefail

HORARIO="${BACKUP_TIME:-02:00}"
echo "Agendador de backup iniciado. Backup diário às ${HORARIO}."

while true; do
    agora=$(date +%s)
    alvo=$(date -d "today ${HORARIO}" +%s)
    if (( alvo <= agora )); then
        alvo=$(date -d "tomorrow ${HORARIO}" +%s)
    fi
    sleep $(( alvo - agora ))
    fazer-backup.sh || echo "ERRO: o backup de $(date '+%d/%m/%Y %H:%M') falhou." >&2
done
