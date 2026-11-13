#Requires -Version 7.0
[CmdletBinding()]
param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
  [switch]$IncludeDotnet,
  [ValidateRange(1024, 65535)][int]$PythonPort = 8501,
  [ValidateRange(1024, 65535)][int]$DotnetPort = 8503
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$sampleRoot = if ($IncludeDotnet) { Join-Path $ProjectRoot 'python' } else { $ProjectRoot }
$config = Join-Path $ProjectRoot '.local/azd-env.ps1'
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { throw 'Run azd up first. Generated local configuration is missing.' }
. $config
$python = if ($IsWindows) { Join-Path $sampleRoot '.venv/Scripts/python.exe' } else { Join-Path $sampleRoot '.venv/bin/python' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python venv is missing. Run azd up first.' }
$specs = @(@{
  Name = 'Streamlit'; File = $python; Port = $PythonPort
  Arguments = @('-m', 'streamlit', 'run', (Join-Path $sampleRoot 'src/app/cosmos-app.py'),
    '--server.address', '127.0.0.1', '--server.port', "$PythonPort", '--server.headless', 'true')
})
if ($IncludeDotnet) {
  if ($PythonPort -eq $DotnetPort) { throw 'The apps require distinct ports.' }
  $dotnet = (Get-Command dotnet -ErrorAction Stop).Source
  $dll = Join-Path $ProjectRoot 'dotnet/src/SemanticReranker.Web/bin/Debug/net10.0/SemanticReranker.Web.dll'
  if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw '.NET build is missing. Run azd up first.' }
  # Run the built assembly directly, not a detached dotnet run process.
  $specs += @{
    Name = 'Razor'; File = $dotnet; Port = $DotnetPort
    Arguments = @($dll, '--urls', "http://127.0.0.1:$DotnetPort",
      '--contentRoot', (Join-Path $ProjectRoot 'dotnet/src/SemanticReranker.Web'))
  }
}
# Check every port before starting either process. Never stop an existing listener.
foreach ($spec in $specs) {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $spec.Port)
  $listener.Server.ExclusiveAddressUse = $true
  try { $listener.Start() }
  catch [System.Net.Sockets.SocketException] { throw "Port $($spec.Port) is busy. No existing process was stopped." }
  finally { $listener.Stop() }
}
$children = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
try {
  foreach ($spec in $specs) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $spec.File
    $info.WorkingDirectory = $ProjectRoot
    $info.UseShellExecute = $false
    foreach ($argument in $spec.Arguments) { $info.ArgumentList.Add($argument) }
    $child = [System.Diagnostics.Process]::Start($info)
    $children.Add($child)
    Write-Host "Starting $($spec.Name), owned PID $($child.Id): http://127.0.0.1:$($spec.Port)"
  }
  Write-Host 'Foreground supervisor active. Ctrl+C stops only these owned processes. Startup does not load data.'
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $ready = $false
  while ($true) {
    foreach ($child in $children) {
      if ($child.HasExited) { throw "App PID $($child.Id) exited with code $($child.ExitCode). Stopping its sibling." }
    }
    if (-not $ready) {
      $ready = $true
      foreach ($spec in $specs) {
        $socket = [System.Net.Sockets.TcpClient]::new()
        try { $socket.Connect([System.Net.IPAddress]::Loopback, $spec.Port) }
        catch [System.Net.Sockets.SocketException] { $ready = $false }
        finally { $socket.Dispose() }
      }
      if ($ready) { Write-Host 'All local app ports are listening. Open the URLs above; search validation is separate.' }
      elseif ($timer.Elapsed.TotalSeconds -ge 60) { throw 'App startup timed out after 60 seconds.' }
    }
    Start-Sleep -Milliseconds 250
  }
}
finally {
  $cleanupErrors = [System.Collections.Generic.List[string]]::new()
  foreach ($child in $children) {
    try {
      if (-not $child.HasExited) {
        $child.Kill($true)
        if (-not $child.WaitForExit(10000)) { $cleanupErrors.Add("PID $($child.Id) did not exit within 10 seconds.") }
      }
    }
    catch [System.InvalidOperationException] {
      if (-not $child.HasExited) { $cleanupErrors.Add("Could not stop owned PID $($child.Id).") }
    }
    catch [System.ComponentModel.Win32Exception] {
      if (-not $child.HasExited) { $cleanupErrors.Add("Could not stop owned PID $($child.Id): $($_.Exception.NativeErrorCode).") }
    }
    finally { $child.Dispose() }
  }
  if ($cleanupErrors.Count) { throw ($cleanupErrors -join ' ') }
  Write-Host 'Owned app processes stopped.'
}
