$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$localConfigPath = Join-Path $projectRoot '.local-db.ps1'
if (-not (Test-Path -LiteralPath $localConfigPath)) {
    throw 'تنظیمات اتصال وجود ندارد؛ ابتدا scripts\setup-local-mysql.ps1 را اجرا کنید.'
}
. $localConfigPath

$localSmsConfigPath = Join-Path $projectRoot '.local-sms.ps1'
if (Test-Path -LiteralPath $localSmsConfigPath) {
    . $localSmsConfigPath
}

$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python محیط مجازی پروژه پیدا نشد.'
}

& $pythonPath -c 'import MySQLdb' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'درایور mysqlclient در محیط مجازی نصب نیست. پس از تأیید نصب وابستگی‌ها، pip install -r requirements.txt را اجرا کنید.'
}

Push-Location $projectRoot
try {
    & $pythonPath manage.py runserver 127.0.0.1:8000
}
finally {
    Pop-Location
}
