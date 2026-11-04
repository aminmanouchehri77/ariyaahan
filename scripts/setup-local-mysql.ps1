$ErrorActionPreference = 'Stop'

$databaseName = 'ariaahan'
$applicationUser = 'ariaahan_app'
$databaseHost = '127.0.0.1'
$databasePort = '3306'
$localConfigPath = Join-Path (Split-Path -Parent $PSScriptRoot) '.local-db.ps1'

$mysqlCommand = Get-Command mysql.exe -ErrorAction SilentlyContinue
if (-not $mysqlCommand) {
    throw 'mysql.exe پیدا نشد. مسیر MySQL Server را به PATH اضافه کنید یا mysql.exe را در PATH قرار دهید.'
}

$administratorUser = Read-Host 'MySQL administrator account [root]'
if ([string]::IsNullOrWhiteSpace($administratorUser)) { $administratorUser = 'root' }

if (Test-Path -LiteralPath $localConfigPath) {
    $overwrite = Read-Host 'تنظیمات اتصال محلی موجود است. بازسازی کاربر برنامه و جایگزینی رمز محلی؟ (y/N)'
    if ($overwrite -notin @('y', 'Y', 'yes', 'YES')) {
        Write-Host 'راه‌اندازی لغو شد؛ تنظیمات قبلی دست‌نخورده ماند.'
        exit 0
    }
}

$randomBytes = New-Object byte[] 32
$randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $randomGenerator.GetBytes($randomBytes)
}
finally {
    $randomGenerator.Dispose()
}
$applicationPassword = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
[Array]::Clear($randomBytes, 0, $randomBytes.Length)

$sqlPath = Join-Path ([System.IO.Path]::GetTempPath()) ("ariaahan-db-" + [guid]::NewGuid().ToString('N') + '.sql')
$sql = @"
CREATE DATABASE IF NOT EXISTS ``$databaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '$applicationUser'@'$databaseHost' IDENTIFIED BY '$applicationPassword';
ALTER USER '$applicationUser'@'$databaseHost' IDENTIFIED BY '$applicationPassword';
GRANT ALL PRIVILEGES ON ``$databaseName``.* TO '$applicationUser'@'$databaseHost';
SELECT VERSION() AS mysql_server_version;
"@

try {
    [System.IO.File]::WriteAllText($sqlPath, $sql, [System.Text.UTF8Encoding]::new($false))

    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $currentUserSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($accessRule)
    Set-Acl -LiteralPath $sqlPath -AclObject $acl

    $mysqlSourcePath = $sqlPath.Replace('\', '/')
    $sourceCommand = 'source "' + $mysqlSourcePath + '"'
    Write-Host 'رمز مدیر MySQL را در prompt خود MySQL وارد کنید؛ رمز در تاریخچهٔ دستور ثبت نمی‌شود.'
    & $mysqlCommand.Source --protocol=TCP --host=$databaseHost --port=$databasePort --user=$administratorUser --password --default-character-set=utf8mb4 --batch --execute=$sourceCommand
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL bootstrap failed with exit code $LASTEXITCODE. Database or user setup was not confirmed."
    }

    $localSettings = @"
`$env:DB_ENGINE = 'django.db.backends.mysql'
`$env:DB_NAME = '$databaseName'
`$env:DB_USER = '$applicationUser'
`$env:DB_PASSWORD = '$applicationPassword'
`$env:DB_HOST = '$databaseHost'
`$env:DB_PORT = '$databasePort'
"@
    [System.IO.File]::WriteAllText($localConfigPath, $localSettings, [System.Text.UTF8Encoding]::new($false))
    Set-Acl -LiteralPath $localConfigPath -AclObject $acl
    Write-Host "Database '$databaseName' and application account '$applicationUser' are ready."
    Write-Host 'The local connection settings were saved in .local-db.ps1, which Git ignores.'
}
finally {
    if (Test-Path -LiteralPath $sqlPath) {
        Remove-Item -LiteralPath $sqlPath -Force
    }
    $applicationPassword = $null
    $sql = $null
}
