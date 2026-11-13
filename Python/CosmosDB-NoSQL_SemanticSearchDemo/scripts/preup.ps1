#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'postprovision.ps1') -Prepare -BootstrapOnly
