#Requires -Version 7.0
[CmdletBinding()]
param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
  [switch]$IncludeDotnet,
  [switch]$Prepare,
  [switch]$BootstrapOnly,
  [switch]$RegenerateInvalidName
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($BootstrapOnly -and -not $Prepare) {
  throw 'Bootstrap-only is valid only during preparation, never configuration generation.'
}

$sampleRoot = if ($IncludeDotnet) { Join-Path $ProjectRoot 'python' } else { $ProjectRoot }
if ($Prepare) {
  & (Join-Path $PSScriptRoot 'bootstrap.ps1') -ProjectRoot $ProjectRoot -IncludeDotnet:$IncludeDotnet
}
$python = if ($IsWindows) {
  Join-Path $sampleRoot '.venv/Scripts/python.exe'
} else {
  Join-Path $sampleRoot '.venv/bin/python'
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  throw 'Virtual environment missing. Run azd up to bootstrap dependencies first.'
}
if ($RegenerateInvalidName -and -not $Prepare) {
  throw 'Name recovery is only available through the preprovision hook.'
}
$scriptName = if ($Prepare) { 'prepare_azd.py' } else { 'configure_azd.py' }
$arguments = @((Join-Path $PSScriptRoot $scriptName), '--project-root', $ProjectRoot)
if ($IncludeDotnet -and -not $Prepare) { $arguments += '--include-dotnet' }
if ($RegenerateInvalidName) { $arguments += '--regenerate-invalid-name' }
if ($BootstrapOnly) { $arguments += '--bootstrap-only' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Local azd configuration failed. Resolve the error and rerun this hook.' }
