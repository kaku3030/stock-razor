param(
    [string]$Round24Root = "C:\Users\77896\Documents\stock-razor-worktrees\round24-six-strategy-backtest-20261020",
    [string]$HistoricalCaptureRoot = "C:\Users\77896\Documents\Codex\2026-10-18\referenced-chatgpt-conversation-this-is-an-33\work\outputs\srvp_round4_20261018\capture",
    [string]$OneMinuteCapture = "C:\Users\77896\Documents\stock-razor-worktrees\round24-six-strategy-backtest-20261020\data\round24_s2_1m_opend_probe_20261020",
    [string]$PythonExe = "python",
    [switch]$PushResults
)

$ErrorActionPreference = "Stop"
$branchName = "research/round26-s2-candidate-20261020"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$round24Root = (Resolve-Path $Round24Root).Path
$historicalCaptureRoot = (Resolve-Path $HistoricalCaptureRoot).Path
$oneMinuteCapture = (Resolve-Path $OneMinuteCapture).Path
$expectedBranch = (& git -C $repoRoot branch --show-current).Trim()
if ($expectedBranch -ne $branchName) {
    throw "Run from branch $branchName (currently $expectedBranch)."
}
if (-not (Test-Path $historicalCaptureRoot -PathType Container)) {
    throw "Historical capture directory not found: $historicalCaptureRoot"
}
if (-not (Test-Path (Join-Path $round24Root "data") -PathType Container)) {
    throw "Round24 worktree data directory not found under $round24Root."
}

$symbols = @("AAPL", "AMD", "COHR", "NVDA", "QQQ", "TSLA")
$timeframes = @("D1", "1H", "15m", "5m")
$dataRoot = $historicalCaptureRoot
foreach ($symbol in $symbols) {
    $minuteName = "US_${symbol}_1m_qfq_rth_20190101_20261016.csv"
    if (-not (Test-Path (Join-Path $oneMinuteCapture $minuteName) -PathType Leaf)) {
        throw "Missing audited 1m file: $(Join-Path $oneMinuteCapture $minuteName)"
    }
    foreach ($tf in $timeframes) {
        $name = "US_${symbol}_${tf}_qfq_rth_20190101_20261016.csv"
        $sourceFile = Join-Path $dataRoot $name
        if (-not (Test-Path $sourceFile -PathType Leaf)) {
            throw "Missing local $symbol/$tf source file: $sourceFile"
        }
    }
}

$testPath = Join-Path $repoRoot "tests\research\test_round26_s2_candidate_replay.py"
$replayPath = Join-Path $repoRoot "tools\research\round26_s2_candidate_replay.py"
$outputPath = Join-Path $repoRoot "outputs\round26_s2_candidate_20261020"
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null

& $PythonExe -m py_compile $replayPath $testPath
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed ($LASTEXITCODE)." }
Push-Location $repoRoot
& $PythonExe -m unittest discover -v -s (Join-Path $repoRoot "tests\research") `
    -p "test_round26_s2_candidate_replay.py"
if ($LASTEXITCODE -ne 0) { throw "Round26 regression tests failed ($LASTEXITCODE)." }

$strictLog = Join-Path $outputPath "strict_full_data_blocked.log"
$strictArgs = @(
    $replayPath, "--capture", $dataRoot, "--one-minute-capture", $oneMinuteCapture,
    "--out", (Join-Path $outputPath "strict_full_data"),
    "--timestamp-zone", "America/New_York", "--bar-time-semantics", "end"
)
$priorErrorActionPreference = $ErrorActionPreference
try {
    # The strict run is expected to exit nonzero; keep PowerShell from converting
    # Python's stderr into a terminating native-command error before it is logged.
    $ErrorActionPreference = "Continue"
    $strictOutput = & $PythonExe @strictArgs 2>&1
    $strictExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $priorErrorActionPreference
}
$strictOutput | Out-String | Set-Content -LiteralPath $strictLog -Encoding utf8
if ($strictExit -eq 0) {
    throw "Strict run unexpectedly passed despite the audited COHR invalid OHLC bar; inspect the input lineage."
}
$strictText = $strictOutput -join "`n"
if ($strictText -notmatch "invalid OHLC" -or $strictText -notmatch "COHR") {
    throw "Strict run failed for a reason other than the known COHR data defect. See $strictLog"
}

$sensitivityArgs = @(
    $replayPath, "--capture", $dataRoot, "--one-minute-capture", $oneMinuteCapture,
    "--out", $outputPath,
    "--timestamp-zone", "America/New_York", "--bar-time-semantics", "end",
    "--exclude-invalid-session", "COHR:2025-02-11"
)
& $PythonExe @sensitivityArgs
if ($LASTEXITCODE -ne 0) { throw "Explicit COHR whole-session sensitivity replay failed ($LASTEXITCODE)." }

if ($PushResults) {
    $staged = (& git -C $repoRoot diff --cached --name-only)
    if ($staged) { throw "Staged changes already exist; refusing to include unrelated files in the result commit." }
    & git -C $repoRoot add -- outputs/round26_s2_candidate_20261020 tools/research/run_round26_s2_local.ps1
    if ($LASTEXITCODE -ne 0) { throw "Could not stage Round26 outputs and runner fix." }
    & git -C $repoRoot commit -m "results(research): run S2 candidate on local OpenD captures"
    if ($LASTEXITCODE -ne 0) { throw "Could not commit Round26 results." }
    & git -C $repoRoot push origin "HEAD:$branchName"
    if ($LASTEXITCODE -ne 0) { throw "Results commit exists locally but push failed." }
}

Pop-Location

Write-Host "Round26 sensitivity outputs: $outputPath"
Write-Host "Strict run blocker: $strictLog"
if (-not $PushResults) { Write-Host "Re-run with -PushResults to commit only Round26 output files to $branchName." }
