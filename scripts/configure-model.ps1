# 地址、模型名和额度由队长选择。本脚本只配置，不发请求、不收费。
# 密钥通过隐藏输入读取，不要在聊天、命令参数或截图中提供。
$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $projectDirectory ".env"
$ignorePath = Join-Path $projectDirectory ".gitignore"
if (-not (Test-Path -LiteralPath $ignorePath) -or
    -not (Select-String -LiteralPath $ignorePath -Pattern '^\.env$' -Quiet)) {
    throw "项目 .gitignore 未声明忽略 .env，已停止。请先恢复忽略规则后配置密钥。"
}

$baseUrl = (Read-Host "服务商 OpenAI 兼容 API 基础地址（例如服务商给出的 https://主机/v1）").Trim()
$parsedUrl = $null
if (-not [Uri]::TryCreate($baseUrl, [UriKind]::Absolute, [ref]$parsedUrl) -or
    ($parsedUrl.Scheme -ne "https" -and -not ($parsedUrl.Scheme -eq "http" -and $parsedUrl.IsLoopback)) -or
    $parsedUrl.UserInfo -or $parsedUrl.Query -or $parsedUrl.Fragment -or $baseUrl -match '\s') {
    throw "地址无效：远端要求 HTTPS；HTTP 只允许本机回环；不能在地址中放用户名、密钥或查询参数。"
}
$modelName = (Read-Host "服务商确认可调用的模型名").Trim()
if (-not $modelName -or $modelName.Length -gt 200 -or $modelName -match '[\r\n\x00]') {
    throw "模型名不能为空，且不能含换行。"
}
$secureKey = Read-Host "API 密钥（隐藏输入，只写本机 .env）" -AsSecureString
$keyPointer = [IntPtr]::Zero
$plainKey = $null
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if (-not $plainKey -or $plainKey.Length -gt 4096 -or $plainKey -match '\s' -or $plainKey -match '[^\x00-\x7F]') {
        throw "密钥格式无效；不能为空或包含空白，请从服务商控制台重新复制。"
    }
    $environmentContents = "# 本机模型配置；已由 .gitignore 忽略。勿上传或分享。`n" +
        "FINTECH_MODEL_BASE_URL=$baseUrl`n" +
        "FINTECH_MODEL_NAME=$modelName`n" +
        "FINTECH_MODEL_API_KEY=$plainKey`n"
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($environmentPath, $environmentContents, $utf8WithoutBom)
    Write-Host "本机配置已保存到 .env；未展示密钥、未发请求。"
    Write-Host "请运行 scripts/start.ps1，再发送自然语言验证。服务商须支持 Chat Completions JSON 模式。"
    Write-Host "若已有同名 FINTECH_MODEL_* 环境变量，它们会优先于 .env；请在本机清理旧配置。"
} finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $plainKey = $null
    $environmentContents = $null
    if ($secureKey) { $secureKey.Dispose() }
}
