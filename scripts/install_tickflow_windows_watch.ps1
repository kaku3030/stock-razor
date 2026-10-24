param(
    [Parameter(Mandatory=$true)][string]$ExpectedSha,
    [string]$Python = (Get-Command python -ErrorAction Stop).Source,
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'StockRazor\TickFlowHalfHour')
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$sha = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sha -ne $ExpectedSha -or $sha -notmatch '^[0-9a-f]{40}$') { throw 'SOURCE_SHA_MISMATCH' }
$dirty = & git -C $repo status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'SOURCE_DIRTY' }
& $Python -c 'import tickflow, win32cred, exchange_calendars; assert tuple(map(int,tickflow.__version__.split(chr(46)))) == (0,1,25)'
if ($LASTEXITCODE -ne 0) { throw 'SDK_OR_CALENDAR_UNAVAILABLE' }
New-Item -ItemType Directory -Force $Root | Out-Null
$taskName = 'STOCK_RAZOR_TickFlow_Desktop_30m_ReadOnly'
$prior = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($prior -and $prior.State -eq 'Running') { throw 'EXISTING_AUDIT_RUNNING' }
$backup = Join-Path $Root ('backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory $backup | Out-Null
if ($prior) { Export-ScheduledTask -TaskName $taskName | Set-Content (Join-Path $backup 'task.xml') -Encoding UTF8 }
foreach ($name in @('audit_tickflow_windows_readonly.py','half_hour_check.ps1','deployment.json','run_tickflow_windows_watch.py')) {
    $path = Join-Path $Root $name
    if (Test-Path $path) { Copy-Item $path $backup }
}
$files = @{}
foreach ($name in @('audit_tickflow_windows_readonly.py','run_tickflow_windows_watch.py')) {
    Copy-Item (Join-Path $PSScriptRoot $name) (Join-Path $Root $name) -Force
    $files[$name] = (Get-FileHash (Join-Path $Root $name) -Algorithm SHA256).Hash.ToLower()
}
$manifest = @{source_sha=$sha; installed_at_utc=(Get-Date).ToUniversalTime().ToString('o'); files=$files}
[IO.File]::WriteAllText((Join-Path $Root 'deployment.json'), ($manifest | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
$watch = Join-Path $Root 'run_tickflow_windows_watch.py'
$arguments = '"' + $watch + '" --root "' + $Root + '" --execute'
$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 2)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Hybrid V1.0 Windows TickFlow only; 2m calendar-gated research, no trading. Legacy task name retained.' -Force | Out-Null
& $Python $watch --root $Root --execute
if ($LASTEXITCODE -ne 0) { throw 'INITIAL_WATCH_BLOCKED_INSPECT_PRIVATE_RECEIPT' }
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime,LastTaskResult
