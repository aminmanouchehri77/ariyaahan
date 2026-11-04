$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$localConfigPath = Join-Path $projectRoot '.local-db.ps1'
if (-not (Test-Path -LiteralPath $localConfigPath)) {
    throw 'تنظیمات اتصال وجود ندارد؛ ابتدا scripts\setup-local-mysql.ps1 را اجرا کنید.'
}
. $localConfigPath

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
    & $pythonPath manage.py migrate
    if ($LASTEXITCODE -ne 0) { throw "Django migrations failed with exit code $LASTEXITCODE." }
    & $pythonPath manage.py check --database default
    if ($LASTEXITCODE -ne 0) { throw "Django database check failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
