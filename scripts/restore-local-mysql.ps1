param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local-mysql-ops.ps1')
$projectRoot = Import-LocalMySqlSettings
$mysqlCommand = Get-Command mysql.exe -ErrorAction SilentlyContinue
if (-not $mysqlCommand) { throw 'mysql.exe پیدا نشد؛ ابزارهای MySQL Client را نصب یا به PATH اضافه کنید.' }

$backupDirectory = [IO.Path]::GetFullPath((Join-Path $projectRoot 'backups'))
$suppliedPath = if ([IO.Path]::IsPathRooted($BackupFile)) { $BackupFile } else { Join-Path $projectRoot $BackupFile }
$backupPath = [IO.Path]::GetFullPath($suppliedPath)
$allowedPrefix = $backupDirectory.TrimEnd('\') + '\'
if (-not $backupPath.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'برای جلوگیری از انتخاب فایل نامرتبط، فایل پشتیبان باید داخل پوشهٔ backups پروژه باشد.'
}
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf) -or [IO.Path]::GetExtension($backupPath) -ne '.sql') {
    throw 'فایل SQL پشتیبان پیدا نشد.'
}
if ([IO.Path]::GetFileName($backupPath) -notmatch '^ariaahan-\d{8}-\d{6}-\d{3}\.sql$') {
    throw 'نام فایل با الگوی پشتیبان‌های ساخته‌شدهٔ پروژه سازگار نیست.'
}
if ($backupPath.Contains(' ')) {
    throw 'برای بازگردانی، مسیر پوشهٔ پروژه و فایل پشتیبان نباید فاصله داشته باشد.'
}

Write-Warning "این عملیات جدول‌های دیتابیس $env:DB_NAME را با محتوای فایل پشتیبان جایگزین می‌کند."
$typedDatabase = Read-Host "برای ادامه نام دیتابیس را دقیقاً وارد کنید: $env:DB_NAME"
if ($typedDatabase -cne $env:DB_NAME) { throw 'نام دیتابیس یکسان نبود؛ هیچ تغییری انجام نشد.' }
$typedConfirmation = Read-Host 'برای تأیید نهایی RESTORE را وارد کنید'
if ($typedConfirmation -cne 'RESTORE') { throw 'بازگردانی لغو شد؛ هیچ تغییری انجام نشد.' }

$defaultsPath = New-LocalMySqlDefaultsFile
try {
    $sourcePath = $backupPath.Replace('\', '/')
    & $mysqlCommand.Source "--defaults-extra-file=$defaultsPath" '--default-character-set=utf8mb4' $env:DB_NAME '--execute' "source $sourcePath"
    if ($LASTEXITCODE -ne 0) { throw "بازگردانی با کد $LASTEXITCODE ناموفق بود؛ وضعیت دیتابیس را بررسی کنید." }
    Write-Output 'بازگردانی دیتابیس پایان یافت.'
}
finally {
    Remove-LocalMySqlDefaultsFile $defaultsPath
}
