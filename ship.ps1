# Раскатка с ноутбука одной командой:
#
#   .\ship.ps1                 # всё: запушить бокс и вход, на машине пересобрать и поднять
#   .\ship.ps1 skin-web        # пересобрать только названные службы бокса
#   .\ship.ps1 -NoBuild        # поднять без пересборки
#
# Что делает: пушит незапушенное в этом репозитории и в соседнем ../Gate (если он есть), потом
# запускает ship.sh на машине — он сам делает git pull, сборку, подъём и проверку.
#
# Вход на машину: ssh по ключу, если он есть; иначе plink с паролем из переменной окружения
# NEUROBOX_SSH_PASSWORD (пароль в файлы не кладётся никогда).

param(
    [switch]$NoBuild,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Services
)

$ErrorActionPreference = "Stop"
$Server = "root@150.251.145.87"
$HostKey = "SHA256:omFs0Jtz85BTsJwxfJk9zhnr1Bzh9LYII9zdWAHQiW8"

function Push-IfAhead([string]$Repo) {
    if (-not (Test-Path (Join-Path $Repo ".git"))) { return }
    $dirty = git -C $Repo status --porcelain
    if ($dirty) { Write-Host "!! $Repo: есть незакоммиченные правки, они на машину НЕ уедут" -ForegroundColor Yellow }
    $ahead = git -C $Repo rev-list --count '@{u}..HEAD' 2>$null
    if ($ahead -and [int]$ahead -gt 0) {
        Write-Host "-> $Repo: push ($ahead коммит(а))"
        git -C $Repo push -q
    }
}

Push-IfAhead $PSScriptRoot
Push-IfAhead (Join-Path (Split-Path $PSScriptRoot -Parent) "Gate")

$remoteArgs = @()
if ($NoBuild) { $remoteArgs += "--no-build" }
$remoteArgs += $Services
$remote = "cd /opt/neurobox && git pull --ff-only -q && bash ship.sh $($remoteArgs -join ' ')"

$plink = "C:\Program Files\PuTTY\plink.exe"
if ($env:NEUROBOX_SSH_PASSWORD -and (Test-Path $plink)) {
    & $plink -batch -ssh -hostkey $HostKey -pw $env:NEUROBOX_SSH_PASSWORD $Server $remote
} else {
    ssh -o BatchMode=yes $Server $remote
}
exit $LASTEXITCODE
