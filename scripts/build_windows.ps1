# Gera dist\UBento\UBento.exe (PyInstaller) e, se o Inno Setup estiver instalado, o instalador.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m pip install -e ".[dev]"
python scripts\make_icon.py
python -m PyInstaller ubento.spec --noconfirm --clean

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) { $iscc = Get-Item "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue }
if ($iscc) { & $iscc.Source installer\ubento.iss } else { Write-Host "Inno Setup não encontrado: instalador não gerado (o app portátil está em dist\UBento)." }
