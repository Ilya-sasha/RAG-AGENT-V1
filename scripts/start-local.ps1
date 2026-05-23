param(
    [string]$PythonExe = "C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe",
    [string]$ListenHost,
    [Nullable[int]]$Port,
    [string]$DbUrl,
    [string]$EmbeddingModelRoot,
    [string]$ModelBaseUrl,
    [string]$ModelApiKey,
    [string]$ModelName,
    [Nullable[double]]$ModelTimeoutSeconds
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedHost = if ($PSBoundParameters.ContainsKey("ListenHost")) { $ListenHost } elseif ($env:AGENT_RUNTIME_HOST) { $env:AGENT_RUNTIME_HOST } else { "127.0.0.1" }
$resolvedPort = if ($PSBoundParameters.ContainsKey("Port")) { $Port } elseif ($env:AGENT_RUNTIME_PORT) { $env:AGENT_RUNTIME_PORT } else { 8000 }
$resolvedDbUrl = if ($PSBoundParameters.ContainsKey("DbUrl")) { $DbUrl } elseif ($env:AGENT_RUNTIME_DB_URL) { $env:AGENT_RUNTIME_DB_URL } else { "sqlite+aiosqlite:///./runtime.db" }
$resolvedEmbeddingModelRoot = if ($PSBoundParameters.ContainsKey("EmbeddingModelRoot")) { $EmbeddingModelRoot } elseif ($env:AGENT_RUNTIME_EMBEDDING_MODEL_ROOT) { $env:AGENT_RUNTIME_EMBEDDING_MODEL_ROOT } else { "C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base" }
$resolvedModelBaseUrl = if ($PSBoundParameters.ContainsKey("ModelBaseUrl")) { $ModelBaseUrl } elseif ($env:AGENT_RUNTIME_MODEL_BASE_URL) { $env:AGENT_RUNTIME_MODEL_BASE_URL } else { "https://api.deepseek.com" }
$resolvedModelApiKey = if ($PSBoundParameters.ContainsKey("ModelApiKey")) { $ModelApiKey } elseif ($env:AGENT_RUNTIME_MODEL_API_KEY) { $env:AGENT_RUNTIME_MODEL_API_KEY } else { $null }
$resolvedModelName = if ($PSBoundParameters.ContainsKey("ModelName")) { $ModelName } elseif ($env:AGENT_RUNTIME_MODEL_NAME) { $env:AGENT_RUNTIME_MODEL_NAME } else { "deepseek-v4-flash" }
$resolvedModelTimeoutSeconds = if ($PSBoundParameters.ContainsKey("ModelTimeoutSeconds")) { $ModelTimeoutSeconds } elseif ($env:AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS) { $env:AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS } else { 60 }

$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:AGENT_RUNTIME_DB_URL = $resolvedDbUrl
$env:AGENT_RUNTIME_EMBEDDING_MODEL_ROOT = $resolvedEmbeddingModelRoot
$env:AGENT_RUNTIME_MODEL_BASE_URL = $resolvedModelBaseUrl
$env:AGENT_RUNTIME_MODEL_NAME = $resolvedModelName
$env:AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS = $resolvedModelTimeoutSeconds
if ($null -ne $resolvedModelApiKey -and $resolvedModelApiKey -ne "") {
    $env:AGENT_RUNTIME_MODEL_API_KEY = $resolvedModelApiKey
}

$apiKeyPreview = if ($null -ne $resolvedModelApiKey -and $resolvedModelApiKey -ne "") {
    $prefixLength = [Math]::Min(10, $resolvedModelApiKey.Length)
    $resolvedModelApiKey.Substring(0, $prefixLength)
} else {
    "<empty>"
}

Write-Host "AGENT_RUNTIME_MODEL_BASE_URL=$resolvedModelBaseUrl"
Write-Host "AGENT_RUNTIME_MODEL_NAME=$resolvedModelName"
Write-Host "AGENT_RUNTIME_MODEL_API_KEY_PREFIX=$apiKeyPreview"
Write-Host "AGENT_RUNTIME_DB_URL=$resolvedDbUrl"
Write-Host "PYTHONIOENCODING=$env:PYTHONIOENCODING"
Write-Host "Starting server at http://$resolvedHost`:$resolvedPort"

Push-Location $repoRoot
try {
    $pythonExeForCmd = $PythonExe.Replace('"', '""')
    $uvicornCommand = "`"$pythonExeForCmd`" -m uvicorn agent_runtime.main:app --host $resolvedHost --port $resolvedPort"
    & cmd.exe /d /c $uvicornCommand
}
finally {
    Pop-Location
}
