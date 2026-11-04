# Verify an internal-trial build before handing it to a tax accountant.
# Run after scripts\build_windows.ps1, from the repository root:
#   .\scripts\verify_trial_package.ps1
# It does not change the build. It stops (non-zero exit) on any problem.
param(
  [string]$ArtifactDir = "dist\AccountingConverter",
  [string]$ZipPath = "dist\AccountingConverter_InternalTrial.zip"
)

$ErrorActionPreference = "Stop"
$Problems = New-Object System.Collections.Generic.List[string]

function Fail([string]$Message) { $Problems.Add($Message) | Out-Null; Write-Host "NG: $Message" -ForegroundColor Red }
function Pass([string]$Message) { Write-Host "OK: $Message" -ForegroundColor Green }

if (-not (Test-Path $ArtifactDir)) { throw "$ArtifactDir がありません。先に build_windows.ps1 を実行してください。" }
$Root = (Resolve-Path $ArtifactDir).Path

# 1. Required files
foreach ($Required in @("AccountingConverter.exe", "_internal", "release_manifest.json", "BUILD_INFO.txt")) {
  if (Test-Path (Join-Path $Root $Required)) { Pass "$Required がある" } else { Fail "$Required がない" }
}

# 2. No customer data, company settings, logs or private folders in the bundle
$Files = Get-ChildItem -Path $Root -Recurse -File
$Relative = $Files | ForEach-Object { $_.FullName.Substring($Root.Length + 1) }
$ForbiddenPath = '(?i)(^|\\)(data\\private|private|companies|profiles|jdl-account-drafts|logs|tests|\.git|\.venv-build)(\\|$)'
$ForbiddenExtension = '(?i)\.(csv|tsv|xlsx|xls|pdf|log|audit\.json)$'
$BadPaths = $Relative | Where-Object { $_ -match $ForbiddenPath -or $_ -match $ForbiddenExtension }
# Top level may only hold the exe, the provenance files and _internal.
$TopLevel = Get-ChildItem -Path $Root | Where-Object { $_.Name -notin @("AccountingConverter.exe", "_internal", "release_manifest.json", "BUILD_INFO.txt") }
if ($BadPaths) { $BadPaths | ForEach-Object { Fail "配布物に含めてはいけないファイル: $_" } } else { Pass "顧客データ・会社設定・ログ・CSV/PDF/Excelは含まれていない" }
if ($TopLevel) { $TopLevel | ForEach-Object { Fail "想定外の最上位ファイル: $($_.Name)" } } else { Pass "最上位はexe・_internal・来歴ファイルだけ" }

# 3. Every file matches release_manifest.json, and nothing extra was added
$Manifest = Get-Content (Join-Path $Root "release_manifest.json") -Raw | ConvertFrom-Json
$Listed = @{}
foreach ($Entry in $Manifest.files) { $Listed[$Entry.path.Replace('/', '\')] = $Entry.sha256 }
$Mismatch = 0
foreach ($Path in $Relative) {
  if ($Path -in @("release_manifest.json", "BUILD_INFO.txt")) { continue }
  if (-not $Listed.ContainsKey($Path)) { Fail "manifestにないファイル: $Path"; $Mismatch++; continue }
  $Hash = (Get-FileHash -Algorithm SHA256 (Join-Path $Root $Path)).Hash.ToLower()
  if ($Hash -ne $Listed[$Path]) { Fail "ハッシュ不一致: $Path"; $Mismatch++ }
}
foreach ($Path in $Listed.Keys) { if (-not (Test-Path (Join-Path $Root $Path))) { Fail "manifestにあるが存在しない: $Path"; $Mismatch++ } }
if ($Mismatch -eq 0) { Pass "全 $($Listed.Count) ファイルがrelease_manifest.jsonと一致" }
$ExeHash = (Get-FileHash -Algorithm SHA256 (Join-Path $Root "AccountingConverter.exe")).Hash.ToLower()
if ($ExeHash -eq $Manifest.executable_sha256) { Pass "exe SHA-256 = $ExeHash" } else { Fail "exeのハッシュがmanifestと一致しない" }

# 4. Microsoft Defender scan of the folder (never disable Defender or add exclusions)
$MpCmdRun = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
function Scan([string]$Target) {
  if (-not (Test-Path $MpCmdRun)) { Fail "MpCmdRun.exe が見つからないためDefenderスキャンを実行できない"; return }
  & $MpCmdRun -Scan -ScanType 3 -File $Target -DisableRemediation | Out-Host
  if ($LASTEXITCODE -eq 0) { Pass "Defenderスキャンで検出なし: $Target" }
  else { Fail "Defenderスキャンの結果を確認すること（終了コード $LASTEXITCODE）: $Target。配布を止める。" }
}
Scan $Root

# 5. ZIP of the whole folder (not the exe alone), scanned again, hash kept outside the ZIP
if ($Problems.Count -eq 0) {
  if (Test-Path $ZipPath) { throw "$ZipPath が既にあります。確認してから削除し、再実行してください。" }
  Compress-Archive -Path $Root -DestinationPath $ZipPath
  Scan (Resolve-Path $ZipPath).Path
  $ZipHash = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLower()
  $Record = "$ZipPath.sha256.txt"
  @(
    "AccountingConverter internal trial",
    "Git commit: $($Manifest.git_commit)",
    "Project version: $($Manifest.project_version)",
    "Built at (UTC): $($Manifest.built_at_utc)",
    "AccountingConverter.exe SHA-256: $ExeHash",
    "ZIP SHA-256: $ZipHash",
    "Verified at: $((Get-Date).ToString('s'))"
  ) | Set-Content -Encoding utf8 $Record
  Pass "ZIP SHA-256 = $ZipHash（$Record に記録）"
}

if ($Problems.Count -gt 0) {
  Write-Host "`n$($Problems.Count)件の問題があります。配布しないでください。" -ForegroundColor Red
  exit 1
}
Write-Host "`nすべての確認に合格しました。次はクリーンなPCでの起動確認です（docs\operator\internal_trial_release.md）。" -ForegroundColor Green
