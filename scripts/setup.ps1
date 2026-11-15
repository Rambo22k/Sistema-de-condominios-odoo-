$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
$envTemplate = Join-Path $projectRoot '.env.example'
$configPath = Join-Path $projectRoot 'config/odoo.conf'
$configTemplate = Join-Path $projectRoot 'config/odoo.conf.example'

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envTemplate -Destination $envPath
    Write-Host 'Created .env from the example template.'
} else {
    Write-Host 'Kept the existing .env unchanged.'
}

if (-not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath $configTemplate -Destination $configPath
    Write-Host 'Created config/odoo.conf from the example template.'
} else {
    Write-Host 'Kept the existing config/odoo.conf unchanged.'
}

Write-Host 'Before starting Docker, set the database password, Odoo master password, and licensed Enterprise addons path in these local files.'
