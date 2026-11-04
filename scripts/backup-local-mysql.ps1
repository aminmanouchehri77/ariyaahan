$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local-mysql-ops.ps1')
$projectRoot = Import-LocalMySqlSettings
$dumpCommand = Get-Command mysqldump.exe -ErrorAction SilentlyContinue
if (-not $dumpCommand) { throw 'mysqldump.exe پیدا نشد؛ ابزارهای MySQL Client را نصب یا به PATH اضافه کنید.' }

$backupDirectory = Join-Path $projectRoot 'backups'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $backupDirectory /inheritance:r /grant:r "$($identity):(OI)(CI)F" *> $null
if ($LASTEXITCODE -ne 0) { throw 'محدودکردن دسترسی پوشهٔ پشتیبان انجام نشد.' }

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$backupPath = Join-Path $backupDirectory ("ariaahan-$timestamp.sql")
$defaultsPath = New-LocalMySqlDefaultsFile
try {
    $arguments = @(
        "--defaults-extra-file=$defaultsPath",
        '--single-transaction',
        '--routines',
        '--triggers',
        '--hex-blob',
        '--default-character-set=utf8mb4',
        "--result-file=$backupPath",
        $env:DB_NAME
    )
    & $dumpCommand.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        throw "گرفتن نسخهٔ پشتیبان با کد $LASTEXITCODE ناموفق بود."
    }
    & icacls.exe $backupPath /inheritance:r /grant:r "$($identity):F" *> $null
    if ($LASTEXITCODE -ne 0) { throw 'محدودکردن دسترسی فایل پشتیبان انجام نشد.' }
    Write-Output "نسخهٔ پشتیبان محلی ساخته شد: $backupPath"
}
finally {
    Remove-LocalMySqlDefaultsFile $defaultsPath
}
