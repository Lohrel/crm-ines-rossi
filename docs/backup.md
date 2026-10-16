# Backups do CRM

Guia para quem cuida do servidor do escritório. Os comandos são do **PowerShell** do Windows,
rodados na pasta do projeto (troque `C:\CRM\crm-ines-rossi` pela pasta de verdade).

Resumo da rotina:

| Quando | O quê | Quem faz |
|---|---|---|
| Todo dia, 02:00 | Backup do banco e dos anexos na pasta `backups\` do servidor | O sistema, sozinho |
| Todo dia, 03:00 | Cópia dos backups novos para o HD externo | O Agendador de Tarefas do Windows |
| Toda semana | Conferir o registro da cópia e trocar o HD que fica fora do escritório | Uma pessoa |
| Todo mês | Teste de restauração numa máquina de teste | Uma pessoa |

## 1. Como o backup funciona

Todo dia, no horário `BACKUP_TIME` do `.env` (padrão: 02:00), o sistema gera dois arquivos na
pasta `backups\diario\` do projeto, com a data e a hora no nome:

- `crm_2026-10-16_0200.dump.gpg`: o banco de dados inteiro (clientes, contratos, vidas,
  movimentações, histórico, usuários...).
- `crm_2026-10-16_0200_anexos.tar.gpg`: todos os arquivos enviados (DPS, eSocial, documentos de
  clientes e de seguradoras).

**Os dois andam juntos**: para restaurar, sempre copie o par com o mesmo horário.

Cada arquivo é criptografado (AES-256) com a senha `BACKUP_PASSPHRASE` do `.env` e é aberto e
conferido antes de entrar na pasta. Um backup que falha no meio não aparece em `diario\`.

O servidor guarda:

| Pasta | O que tem | Quantos |
|---|---|---|
| `backups\diario\` | um par por dia | os últimos 7 dias |
| `backups\semanal\` | uma cópia de cada domingo | os últimos 4 domingos |
| `backups\mensal\` | uma cópia de cada dia 1º | os últimos 12 meses |

O HD externo guarda mais: veja a seção 4.

## 2. A senha dos backups

Sem a `BACKUP_PASSPHRASE`, **ninguém consegue abrir os backups**, nem nós. Se o servidor queimar
e a senha só estiver no `.env` dele, os backups do HD viram arquivos inúteis.

- Guarde a senha num gerenciador de senhas (ex.: Bitwarden) de quem cuida do sistema.
- Guarde também uma cópia em papel, num envelope lacrado, com a direção da corretora.
- Nunca mande a senha por WhatsApp ou e-mail, e não troque a senha sem avisar: os backups
  antigos continuam precisando da senha antiga.

## 3. Conferir e fazer backup na mão

Ver se o backup de hoje foi feito:

```powershell
dir backups\diario
```

O último par de arquivos tem que ter a data de hoje (ou de ontem, antes das 02:00).

Ver o que o backup disse (erros aparecem aqui):

```powershell
docker compose logs --tail 20 backup
```

Fazer um backup agora (ex.: antes de atualizar o sistema):

```powershell
docker compose exec backup fazer-backup.sh
```

## 4. HD externo no Windows

O servidor sozinho não basta: se o disco dele quebrar, for roubado ou pegar um vírus, os backups
vão junto. Por isso os backups são copiados todo dia para um HD externo.

### 4.1 O ideal: dois HDs que se revezam

Um HD sempre ligado no servidor pode ser estragado pelo mesmo vírus que estragar o servidor. Use
**dois HDs** (A e B):

- Um fica ligado no servidor e recebe a cópia todo dia.
- O outro fica **fora do escritório** (ex.: na casa de quem cuida do sistema).
- Toda semana (ex.: sexta-feira), troque os dois.

Assim, no pior caso, perde-se uma semana. Com um HD só, ainda é muito melhor que nada: comece
com um e compre o segundo depois.

Qualquer HD ou SSD USB de 500 GB sobra por anos: os backups do CRM são pequenos.

### 4.2 Preparar cada HD (uma vez só)

Faça isto em cada HD, um de cada vez:

1. Ligue o HD no servidor.
2. Clique com o botão direito no botão Iniciar e abra **Gerenciamento de disco**.
3. Ache o HD na lista (pelo tamanho). Se ele for novo ou tiver outro formato, clique com o botão
   direito na partição dele, **Formatar...**: sistema de arquivos **NTFS**, rótulo
   `BACKUP-CRM-A` (no outro, `BACKUP-CRM-B`). Formatar apaga o que houver no HD.
4. Clique com o botão direito na partição, **Alterar letra da unidade e caminhos...**, **Alterar**
   e escolha a letra **Z:**. Use a mesma letra Z: nos dois HDs: o Windows lembra a letra de cada
   HD, e a cópia sempre procura o `Z:`.
5. Abra o Explorador de Arquivos e crie no HD a pasta `backups-crm`.

Não é preciso BitLocker no HD: os backups já saem criptografados.

### 4.3 A cópia automática (uma vez só)

O projeto já tem o script que faz a cópia: `docker\backup\windows\copiar-para-o-hd.ps1`. Ele:

- copia para `Z:\backups-crm` os backups novos e refaz uma cópia que tenha sido interrompida;
- **nunca apaga** do HD um backup que sumiu do servidor;
- no HD, apaga só os diários com mais de 90 dias e os semanais com mais de 1 ano. Os mensais
  ficam para sempre;
- anota o resultado em `backups\copia-para-o-hd.log`.

Primeiro, teste o script à mão, com o HD ligado:

```powershell
cd C:\CRM\crm-ines-rossi
powershell -ExecutionPolicy Bypass -File docker\backup\windows\copiar-para-o-hd.ps1
```

Tem que aparecer uma linha `OK: último backup no HD: ...`. Abra o `Z:\backups-crm` e confira que
as pastas `diario`, `semanal` e `mensal` estão lá.

Depois, agende a cópia para todo dia:

1. Abra o **Agendador de Tarefas** (procure no menu Iniciar).
2. Na direita, clique em **Criar Tarefa...** (não use "Criar Tarefa Básica").
3. Aba **Geral**:
   - Nome: `Copiar backups do CRM para o HD`
   - Marque **Executar somente quando o usuário estiver conectado** (o Docker Desktop também só
     roda com o usuário conectado).
4. Aba **Disparadores** → **Novo...**:
   - **Diariamente**, às **03:00** (uma hora depois do `BACKUP_TIME`).
   - Confira que **Habilitado** está marcado → OK.
5. Aba **Ações** → **Novo...**:
   - Ação: **Iniciar um programa**
   - Programa/script: `powershell.exe`
   - Adicione argumentos:
     `-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\CRM\crm-ines-rossi\docker\backup\windows\copiar-para-o-hd.ps1"`
   - Iniciar em: `C:\CRM\crm-ines-rossi` → OK.
