#requires -version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path $PSScriptRoot -Parent
$source = [IO.File]::ReadAllText((Join-Path $kitRoot 'bootstrap-windows.ps1'))
$parserErrors = $null
[void][Management.Automation.Language.Parser]::ParseFile((Join-Path $kitRoot 'bootstrap-windows.ps1'), [ref]$null, [ref]$parserErrors)
if ($parserErrors) { throw 'Dependency-only bootstrap failed PowerShell parsing.' }
if (-not $source.Contains("`$dependenciesOnly = `$Arguments -contains '--check-dependencies'")) { throw 'Dependency-only argument was not parsed.' }
if (-not $source.Contains("`$_ -ne '--accept-tool-licenses' -and `$_ -ne '--check-dependencies'")) { throw 'Bootstrap-only arguments must not reach phone setup.' }
$checkPosition = $source.IndexOf('if ($dependenciesOnly) {')
$releaseLock = $source.IndexOf('} finally { $lock.Dispose() }', $source.IndexOf('function Invoke-WindowsBootstrap'))
$phoneSetup = $source.IndexOf('if (-not $explicitAdb)', $checkPosition)
if ($checkPosition -le $releaseLock -or $phoneSetup -le $checkPosition) { throw 'Dependency-only mode must release the tool lock and return before phone setup.' }
$checkBody = $source.Substring($checkPosition, $phoneSetup - $checkPosition)
if (-not $checkBody.Contains('return 0') -or $checkBody -match 'New-ToolProcess|setup-records|adb.+devices') { throw 'Dependency-only mode must return without a phone command.' }
Write-Host 'PASS 5 PowerShell dependency-only contract checks.'
