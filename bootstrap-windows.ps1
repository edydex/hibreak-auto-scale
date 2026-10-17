#requires -version 5.1
<#
HiBreak dependency bootstrap for Windows PowerShell 5.1 or newer.
Uses existing compatible tools, or verified official portable ZIPs in LocalAppData.
No administrator rights, persistent PATH change, pip, or package manager needed.
Run Setup-on-Windows.cmd; it applies a process-only execution-policy override.
Unknown setup arguments are passed as distinct process arguments, never evaluated.
#>
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Quote-WindowsArgument([AllowEmptyString()][string]$Value) {
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $result = New-Object System.Text.StringBuilder
    [void]$result.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') {
            [void]$result.Append(('\' * ($slashes * 2 + 1)))
            [void]$result.Append('"')
        } else {
            [void]$result.Append(('\' * $slashes))
            [void]$result.Append($character)
        }
        $slashes = 0
    }
    [void]$result.Append(('\' * ($slashes * 2)))
    [void]$result.Append('"')
    return $result.ToString()
}

function New-ToolProcess([string]$Executable, [string[]]$Arguments, [bool]$Capture) {
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = (($Arguments | ForEach-Object { Quote-WindowsArgument $_ }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $Capture
    $start.RedirectStandardOutput = $Capture
    $start.RedirectStandardError = $Capture
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    return $process
}

function Invoke-ToolCheck([string]$Executable, [string[]]$Arguments, [int]$TimeoutSeconds = 15) {
    $process = New-ToolProcess $Executable $Arguments $true
    try {
        [void]$process.Start()
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            throw 'Tool version check timed out.'
        }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $output.GetAwaiter().GetResult(); Errors = $errors.GetAwaiter().GetResult() }
    } finally { $process.Dispose() }
}

function Test-Python([string]$Executable, [string]$ExpectedVersion = '') {
    if (-not [IO.File]::Exists($Executable) -or $Executable -match '(?i)[\\/]WindowsApps[\\/]') { return $false }
    try {
        $code = "import sys,json,hashlib,zipfile,xml.etree.ElementTree,subprocess,pathlib; print(json.dumps({'version':list(sys.version_info[:3]),'ok':sys.version_info>=(3,10)}))"
        $check = Invoke-ToolCheck $Executable @('-B', '-I', '-S', '-X', 'utf8', '-c', $code)
        if ($check.ExitCode -ne 0) { return $false }
        $report = $check.Output.Trim() | ConvertFrom-Json
        if ($report.ok -ne $true) { return $false }
        return (-not $ExpectedVersion -or (($report.version -join '.') -eq $ExpectedVersion))
    } catch { return $false }
}

function Test-Adb([string]$Executable, [string]$ExpectedVersion = '') {
    if (-not [IO.File]::Exists($Executable)) { return $false }
    try {
        $check = Invoke-ToolCheck $Executable @('version')
        if ($check.ExitCode -ne 0 -or $check.Output -notmatch '(?m)^Android Debug Bridge version 1\.0\.41\s*$') { return $false }
        $release = [regex]::Match($check.Output, '(?m)^Version (\d+)\.\d+\.\d+(?:-|\s|$)')
        if (-not $release.Success -or [int]$release.Groups[1].Value -lt 29) { return $false }
        return (-not $ExpectedVersion -or $check.Output -match ('(?m)^Version ' + [regex]::Escape($ExpectedVersion) + '(?:-|\s|$)'))
    } catch { return $false }
}

function Get-PathTools([string[]]$Names) {
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $Names) {
        foreach ($command in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
            if ($command.Source -and $seen.Add($command.Source)) { $command.Source }
        }
    }
}

function Find-Python {
    foreach ($candidate in @(Get-PathTools @('python3.exe', 'python.exe'))) {
        if (Test-Python $candidate) { return $candidate }
    }
    $programs = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if ([IO.Directory]::Exists($programs)) {
        foreach ($directory in @(Get-ChildItem -LiteralPath $programs -Directory | Sort-Object Name -Descending)) {
            $candidate = Join-Path $directory.FullName 'python.exe'
            if (Test-Python $candidate) { return $candidate }
        }
    }
    return $null
}

function Find-Adb([string]$Explicit) {
    if ($Explicit) {
        $candidate = [IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Adb $candidate)) { throw 'The supplied --adb executable did not pass its version check.' }
        return $candidate
    }
    foreach ($candidate in @(Get-PathTools @('adb.exe'))) {
        if (Test-Adb $candidate) { return $candidate }
    }
    $sdkAdb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
    if (Test-Adb $sdkAdb) { return $sdkAdb }
    return $null
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-NormalDirectory([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The private tool cache must be an ordinary directory, not a symbolic link or junction.'
    }
}

function Assert-DownloadUri([Uri]$Uri) {
    if ($Uri.Scheme -ne 'https' -or $Uri.UserInfo -or $Uri.Port -ne 443 -or
        $Uri.DnsSafeHost -notin @('www.python.org', 'dl.google.com')) {
        throw 'A tool download or redirect was outside the approved HTTPS servers.'
    }
}

function Get-VerifiedArchive($Asset, [string]$Downloads) {
    if ($Asset.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'The tool manifest has no valid pinned SHA-256.' }
    $uri = [Uri]$Asset.url
    Assert-DownloadUri $uri
    $archive = Join-Path $Downloads ($Asset.sha256 + '.zip')
    if ([IO.File]::Exists($archive) -and (Get-FileSha256 $archive) -eq $Asset.sha256) { return $archive }
    if ([IO.File]::Exists($archive)) { [IO.File]::Delete($archive) }
    $partial = Join-Path $Downloads ([Guid]::NewGuid().ToString('N') + '.download')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        for ($redirect = 0; $redirect -le 5; $redirect++) {
            Assert-DownloadUri $uri
            $request = [Net.HttpWebRequest]::Create($uri)
            $request.AllowAutoRedirect = $false
            $request.Timeout = 30000
            $request.ReadWriteTimeout = 30000
            $request.UserAgent = 'HiBreak-Auto-Scale-Setup/1.1'
            $response = $null
            try {
                $response = $request.GetResponse()
                if ([int]$response.StatusCode -in @(301, 302, 303, 307, 308)) {
                    if (-not $response.Headers['Location']) { throw 'The tool download returned an empty redirect.' }
                    $uri = New-Object Uri($uri, $response.Headers['Location'])
                    continue
                }
                if ([int]$response.StatusCode -ne 200 -or $response.ContentLength -gt 104857600) {
                    throw 'The tool download returned an unexpected response or file size.'
                }
                $inputStream = $response.GetResponseStream()
                $outputStream = New-Object IO.FileStream($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $buffer = New-Object byte[] 65536
                    [long]$total = 0
                    while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $total += $count
                        if ($total -gt 104857600) { throw 'The tool archive exceeded its size limit.' }
                        $outputStream.Write($buffer, 0, $count)
                    }
                    $outputStream.Flush($true)
                } finally { $outputStream.Dispose(); $inputStream.Dispose() }
                if ((Get-FileSha256 $partial) -ne $Asset.sha256) { throw 'Tool checksum mismatch. Nothing from this archive was executed.' }
                [IO.File]::Move($partial, $archive)
                return $archive
            } finally { if ($response) { $response.Dispose() } }
        }
        throw 'The tool download returned too many redirects.'
    } finally { if ([IO.File]::Exists($partial)) { [IO.File]::Delete($partial) } }
}

function Get-SafeArchivePath([string]$Root, [string]$Name) {
    $normalized = $Name.Replace('\', '/')
    if (-not $normalized -or $normalized.StartsWith('/') -or $normalized -match '[:\x00-\x1f<>"|?*]') {
        throw 'The tool ZIP contains an unsafe absolute, device, or special path.'
    }
    $parts = $normalized.TrimEnd('/').Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.', '..') -or $part -match '[. ]$' -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw 'The tool ZIP contains an unsafe path component.'
        }
    }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $destination = [IO.Path]::GetFullPath((Join-Path $Root ($normalized.Replace('/', [IO.Path]::DirectorySeparatorChar))))
    if (-not $destination.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The tool ZIP attempted to leave its staging directory.'
    }
    return $destination
}

