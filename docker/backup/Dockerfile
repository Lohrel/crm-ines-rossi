# A imagem oficial do PostgreSQL já inclui pg_dump, pg_restore e gpg.
FROM postgres:16

COPY agendador.sh fazer-backup.sh restaurar.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/agendador.sh /usr/local/bin/fazer-backup.sh /usr/local/bin/restaurar.sh

ENTRYPOINT ["/usr/local/bin/agendador.sh"]
