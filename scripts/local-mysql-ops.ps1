$ErrorActionPreference = 'Stop'

function Import-LocalMySqlSettings {
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $configPath = Join-Path $projectRoot '.local-db.ps1'
    if (-not (Test-Path -LiteralPath $configPath)) {
        throw 'تنظیمات اتصال محلی پیدا نشد؛ ابتدا scripts\setup-local-mysql.ps1 را اجرا کنید.'
    }
    . $configPath
    foreach ($name in @('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
            throw "متغیر اتصال $name در تنظیمات محلی خالی است."
        }
    }
    if ($env:DB_NAME -notmatch '^[A-Za-z0-9_]+$') {
        throw 'نام دیتابیس محلی دارای نویسهٔ پشتیبانی‌نشده است.'
    }
    return $projectRoot
}

function New-LocalMySqlDefaultsFile {
    $escapeOption = {
        param([string]$Value)
        $escaped = $Value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '').Replace("`n", '')
        return '"' + $escaped + '"'
    }
    $clientPath = Join-Path ([IO.Path]::GetTempPath()) ('.ariaa-mysql-' + [Guid]::NewGuid().ToString('N') + '.cnf')
    $config = @(
        '[client]',
        "user=$(& $escapeOption $env:DB_USER)",
        "password=$(& $escapeOption $env:DB_PASSWORD)",
        "host=$(& $escapeOption $env:DB_HOST)",
        "port=$(& $escapeOption $env:DB_PORT)",
        'default-character-set=utf8mb4',
        ''
    ) -join "`n"
    [IO.File]::WriteAllText($clientPath, $config, [Text.UTF8Encoding]::new($false))

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $clientPath /inheritance:r /grant:r "$($identity):F" *> $null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $clientPath -Force -ErrorAction SilentlyContinue
        throw 'محدودکردن دسترسی فایل موقت رمز MySQL انجام نشد.'
    }
    return $clientPath
}

function Remove-LocalMySqlDefaultsFile {
    param([string]$Path)
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        Remove-Item -LiteralPath $Path -Force
    }
}
