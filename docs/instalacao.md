# Instalação no servidor do escritório

O CRM roda em **um** computador que fica sempre ligado (o servidor). Os demais computadores só abrem o navegador.

## 1. Preparar o servidor

Recomendado a longo prazo: um mini PC dedicado com **Ubuntu Server 24.04 LTS**, cabo de rede e nobreak. Para começar, dá para usar um computador **Windows** do escritório (veja [Servidor Windows](#servidor-windows-provisório) no fim deste guia).

1. Instale o Docker: no Ubuntu, <https://docs.docker.com/engine/install/ubuntu/>; no Windows, o [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Dê ao servidor um **IP fixo** na rede (no roteador, reserve o IP pelo endereço MAC).
3. Instale o Git e baixe o projeto (os comandos são iguais no PowerShell do Windows):

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
- Cada backup gera dois arquivos com o mesmo horário: o banco (`.dump.gpg`) e os anexos dos beneficiários, como DPS e eSocial (`_anexos.tar.gpg`). Os dois são criptografados: sem a `BACKUP_PASSPHRASE` ninguém consegue abri-los.
- Os anexos ficam num volume do Docker (`anexos`), fora da pasta pública do site. Só são baixados pela tela do beneficiário, com login.

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

O comando restaura o banco e, logo em seguida, os anexos do mesmo horário (copie os dois arquivos). Abra o sistema e confira se os dados estão lá e se um anexo abre.

> ⚠️ `restaurar.sh` **substitui** os dados do banco e os anexos. No servidor em uso, só rode em caso de perda de dados.

## 8. Atualizar o sistema

```bash
git pull
docker compose up -d --build
```

As migrações do banco são aplicadas automaticamente ao iniciar.

Uma vez por mês, atualize também o sistema operacional (`sudo apt update && sudo apt upgrade`) e as imagens (`docker compose pull`).

## Servidor Windows (provisório)

Enquanto não houver uma máquina dedicada, o sistema pode rodar num PC Windows 10/11 com o Docker Desktop. Tudo acima vale igual; os cuidados extras são:

**Manter o sistema no ar**

- No Docker Desktop, em *Settings → General*, marque **Start Docker Desktop when you sign in to your computer**.
- O Docker Desktop só roda com um usuário **logado** no Windows. Depois de reiniciar, alguém precisa entrar no Windows (pode deixar a tela bloqueada, mas não deslogar).
- Em *Configurações → Sistema → Energia*, coloque **Suspensão: Nunca** quando conectado à energia. Um PC suspenso derruba o CRM para todos.
- Em *Windows Update*, ajuste o **Horário ativo** para o expediente, para o Windows não reiniciar sozinho durante o trabalho.
- Ligue o PC num nobreak, se possível.

**Liberar o acesso dos outros computadores**

- Na primeira vez, o Windows pode perguntar se o Docker pode usar a rede: permita em **Redes privadas**.
- A rede do escritório deve estar marcada como **Privada** (*Configurações → Rede e Internet → propriedades da conexão*).
- Se os outros PCs não conseguirem abrir o sistema, libere as portas 80 e 443 no Firewall do Windows (PowerShell como administrador):

  ```powershell
  New-NetFirewallRule -DisplayName "CRM HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Private
  ```

**Segurança do PC servidor**

- Ative o **BitLocker** no disco (*Configurações → Privacidade e segurança → Criptografia do dispositivo*), porque o banco com dados de saúde fica nele.
- Use uma conta do Windows com senha forte, e não deixe outras pessoas usarem esse PC com a mesma conta.
- A pasta do projeto (com o `.env` e a pasta `backups`) não deve ficar compartilhada na rede.

**Cópia dos backups para o HD externo**

Crie uma tarefa no **Agendador de Tarefas** do Windows que roda todo dia após o horário do backup:

```powershell
robocopy C:\caminho\crm-ines-rossi\backups E:\backups-crm /MIR /R:2 /W:5
```

(troque `C:\caminho\...` pela pasta do projeto e `E:` pela letra do HD externo)

**Mudar para a máquina dedicada depois**

1. Faça um backup agora: `docker compose exec backup fazer-backup.sh`.
2. Instale a máquina nova seguindo os passos 1 a 3 com **o mesmo `.env`**.
3. Copie os dois arquivos do backup (banco e anexos) para a pasta `backups/` da máquina nova e restaure: `docker compose exec backup restaurar.sh diario/<arquivo>.dump.gpg`.
4. Aponte `crm.local` para o IP da máquina nova (roteador ou arquivo `hosts`) e desligue o sistema no PC antigo com `docker compose down`.
