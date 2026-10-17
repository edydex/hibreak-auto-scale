#requires -version 5.1
param([string]$PythonExecutable = '')
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$KitRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $KitRoot 'bootstrap-windows.ps1') --library-only
$script:Checks = 0
function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('FAILED: ' + $Message) }
    $script:Checks++
}
function Reject([scriptblock]$Action, [string]$Message) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    Check $failed $Message
}
function New-FixtureZip([string]$Path, [object[]]$Entries) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($item in $Entries) {
            $entry = $zip.CreateEntry($item.Name)
            if ($item.ContainsKey('Attributes')) { $entry.ExternalAttributes = $item.Attributes }
            $writer = New-Object IO.StreamWriter($entry.Open(), (New-Object Text.UTF8Encoding($false)))
            try { $writer.Write($item.Content) } finally { $writer.Dispose() }
        }
    } finally { $zip.Dispose() }
}

$temporary = Join-Path $PSScriptRoot ('fixture-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temporary)
try {
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $KitRoot 'bootstrap-windows.ps1'), [ref]$null, [ref]$errors)
    Check (-not $errors) 'Production PowerShell script parses.'
    Check ((Quote-WindowsArgument '') -eq '""') 'Empty native argument is retained.'
    Check ((Quote-WindowsArgument 'plain') -eq 'plain') 'Plain native argument stays plain.'
    Check ((Quote-WindowsArgument 'a b') -eq '"a b"') 'Spaces are quoted.'
    Check ((Quote-WindowsArgument 'x"y') -eq '"x\"y"') 'Embedded quote is escaped.'
    Check ((Quote-WindowsArgument 'C:\Users\A B\') -eq '"C:\Users\A B\\"') 'Trailing backslash is doubled inside quotes.'
    Check ((Quote-WindowsArgument 'x\"y') -eq '"x\\\"y"') 'Backslashes before a quote are doubled.'
    Check ((Quote-WindowsArgument '&;$()') -eq '&;$()') 'Shell metacharacters remain data for a direct process.'
    $unicode = [string][char]0x0424 + ' & files'
    Check ((Quote-WindowsArgument $unicode) -eq ('"' + $unicode + '"')) 'Unicode paths are preserved.'

    $root = Join-Path $temporary 'root'
    [void][IO.Directory]::CreateDirectory($root)
    $normal = Get-SafeArchivePath $root 'folder/file.txt'
    Check ($normal.StartsWith(([IO.Path]::GetFullPath($root) + [IO.Path]::DirectorySeparatorChar))) 'Normal archive path stays under root.'
    foreach ($bad in @('../escape', 'folder/../escape', '\\server\file', 'C:/escape', '/escape', 'file:ads', 'folder\\..\\escape', 'AUX.txt', 'folder/COM1.log', 'trailing.', 'trailing ', 'a//b', './file', 'file?')) {
        Reject { Get-SafeArchivePath $root $bad } ('Unsafe ZIP path refused: ' + $bad)
    }
    Assert-DownloadUri ([Uri]'https://www.python.org/ftp/example.zip')
    Assert-DownloadUri ([Uri]'https://dl.google.com/android/example.zip')
    $script:Checks += 2
    foreach ($bad in @('http://www.python.org/file', 'https://evil.example/file', 'https://www.python.org.evil.example/file', 'https://user@www.python.org/file', 'https://www.python.org:444/file')) {
        Reject { Assert-DownloadUri ([Uri]$bad) } ('Unapproved download URI refused: ' + $bad)
    }

    $good = Join-Path $temporary 'good.zip'
    New-FixtureZip $good @(@{ Name = 'folder/data.txt'; Content = 'fixture payload' }, @{ Name = 'LICENSE.txt'; Content = 'fixture license' })
    $extract = Join-Path $temporary 'extract'
    [void][IO.Directory]::CreateDirectory($extract)
    Expand-CheckedZip $good $extract
    Check (([IO.File]::ReadAllText((Join-Path $extract 'folder/data.txt'))) -eq 'fixture payload') 'Valid ZIP payload extracted.'
    Check ([IO.File]::Exists((Join-Path $extract 'LICENSE.txt'))) 'Archive license remains present.'
    $unsafe = @(
        @(@{ Name = '../outside'; Content = 'no' }),
        @(@{ Name = 'a.txt'; Content = 'one' }, @{ Name = 'A.TXT'; Content = 'two' }),
        @(@{ Name = 'link'; Content = '../outside'; Attributes = [Convert]::ToInt32('A1FF0000', 16) })
    )
    $index = 0
    foreach ($entries in $unsafe) {
        $archive = Join-Path $temporary ('unsafe-' + $index + '.zip')
        New-FixtureZip $archive $entries
        $destination = Join-Path $temporary ('unsafe-extract-' + $index)
        [void][IO.Directory]::CreateDirectory($destination)
        Reject { Expand-CheckedZip $archive $destination } ('Unsafe ZIP fixture ' + $index + ' was refused.')
        $index++
    }
    Check (-not [IO.File]::Exists((Join-Path $temporary 'outside'))) 'Unsafe ZIP never wrote outside its root.'

    $cache = Join-Path $temporary 'cache'
    $downloads = Join-Path $cache 'downloads'
    [void][IO.Directory]::CreateDirectory($downloads)
    $hash = Get-FileSha256 $good
    Copy-Item -LiteralPath $good -Destination (Join-Path $downloads ($hash + '.zip'))
    $asset = [pscustomobject]@{ url = 'https://www.python.org/fixture.zip'; sha256 = $hash }
    Check ((Get-VerifiedArchive $asset $downloads) -eq (Join-Path $downloads ($hash + '.zip'))) 'Matching cached pinned ZIP is reused without a network call.'
    Reject { Get-VerifiedArchive ([pscustomobject]@{ url = 'https://www.python.org/fixture.zip'; sha256 = 'not-a-hash' }) $downloads } 'Missing pinned checksum refuses before download.'
    $installed = Install-PortableTool $asset 'fixture-tool' $cache $downloads @('folder/data.txt', 'LICENSE.txt')
    Check (Test-InstalledCache $installed $hash) 'Installed cache marker and payload hashes verify.'
    Check ((Install-PortableTool $asset 'fixture-tool' $cache $downloads @('folder/data.txt')) -eq $installed) 'Valid installation is idempotent.'
    [IO.File]::WriteAllText((Join-Path $installed 'folder/data.txt'), 'modified')
    Check (-not (Test-InstalledCache $installed $hash)) 'Edited cache payload is detected.'
    $reinstalled = Install-PortableTool $asset 'fixture-tool' $cache $downloads @('folder/data.txt', 'LICENSE.txt')
    Check (Test-InstalledCache $reinstalled $hash) 'Invalid cache is replaced from verified ZIP.'
    Check (@(Get-ChildItem -LiteralPath $cache -Directory -Filter 'fixture-tool.invalid-*').Count -eq 1) 'Invalid cache was retained under a distinct name.'
    Check (@(Get-ChildItem -LiteralPath $cache -Directory -Filter '.staging-*').Count -eq 0) 'No staging directory remains after success.'
    Reject { Install-PortableTool $asset 'missing-required-tool' $cache $downloads @('missing.exe') } 'Missing required file refuses installation.'
    Check (-not [IO.Directory]::Exists((Join-Path $cache 'missing-required-tool'))) 'Failed staging was never published.'
    Check (@(Get-ChildItem -LiteralPath $cache -Directory -Filter '.staging-*').Count -eq 0) 'Failed staging directory is removed.'

    $lock = Enter-ToolLock $cache
    try {
        Reject { $other = New-Object IO.FileStream((Join-Path $cache 'bootstrap.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None); $other.Dispose() } 'Cache lock refuses a simultaneous writer.'
    } finally { $lock.Dispose() }
    $lock = Enter-ToolLock $cache
    $lock.Dispose()
    $script:Checks++

    $licenseKit = Join-Path $temporary 'license-kit'
    [void][IO.Directory]::CreateDirectory($licenseKit)
    $licensePath = Join-Path $licenseKit 'ANDROID-SDK-LICENSE.txt'
    [IO.File]::WriteAllText($licensePath, 'fixture SDK terms version one')
    Confirm-ToolLicenses $cache $licenseKit $true
    $acceptancePath = Join-Path $cache 'android-sdk-license.accepted.json'
    $acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json
    Check ($acceptance.accepted -eq $true) 'Explicit SDK acceptance is recorded.'
    Check ($acceptance.license_sha256 -eq (Get-FileSha256 $licensePath)) 'SDK acceptance is bound to the exact included license hash.'
    Confirm-ToolLicenses $cache $licenseKit $false
    $script:Checks++
    [IO.File]::WriteAllText($licensePath, 'fixture SDK terms version two')
    Reject { Confirm-ToolLicenses $cache $licenseKit $false } 'Changed SDK terms cannot reuse old acceptance in a noninteractive test.'
    Confirm-ToolLicenses $cache $licenseKit $true
    $acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json
    Check ($acceptance.license_sha256 -eq (Get-FileSha256 $licensePath)) 'Fresh acceptance replaces the old terms hash atomically.'
    Check (@(Get-ChildItem -LiteralPath $cache -File -Filter '*.acceptance.tmp').Count -eq 0) 'No temporary acceptance file remains.'

    if ($PythonExecutable) {
        $wanted = @('one', 'C:\Users\A B\', 'x"y', $unicode, 'semi;$(Get-Process)', '', 'trailing\')
        # PS5.1 and PS7 enumerate a top-level ConvertFrom-Json array differently.
        # A named array property avoids testing that host-shell difference while
        # retaining the exact native argv/empty-string contract.
        $check = Invoke-ToolCheck $PythonExecutable (@('-I', '-S', '-c', 'import json,sys;print(json.dumps({"argv":sys.argv[1:]}))') + $wanted)
        Check ($check.ExitCode -eq 0) 'Direct process argument fixture ran.'
        $decoded = $check.Output | ConvertFrom-Json
        $observed = @($decoded.argv)
        Check ($observed.Count -eq $wanted.Count) ('Direct process retains every argument. Synthetic response: ' + $check.Output.Trim())
        for ($i = 0; $i -lt $wanted.Count; $i++) { Check ($observed[$i] -ceq $wanted[$i]) ('Native argument roundtrip ' + $i) }
        Check (Test-Python $PythonExecutable) 'Existing compatible Python validates with isolated standard-library imports.'
    }
    Write-Host ('PASS ' + $script:Checks + ' PowerShell host fixture checks. No phone command was run.')
} finally { if ([IO.Directory]::Exists($temporary)) { Remove-Item -LiteralPath $temporary -Recurse -Force } }
