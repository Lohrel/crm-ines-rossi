# Copia os backups do CRM para o HD externo. Feito para o Agendador de Tarefas do Windows,
# que o roda todo dia depois do backup (veja docs/backup.md).
#
# - Só acrescenta: nunca apaga do HD um backup que sumiu do servidor.
# - Refaz uma cópia que tenha sido interrompida.
# - No HD, apaga só os backups diários com mais de $DiasDiarios dias e os semanais com mais de
#   $DiasSemanais dias. Os mensais ficam para sempre.
# - Anota tudo em backups\copia-para-o-hd.log, na pasta do projeto.
#
# Uso manual (PowerShell, na pasta do projeto):
#   powershell -ExecutionPolicy Bypass -File docker\backup\windows\copiar-para-o-hd.ps1

param(
    # Pasta do HD externo onde os backups ficam. A letra precisa ser fixa (veja docs/backup.md).
    [string]$Destino = "Z:\backups-crm",
    [int]$DiasDiarios = 90,
    [int]$DiasSemanais = 365
)

$ErrorActionPreference = "Stop"
$projeto = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$origem = Join-Path $projeto "backups"
$registro = Join-Path $origem "copia-para-o-hd.log"

function Anotar([string]$texto) {
    $linha = "{0:dd/MM/yyyy HH:mm}  {1}" -f (Get-Date), $texto
    Write-Output $linha
    Add-Content -Path $registro -Value $linha -Encoding UTF8
}

$unidade = Split-Path -Qualifier $Destino
if (-not (Test-Path "$unidade\")) {
    Anotar "ERRO: o HD externo ($unidade) não está conectado. Nada foi copiado."
    exit 1
}
if (-not (Test-Path (Join-Path $origem "diario"))) {
    Anotar "ERRO: a pasta $origem\diario não existe. O backup do CRM está rodando?"
    exit 1
}

# /E copia as subpastas (diario, semanal, mensal) sem nunca apagar nada do destino.
# Os arquivos .parcial são backups ainda em andamento, e o .log é este registro.
robocopy $origem $Destino /E /R:2 /W:5 /NP /NFL /NDL /XF *.parcial copia-para-o-hd.log | Out-Null
$codigo = $LASTEXITCODE
# O robocopy usa códigos de 0 a 7 para "deu certo" e 8 ou mais para erro.
if ($codigo -ge 8) {
    Anotar "ERRO: o robocopy falhou (código $codigo). Confira se o HD está cheio ou com defeito."
    exit 1
}

function Limpar([string]$pasta, [int]$dias) {
    $caminho = Join-Path $Destino $pasta
    if (-not (Test-Path $caminho)) { return 0 }
    $limite = (Get-Date).AddDays(-$dias)
    $antigos = @(Get-ChildItem -Path $caminho -File -Filter "crm_*.gpg" |
        Where-Object { $_.LastWriteTime -lt $limite })
    $antigos | Remove-Item
    return $antigos.Count
}
$apagados = (Limpar "diario" $DiasDiarios) + (Limpar "semanal" $DiasSemanais)

$ultimo = Get-ChildItem -Path (Join-Path $Destino "diario") -File -Filter "crm_*.dump.gpg" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $ultimo) {
    Anotar "ERRO: não há nenhum backup do banco no HD."
    exit 1
}
$livre = [math]::Round((Get-PSDrive $unidade.TrimEnd(":")).Free / 1GB, 1)
$horas = [math]::Round(((Get-Date) - $ultimo.LastWriteTime).TotalHours)
if ($horas -gt 36) {
    Anotar "AVISO: o backup mais recente no HD é de $horas horas atrás ($($ultimo.Name)). O backup diário do CRM parou?"
    exit 1
}
Anotar "OK: último backup no HD: $($ultimo.Name). Antigos apagados do HD: $apagados. Livre no HD: $livre GB."