function Expand-CheckedZip([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Assert-NormalDirectory $Destination
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -gt 10000) { throw 'The tool ZIP contains too many entries.' }
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $entries = New-Object System.Collections.ArrayList
        [long]$total = 0
        foreach ($entry in $zip.Entries) {
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000 -or ($entry.ExternalAttributes -band 1024)) {
                throw 'Symbolic links and reparse points are not allowed in a tool ZIP.'
            }
            $target = Get-SafeArchivePath $Destination $entry.FullName
            if (-not $seen.Add($target)) { throw 'Duplicate or case-conflicting paths are not allowed in a tool ZIP.' }
            $total += $entry.Length
            if ($entry.Length -gt 268435456 -or $total -gt 536870912) { throw 'The expanded tool ZIP exceeded its size limit.' }
            [void]$entries.Add([pscustomobject]@{ Entry = $entry; Target = $target })
        }
        foreach ($item in $entries) {
            if ($item.Entry.FullName.EndsWith('/') -or $item.Entry.FullName.EndsWith('\')) {
                [void][IO.Directory]::CreateDirectory($item.Target)
                continue
            }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($item.Target))
            $inputStream = $item.Entry.Open()
            $outputStream = New-Object IO.FileStream($item.Target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $inputStream.CopyTo($outputStream); $outputStream.Flush($true) }
            finally { $outputStream.Dispose(); $inputStream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Test-InstalledCache([string]$Folder, [string]$ArchiveHash) {
    try {
        Assert-NormalDirectory $Folder
        $marker = Get-Content -LiteralPath (Join-Path $Folder 'hibreak-tool.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($marker.archive_sha256 -ne $ArchiveHash -or -not $marker.files -or $marker.files.Count -gt 10000) { return $false }
        foreach ($file in $marker.files) {
            $path = Get-SafeArchivePath $Folder $file.path
            if (-not [IO.File]::Exists($path) -or ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                $file.sha256 -notmatch '^[a-f0-9]{64}$' -or (Get-FileSha256 $path) -ne $file.sha256) { return $false }
        }
        return $true
    } catch { return $false }
}

function Install-PortableTool($Asset, [string]$Name, [string]$Cache, [string]$Downloads, [string[]]$RequiredFiles) {
    $target = Join-Path $Cache $Name
    if ((Test-Path -LiteralPath $target) -and (Test-InstalledCache $target $Asset.sha256)) { return $target }
    if (Test-Path -LiteralPath $target) {
        Assert-NormalDirectory $target
        [IO.Directory]::Move($target, ($target + '.invalid-' + [Guid]::NewGuid().ToString('N')))
    }
    Write-Host ('Downloading and verifying ' + $Name + '...')
    $archive = Get-VerifiedArchive $Asset $Downloads
    $stage = Join-Path $Cache ('.staging-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    try {
        Expand-CheckedZip $archive $stage
        foreach ($required in $RequiredFiles) {
            if (-not [IO.File]::Exists((Get-SafeArchivePath $stage $required))) { throw ('The verified archive is missing ' + $required) }
        }
        $files = @()
        foreach ($file in @(Get-ChildItem -LiteralPath $stage -File -Recurse)) {
            $relative = $file.FullName.Substring($stage.Length + 1).Replace('\', '/')
            $files += @{ path = $relative; sha256 = Get-FileSha256 $file.FullName }
        }
        $marker = @{ archive_sha256 = $Asset.sha256; url = $Asset.url; installed_utc = [DateTime]::UtcNow.ToString('o'); files = $files }
        [IO.File]::WriteAllText((Join-Path $stage 'hibreak-tool.json'), ($marker | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
        [IO.Directory]::Move($stage, $target)
        return $target
    } finally { if ([IO.Directory]::Exists($stage)) { Remove-Item -LiteralPath $stage -Recurse -Force } }
}

function Enter-ToolLock([string]$Cache) {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    $printed = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try { return New-Object IO.FileStream((Join-Path $Cache 'bootstrap.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch [IO.IOException] {
            if (-not $printed) { Write-Host 'Another HiBreak setup is preparing tools. Waiting for it to finish...'; $printed = $true }
            Start-Sleep -Milliseconds 300
        }
    }
    throw 'Another setup still holds the private tool cache. Close it and run this setup again.'
}

function Confirm-ToolLicenses([string]$Cache, [string]$KitDirectory, [bool]$ExplicitAcceptance) {
    $license = Join-Path $KitDirectory 'ANDROID-SDK-LICENSE.txt'
    if (-not [IO.File]::Exists($license)) { throw 'The complete kit is required; ANDROID-SDK-LICENSE.txt is missing.' }
    $licenseHash = Get-FileSha256 $license
    $path = Join-Path $Cache 'android-sdk-license.accepted.json'
    if ([IO.File]::Exists($path)) {
        try {
            $saved = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($saved.accepted -eq $true -and $saved.license_sha256 -eq $licenseHash) { return }
        } catch { }
    }
    Write-Host 'Missing tools will be downloaded from the official Python and Google servers.'
    Write-Host 'Python PSF license: https://docs.python.org/3/license.html'
    Write-Host 'Android SDK terms: https://developer.android.com/studio/terms'
    Write-Host ('Full included Android SDK terms: ' + $license)
    Write-Host ('Android SDK terms SHA-256: ' + $licenseHash)
    Write-Host 'Downloaded packages retain their LICENSE.txt / NOTICE.txt files.'
    if (-not $ExplicitAcceptance) {
        if ([Console]::IsInputRedirected) { throw 'Review the included Android SDK terms, then rerun with --accept-tool-licenses if you accept them.' }
        if ((Read-Host 'Type agree to accept the Android SDK terms and continue').Trim().ToLowerInvariant() -ne 'agree') { throw 'Android SDK terms were not accepted; no missing tool was downloaded.' }
    }
    $value = @{ accepted = $true; license_sha256 = $licenseHash; license_file = 'ANDROID-SDK-LICENSE.txt'; accepted_utc = [DateTime]::UtcNow.ToString('o') }
    $temporary = Join-Path $Cache ([Guid]::NewGuid().ToString('N') + '.acceptance.tmp')
    $previous = Join-Path $Cache ([Guid]::NewGuid().ToString('N') + '.acceptance.previous')
    try {
        [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($path)) { [IO.File]::Replace($temporary, $path, $previous) }
        else { [IO.File]::Move($temporary, $path) }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
        if ([IO.File]::Exists($previous)) { [IO.File]::Delete($previous) }
    }
}

function Invoke-WindowsBootstrap([string[]]$Arguments, [string]$KitDirectory) {
    if ($Arguments -contains '--bootstrap-help') {
        Write-Host 'Double-click Setup-on-Windows.cmd after unzipping the complete kit.'
        Write-Host 'Compatible existing Python 3.10+ / ADB are reused; otherwise private verified portable copies are downloaded.'
        Write-Host '--accept-tool-licenses accepts the included Android SDK terms when Google tools need downloading.'
        Write-Host '--check-dependencies prepares and verifies tools without contacting a phone.'
        Write-Host 'All other options are passed to the phone setup. --adb and --state-dir override the automatic choices.'
        return 0
    }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not $env:LOCALAPPDATA) { throw 'Use Setup-on-Mac.command or Setup-on-Linux.sh on this operating system.' }
    $manifestPath = Join-Path $KitDirectory 'runtime-downloads.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.'python-windows'.version -notmatch '^3\.\d+\.\d+$' -or $manifest.adb.version -notmatch '^\d+\.\d+\.\d+$') { throw 'The runtime download manifest is incomplete.' }
    $accept = $Arguments -contains '--accept-tool-licenses'
    $dependenciesOnly = $Arguments -contains '--check-dependencies'
    $forward = @($Arguments | Where-Object { $_ -ne '--accept-tool-licenses' -and $_ -ne '--check-dependencies' })
    $explicitAdb = ''
    $hasRecords = $false
    for ($i = 0; $i -lt $forward.Count; $i++) {
        if ($forward[$i] -eq '--adb') {
            if ($i + 1 -ge $forward.Count) { throw '--adb needs an executable path.' }
            $explicitAdb = $forward[$i + 1]
        } elseif ($forward[$i].StartsWith('--adb=')) { $explicitAdb = $forward[$i].Substring(6) }
        if ($forward[$i] -eq '--state-dir' -or $forward[$i].StartsWith('--state-dir=')) { $hasRecords = $true }
    }
    $cache = Join-Path $env:LOCALAPPDATA 'HiBreakAutoScale\tools'
    [void][IO.Directory]::CreateDirectory($cache)
    Assert-NormalDirectory $cache
    $downloads = Join-Path $cache 'downloads'
    [void][IO.Directory]::CreateDirectory($downloads)
    Assert-NormalDirectory $downloads
    $lock = Enter-ToolLock $cache
    try {
        $python = Find-Python
        $adb = Find-Adb $explicitAdb
        $architecture = $env:PROCESSOR_ARCHITECTURE
        if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
        if ($architecture -ieq 'AMD64') { $pythonArch = 'amd64' }
        elseif ($architecture -ieq 'ARM64') { $pythonArch = 'arm64' }
        else { throw 'The bundled portable Python supports 64-bit Intel/AMD and ARM64 Windows. This Windows architecture is unsupported.' }
        if (-not $python) {
            $pythonName = 'python-' + $manifest.'python-windows'.version + '-' + $pythonArch
            $pythonFolder = Join-Path $cache $pythonName
            if (Test-InstalledCache $pythonFolder $manifest.'python-windows'.$pythonArch.sha256) {
                $candidate = Join-Path $pythonFolder 'python.exe'
                if (Test-Python $candidate $manifest.'python-windows'.version) { $python = $candidate }
            }
        }
        if (-not $adb) {
            $adbName = 'platform-tools-' + $manifest.adb.version + '-windows'
            $adbFolder = Join-Path $cache $adbName
            if (Test-InstalledCache $adbFolder $manifest.adb.windows.sha256) {
                $candidate = Join-Path $adbFolder 'platform-tools\adb.exe'
                if (Test-Adb $candidate $manifest.adb.version) { $adb = $candidate }
            }
        }
        if (-not $adb) { Confirm-ToolLicenses $cache $KitDirectory $accept }
        if (-not $python) {
            $pythonStem = 'python' + (($manifest.'python-windows'.version -split '\.')[0..1] -join '')
            $pythonFolder = Install-PortableTool $manifest.'python-windows'.$pythonArch $pythonName $cache $downloads @('python.exe', ($pythonStem + '.dll'), ($pythonStem + '.zip'), ($pythonStem + '._pth'), 'LICENSE.txt')
            $python = Join-Path $pythonFolder 'python.exe'
            if (-not (Test-Python $python $manifest.'python-windows'.version)) { throw 'The verified portable Python did not run. Windows 10 or newer is required; keep the full extracted package together.' }
        }
        if (-not $adb) {
            $adbFolder = Install-PortableTool $manifest.adb.windows $adbName $cache $downloads @('platform-tools/adb.exe', 'platform-tools/AdbWinApi.dll', 'platform-tools/AdbWinUsbApi.dll', 'platform-tools/source.properties', 'platform-tools/NOTICE.txt')
            $adb = Join-Path $adbFolder 'platform-tools\adb.exe'
            if (-not (Test-Adb $adb $manifest.adb.version)) { throw 'The verified Google Platform-Tools did not run on this Windows installation.' }
        }
    } finally { $lock.Dispose() }
    if ($dependenciesOnly) {
        Write-Host ('Python: ' + $python)
        Write-Host ('ADB: ' + $adb)
        Write-Host 'Both tools passed their startup checks. No phone was contacted.'
        return 0
    }
    if (-not $explicitAdb) { $forward = @('--adb', $adb) + $forward }
    if (-not $hasRecords) {
        $records = Join-Path $env:LOCALAPPDATA 'HiBreakAutoScale\setup-records'
        [void][IO.Directory]::CreateDirectory($records)
        Assert-NormalDirectory $records
        $forward = @('--state-dir', $records) + $forward
    }
    $entry = $null
    foreach ($name in @('setup.py', 'commonsetup.py', 'setup_on_mac.py')) {
        $candidate = Join-Path $KitDirectory $name
        if ([IO.File]::Exists($candidate)) { $entry = $candidate; break }
    }
    if (-not $entry) { throw 'The complete unzipped kit is required; its setup Python entry point is missing.' }
    Write-Host 'Tools are ready. Unlock the HiBreak and accept its USB debugging authorization prompt.'
    Write-Host 'If Windows sees no phone, a compatible manufacturer USB driver may need manual installation.'
    Write-Host 'Driver help: https://developer.android.com/studio/run/oem-usb'
    $code = "import runpy,sys;from pathlib import Path;p=Path(sys.argv[1]).resolve();sys.path.insert(0,str(p.parent));sys.argv=[str(p),*sys.argv[2:]];runpy.run_path(str(p),run_name='__main__')"
    $process = New-ToolProcess $python (@('-B', '-I', '-S', '-X', 'utf8', '-c', $code, $entry) + $forward) $false
    try { [void]$process.Start(); $process.WaitForExit(); return $process.ExitCode }
    finally { $process.Dispose() }
}

# The library-only flag is used for host fixture tests and never runs a tool.
if ($args -contains '--library-only') { return }
try { exit (Invoke-WindowsBootstrap @($args) $PSScriptRoot) }
catch { Write-Host ('Setup stopped: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }
