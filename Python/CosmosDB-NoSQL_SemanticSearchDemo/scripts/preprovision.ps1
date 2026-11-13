#Requires -Version 7.0
[CmdletBinding()]
param([switch]$RegenerateInvalidName)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'postprovision.ps1') -Prepare -RegenerateInvalidName:$RegenerateInvalidName
