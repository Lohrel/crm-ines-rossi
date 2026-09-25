# Instalação no servidor do escritório

O CRM roda em **um** computador que fica sempre ligado (o servidor). Os demais computadores só abrem o navegador.

## 1. Preparar o servidor

Recomendado: um mini PC com **Ubuntu Server 24.04 LTS**, cabo de rede e nobreak.

1. Instale o Docker: <https://docs.docker.com/engine/install/ubuntu/>
2. Dê ao servidor um **IP fixo** na rede (no roteador, reserve o IP pelo endereço MAC).
3. Instale o Git e baixe o projeto:

   ```bash
   git clone https://github.com/Lohrel/crm-ines-rossi.git
   cd crm-ines-rossi
   ```

## 2. Configurar o arquivo `.env`

```bash
cp .env.example .env
nano .env
```

Preencha:

- `DJANGO_SECRET_KEY`: gere com `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `POSTGRES_PASSWORD`: uma senha longa.
- `BACKUP_PASSPHRASE`: uma senha longa **diferente**. Guarde-a também num gerenciador de senhas fora do servidor: sem ela os backups não abrem.
- `CRM_HOSTNAME`, `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS`: o nome usado para acessar o sistema (ex.: `crm.local`).

Proteja o arquivo: `chmod 600 .env`.

## 3. Subir o sistema

```bash
docker compose up -d --build
docker compose ps          # todos devem aparecer "Up" / "healthy"
```

Crie o usuário administrador (o seu):

```bash
docker compose exec web python manage.py createsuperuser
```

Os outros funcionários são criados pelo administrador em `https://crm.local/admin/`, **um usuário por pessoa**.

## 4. Configurar os 4 computadores

1. **Nome do servidor.** Cada computador precisa saber que `crm.local` é o IP do servidor. A forma mais simples é criar no roteador uma entrada de DNS local. Se o roteador não permitir, adicione uma linha no arquivo `C:\Windows\System32\drivers\etc\hosts` de cada PC (como administrador):

   ```
   192.168.0.10   crm.local
   ```

   (troque pelo IP fixo do servidor)

2. **Certificado HTTPS.** O Caddy cria um certificado próprio do escritório. Para o navegador confiar nele, copie o certificado raiz do servidor:

   ```bash
   docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./crm-raiz.crt
   ```

   Em cada PC Windows: dê dois cliques em `crm-raiz.crt` → **Instalar certificado** → **Máquina local** → **Autoridades de Certificação Raiz Confiáveis**. Depois apague a cópia do arquivo.

3. Abra `https://crm.local` e crie um favorito.

## 5. Acesso de fora do escritório (Tailscale)

1. Instale o Tailscale no servidor e no aparelho remoto, na mesma conta (com verificação em duas etapas ativada).
2. Adicione o nome do servidor no Tailscale (ex.: `servidor.seu-tailnet.ts.net`) ao `.env`:

   ```
   CRM_HOSTNAME=crm.local, servidor.seu-tailnet.ts.net
   DJANGO_ALLOWED_HOSTS=crm.local,servidor.seu-tailnet.ts.net
   DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.local,https://servidor.seu-tailnet.ts.net
   ```

3. `docker compose up -d` para aplicar. Nenhuma porta do roteador precisa ser aberta.

## 6. Backups

- O backup roda sozinho todo dia no horário `BACKUP_TIME` e fica na pasta `backups/` do servidor:
  - `diario/`: últimos 7 dias
  - `semanal/`: últimos 4 domingos
  - `mensal/`: últimos 12 meses (dia 1)
- Os arquivos são criptografados (`.dump.gpg`). Sem a `BACKUP_PASSPHRASE` ninguém consegue abri-los.

**Cópias fora do servidor (obrigatório):**

- Toda semana, copie a pasta `backups/` para um HD externo que fica guardado fora do servidor.
- Configure uma cópia automática para a nuvem (ex.: `rclone` para Backblaze B2 ou Google Drive). Como os arquivos já saem criptografados, a nuvem não vê os dados.

**Fazer um backup agora:**

```bash
docker compose exec backup fazer-backup.sh
```

**Ver se os backups estão rodando:**

```bash
docker compose logs backup
ls -lh backups/diario
```

## 7. Teste de restauração (todo mês)

Backup que nunca foi restaurado não é garantia. Uma vez por mês, restaure o backup mais recente **numa máquina de teste** (não no servidor em uso), seguindo os passos 1 a 3 com o mesmo `.env`, e depois:

```bash
# copie o arquivo para a pasta backups/ da máquina de teste e rode:
docker compose exec backup restaurar.sh diario/crm_AAAA-MM-DD_HHMM.dump.gpg
```

Abra o sistema e confira se os dados estão lá.

> ⚠️ `restaurar.sh` **substitui** os dados do banco. No servidor em uso, só rode em caso de perda de dados.

## 8. Atualizar o sistema

```bash
git pull
docker compose up -d --build
```

As migrações do banco são aplicadas automaticamente ao iniciar.

Uma vez por mês, atualize também o sistema operacional (`sudo apt update && sudo apt upgrade`) e as imagens (`docker compose pull`).