6. Aba **Condições**: desmarque **Iniciar a tarefa somente se o computador estiver ligado à
   energia CA**.
7. Aba **Configurações**: marque **Executar a tarefa o mais cedo possível após uma inicialização
   agendada ter sido perdida** (se o PC estiver desligado às 03:00, a cópia roda quando ele
   ligar).
8. OK. Na lista de tarefas, clique com o botão direito na tarefa nova, **Executar**, e confira
   a linha nova no fim de `backups\copia-para-o-hd.log`.

Se o HD estiver em outra letra, troque a letra no Gerenciamento de disco (passo 4.2) em vez de
mudar o script.

### 4.4 Toda semana: conferir e trocar o HD

1. Abra o registro e leia as últimas linhas:

   ```powershell
   Get-Content backups\copia-para-o-hd.log -Tail 7
   ```

   Tem que haver uma linha `OK` por dia. O que pode aparecer no lugar:

   | Mensagem | O que fazer |
   |---|---|
   | `ERRO: o HD externo (Z:) não está conectado` | Ligue o HD. Se ele estiver ligado, confira a letra no Gerenciamento de disco |
   | `ERRO: o robocopy falhou` | O HD pode estar cheio ou com defeito: troque pelo outro HD |
   | `AVISO: o backup mais recente no HD é de ... horas atrás` | O backup do CRM parou: veja `docker compose logs backup` |
   | Nenhuma linha nos últimos dias | A tarefa não está rodando: confira no Agendador de Tarefas |

