#Requires -Version 7.0
[CmdletBinding()]
param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
  [switch]$IncludeDotnet
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tools = @('az', 'azd')
if ($IncludeDotnet) { $tools += 'dotnet' }
foreach ($tool in $tools) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Required tool missing: $tool. See README prerequisites." }
}
$sampleRoot = if ($IncludeDotnet) { Join-Path $ProjectRoot 'python' } else { $ProjectRoot }
$python = if ($IsWindows) { Join-Path $sampleRoot '.venv/Scripts/python.exe' } else { Join-Path $sampleRoot '.venv/bin/python' }
if (-not (Test-Path -LiteralPath $python)) {
  $base = Get-Command $(if ($IsWindows) { 'python' } else { 'python3' }) -ErrorAction Stop
  & $base.Source -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
  if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ with venv and pip is required.' }
  & $base.Source -m venv (Join-Path $sampleRoot '.venv')
  if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed. Install Python venv support.' }
}
& $python -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { throw 'The existing virtual environment requires Python 3.10+.' }
& $python -m pip install -r (Join-Path $sampleRoot 'requirements.txt') -r (Join-Path $sampleRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check public package access and trusted TLS.' }
if ($IncludeDotnet) {
  & dotnet restore (Join-Path $ProjectRoot 'dotnet/SemanticReranker.sln')
  if ($LASTEXITCODE -ne 0) { throw '.NET restore failed. Install the .NET 10 SDK and check NuGet access.' }
  & dotnet build (Join-Path $ProjectRoot 'dotnet/SemanticReranker.sln') --no-restore
  if ($LASTEXITCODE -ne 0) { throw '.NET build failed.' }
}
Write-Host 'Local dependencies are ready.'
