$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$localConfigPath = Join-Path $projectRoot '.local-sms.ps1'

if (Test-Path -LiteralPath $localConfigPath) {
    $overwrite = Read-Host 'تنظیم کاوه‌نگار محلی موجود است. جایگزین شود؟ (y/N)'
    if ($overwrite -notin @('y', 'Y', 'yes', 'YES')) {
        Write-Host 'تنظیم قبلی دست‌نخورده ماند.'
        exit 0
    }
}

$secureApiKey = Read-Host 'Kavenegar API key (input hidden)' -AsSecureString
if ($secureApiKey.Length -eq 0) {
    throw 'API key cannot be empty.'
}

$bstr = [IntPtr]::Zero
$apiKey = $null
$localSettings = $null
try {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $secureApiKey.Dispose()
}

if ([string]::IsNullOrWhiteSpace($apiKey) -or $apiKey -match '[\r\n]') {
    $apiKey = $null
    throw 'API key is empty or invalid.'
}

$template = (Read-Host 'نام دقیق الگوی تأییدشدهٔ Verify Lookup در کاوه‌نگار').Trim()
if ($template -notmatch '^[A-Za-z0-9-]+$') {
    $apiKey = $null
    throw 'Template name must contain only English letters, digits, or hyphens.'
}

try {
    $escapedApiKey = $apiKey.Replace("'", "''")
    $localSettings = "`$env:KAVENEGAR_API_KEY = '$escapedApiKey'`r`n" +
        "`$env:KAVENEGAR_OTP_TEMPLATE = '$template'`r`n"
    [System.IO.File]::WriteAllText($localConfigPath, '', [System.Text.UTF8Encoding]::new($false))

    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $currentUserSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($accessRule)
    Set-Acl -LiteralPath $localConfigPath -AclObject $acl
    [System.IO.File]::WriteAllText($localConfigPath, $localSettings, [System.Text.UTF8Encoding]::new($false))

    Write-Host 'تنظیم محلی کاوه‌نگار ذخیره شد؛ مقدار کلید نمایش داده نمی‌شود.'
    Write-Host 'سرور را با .\scripts\run-local.ps1 دوباره اجرا کنید تا تنظیمات بارگذاری شوند.'
}
finally {
    $apiKey = $null
    $escapedApiKey = $null
    $localSettings = $null
}