2. Para trocar o HD: clique no ícone **Remover hardware com segurança** (perto do relógio),
   escolha o HD e espere a mensagem de que pode remover. Desligue o HD, ligue o outro e rode a
   cópia uma vez à mão (seção 4.3) para ele receber os backups da semana.

## 5. Cópia na nuvem (opcional)

Uma terceira cópia na nuvem protege contra incêndio ou roubo dos dois HDs. Como os arquivos já
saem criptografados, a empresa da nuvem não vê os dados. O jeito mais simples é instalar o app do
Google Drive (ou do OneDrive) no servidor e incluir a pasta `backups\mensal` na sincronização.
Não sincronize a pasta do projeto inteira: o `.env` tem senhas.

## 6. Restaurar

Restaurar **substitui** o banco e os anexos pelos do backup: o que foi feito depois do horário do
backup se perde. No servidor em uso, só restaure quando houver perda de dados.

1. Escolha o backup: o mais recente de antes do problema. Se ele não estiver mais no servidor,
   copie o par de arquivos (`.dump.gpg` e `_anexos.tar.gpg` do mesmo horário) do
   `Z:\backups-crm\diario` (ou `semanal`, `mensal`) para a pasta `backups\diario` do projeto.
2. Pare o sistema, para ninguém gravar nada no meio:

   ```powershell
   docker compose stop web
   ```

3. Restaure (troque pelo nome do arquivo do banco; o dos anexos é achado sozinho):

   ```powershell
   docker compose exec backup restaurar.sh diario/crm_2026-10-16_0200.dump.gpg
   ```

4. Ligue o sistema de novo. Ao iniciar, ele atualiza o banco restaurado para a versão atual:

   ```powershell
   docker compose start web
   ```

5. Abra o sistema, confira alguns clientes e abra um anexo.

O que a restauração mostra:

| Mensagem | O que quer dizer |
|---|---|
| `Banco restaurado` e `Anexos restaurados` | Deu certo |
| `ERRO: ... está incompleto ou estragado, ou a senha está errada. Nenhum dado foi alterado.` | O arquivo foi cortado (cópia interrompida), estragou, ou a `BACKUP_PASSPHRASE` do `.env` não é a do backup. Nada mudou: tente o backup do dia anterior ou outra cópia do HD |
| `ERRO: o backup do banco não pôde ser restaurado. Nenhum dado foi alterado.` | O arquivo abriu, mas o banco não montou. Nada mudou: guarde a mensagem inteira e peça ajuda |
| `AVISO: não há backup de anexos deste horário` | Só o banco foi restaurado. Copie o arquivo `_anexos.tar.gpg` do mesmo horário e rode de novo |

A restauração monta o backup num banco novo e só no fim troca o banco do sistema por ele. O banco
de antes fica guardado como `crm_antes_da_restauracao` até a próxima restauração, caso seja
preciso voltar atrás (peça ajuda para isso).

## 7. Teste de restauração (todo mês)

Backup que nunca foi restaurado não é garantia. Uma vez por mês, numa **máquina de teste** (nunca
no servidor em uso):

1. Instale o sistema nela seguindo os passos 1 a 3 do [guia de instalação](instalacao.md), com
   **o mesmo `.env`** do servidor (é ele que tem a senha dos backups).
2. Pegue o par de backups mais recente **do HD externo**, não do servidor: assim o teste também
   prova que a cópia para o HD funciona.
3. Restaure como na seção 6.
4. Confira: os últimos clientes cadastrados estão lá? Um anexo abre?
5. Anote a data e o resultado do teste.

## 8. O que nunca fazer

- `docker compose down -v`: o `-v` apaga o banco e os anexos (os volumes do Docker). Use
  `docker compose down`, sem o `-v`.
- No Docker Desktop, **Reset to factory defaults**, **Clean / Purge data** ou desinstalar: também
  apagam o banco e os anexos. Só a pasta `backups\` sobrevive.
- `robocopy ... /MIR` para o HD: o `/MIR` apaga do HD o que sumir do servidor.
- Apagar a pasta `backups\` do servidor para liberar espaço: ela já se limpa sozinha.
