param(
    [string]$DatabasePath = "data/bank.db",
    [ValidateSet("alice", "bob")]
    [string]$User = "alice"
)

# 不安装依赖、不重置数据库。只寻找能运行标准库原型的 Python 3.10+。
$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $PSScriptRoot
$runtimePython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonCandidates = @()
if (Test-Path -LiteralPath $runtimePython -PathType Leaf) {
    $pythonCandidates += @{ Path = $runtimePython; Arguments = @() }
}
foreach ($commandName in @("python.exe", "python3.exe", "py.exe")) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($command -and $command.Source -and $command.Source -notmatch "[\\/]WindowsApps[\\/]") {
        $prefixArguments = @()
        if ($commandName -eq "py.exe") { $prefixArguments = @("-3") }
        $pythonCandidates += @{ Path = $command.Source; Arguments = $prefixArguments }
    }
}
$pythonExecutable = $null
$pythonArguments = @()
foreach ($candidate in $pythonCandidates) {
    try {
        $versionArguments = @($candidate.Arguments) + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)")
        & $candidate.Path @versionArguments 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonExecutable = $candidate.Path
            $pythonArguments = @($candidate.Arguments)
            break
        }
    } catch {
        # Windows 的商店别名或未安装的 Python launcher 不作为有效运行环境。
    }
}
if (-not $pythonExecutable) {
    throw "未找到可运行的 Python 3.10+。请提供已有 Python 路径，或安装 Python 后再启动；本脚本不会自动安装。"
}

$previousEncoding = $env:PYTHONUTF8
$exitCode = 1
Push-Location -LiteralPath $projectDirectory
try {
    $env:PYTHONUTF8 = "1"
    Write-Host "启动模拟银行原型；已有数据库不会重置。"
    $launchArguments = $pythonArguments + @("-m", "src.main", "--db", $DatabasePath, "--user", $User)
    & $pythonExecutable @launchArguments
    $exitCode = $LASTEXITCODE
} finally {
    $env:PYTHONUTF8 = $previousEncoding
    Pop-Location
}
exit $exitCode
