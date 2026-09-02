$ErrorActionPreference = "Stop"

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[build]"
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "AccountingConverter" `
  --paths "src" `
  --collect-submodules "accounting_converter" `
  "src\accounting_converter\ui\app.py"

Write-Host "Build finished. Check dist\AccountingConverter."
