param(
  [switch]$TkFallback
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

$DirtyFiles = git status --porcelain --untracked-files=all
if ($LASTEXITCODE -ne 0) {
  throw "Git status could not be read. Run this script from a valid clone."
}
if ($DirtyFiles) {
  throw "The worktree is not clean. Commit or remove local changes before a release build."
}

$BuildVenv = ".venv-build"
if (Test-Path $BuildVenv) {
  throw "$BuildVenv already exists. Remove it manually, review the action, and run again."
}

foreach ($Path in @("build", "dist")) {
  if (Test-Path $Path) {
    Remove-Item -Recurse -Force $Path
  }
}

py -3.12 -m venv $BuildVenv
& ".\$BuildVenv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -e ".[build]"
$EntryPoint = "src\accounting_converter\ui_qt\app.py"
$QtArguments = @("--collect-all", "PySide6")
if ($TkFallback) {
  $EntryPoint = "src\accounting_converter\ui\app.py"
  $QtArguments = @()
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "AccountingConverter" `
  --paths "src" `
  --collect-submodules "accounting_converter" `
  @QtArguments `
  $EntryPoint

$GitCommit = git rev-parse HEAD
$PythonVersion = python -c "import platform; print(platform.python_version())"
$PyInstallerVersion = python -c "import PyInstaller; print(PyInstaller.__version__)"
$ProjectVersion = python -c "import accounting_converter; print(accounting_converter.__version__)"
python -m pip list --format=json | Set-Content -Encoding utf8 "build\build_dependencies.json"
python scripts\generate_release_manifest.py `
  --artifact-dir "dist\AccountingConverter" `
  --git-commit $GitCommit `
  --project-version $ProjectVersion `
  --python-version $PythonVersion `
  --pyinstaller-version $PyInstallerVersion `
  --dependencies-json "build\build_dependencies.json"

Write-Host "Build finished. Review dist\AccountingConverter and its release manifest."
Write-Host "GUI entry point: $EntryPoint"
Write-Host "Do not distribute until Defender scan, clean-PC smoke test, and ZIP hashing pass."
