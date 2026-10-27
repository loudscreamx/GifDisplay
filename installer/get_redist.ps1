# Скачивает официальный установщик драйвера PawnIO в installer\redist и проверяет его (SHA-256 и подпись).
# Запуск: powershell -ExecutionPolicy Bypass -File installer\get_redist.ps1
$ErrorActionPreference = "Stop"
$url = "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"
$sha = "1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032"
$dir = Join-Path $PSScriptRoot "redist"
New-Item -ItemType Directory -Force $dir | Out-Null
$file = Join-Path $dir "PawnIO_setup.exe"
Invoke-WebRequest $url -OutFile $file -UseBasicParsing
if ((Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -ne $sha) { Remove-Item $file; throw "SHA-256 does not match" }
$sig = Get-AuthenticodeSignature $file
if ($sig.Status -ne "Valid") { Remove-Item $file; throw "Signature is not valid: $($sig.Status)" }
"OK: $file ($($sig.SignerCertificate.Subject))"
