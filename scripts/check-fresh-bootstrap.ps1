#requires -version 5.1
# Native Windows fixture: actual verified private downloads, no phone commands.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $kitRoot 'bootstrap-windows.ps1') --library-only
$cache = Join-Path $env:LOCALAPPDATA 'HiBreakAutoScale\tools'
if ([IO.Directory]::Exists($cache)) {
    throw 'Fresh-runtime check requires an absent HiBreak private tool cache.'
}
# Only discovery is replaced. Download pins, safe extraction, cache publication,
# isolated imports and native ADB/Python version execution remain production code.
function Find-Python { return $null }
function Find-Adb([string]$ExplicitAdb) { return $null }
$status = Invoke-WindowsBootstrap @('--check-dependencies', '--accept-tool-licenses') $kitRoot
if ($status -ne 0) { throw ('Fresh dependency check failed: ' + $status) }
if ([IO.Directory]::Exists((Join-Path $env:LOCALAPPDATA 'HiBreakAutoScale\setup-records'))) {
    throw 'Dependency-only mode unexpectedly entered phone setup.'
}
