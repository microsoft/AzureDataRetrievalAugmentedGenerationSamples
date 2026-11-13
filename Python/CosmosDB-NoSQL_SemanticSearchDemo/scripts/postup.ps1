#Requires -Version 7.0
[CmdletBinding()]
param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
  [switch]$IncludeDotnet
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$sampleRoot = if ($IncludeDotnet) { Join-Path $ProjectRoot 'python' } else { $ProjectRoot }
$config = Join-Path $ProjectRoot '.local/azd-env.ps1'
if (-not (Test-Path -LiteralPath $config)) { throw 'Generated configuration missing. Run azd up.' }
. $config
$python = if ($IsWindows) { Join-Path $sampleRoot '.venv/Scripts/python.exe' } else { Join-Path $sampleRoot '.venv/bin/python' }
$arguments = @((Join-Path $sampleRoot 'src/seed_movies.py'), '--confirm-write', '--cleanup-original-fixtures')
if ($IncludeDotnet) { $arguments += '--include-dotnet' }
& $python @arguments
if ($LASTEXITCODE -ne 0) {
  throw 'MovieLens restoration failed. See the original error and local receipt. Fix the cause and rerun; completed embedding batches are cached. Legacy fixture cleanup is allowed only after full readback of every target.'
}
Write-Host 'Seed complete. Start locally with: pwsh ./scripts/start.ps1'
