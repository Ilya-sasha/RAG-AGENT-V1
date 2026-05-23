param(
    [string]$PythonExe = "C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe",
    [ValidateSet("smoke", "workflow", "assistant", "release-assets", "runtime", "full", "perf")]
    [string]$Suite = "full",
    [string]$BaseTempDir,
    [string]$TempDir,
    [switch]$UseCacheProvider,
    [string[]]$ExtraPytestArgs = @()
)

function New-RegressionDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path -ErrorAction Stop | Out-Null
    return $Path
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultBaseTempDir = Join-Path (Join-Path $repoRoot ".pytest_tmp") $Suite
$fallbackBaseTempDir = Join-Path (Join-Path (Join-Path $repoRoot ".tmp") "pytest") $Suite
$resolvedBaseTempDir = if ($PSBoundParameters.ContainsKey("BaseTempDir")) {
    New-RegressionDirectory -Path $BaseTempDir
} else {
    try {
        New-RegressionDirectory -Path $defaultBaseTempDir
    }
    catch {
        Write-Warning "Unable to use default pytest base temp directory '$defaultBaseTempDir'. Falling back to '$fallbackBaseTempDir'."
        New-RegressionDirectory -Path $fallbackBaseTempDir
    }
}
$resolvedTempDir = if ($PSBoundParameters.ContainsKey("TempDir")) {
    New-RegressionDirectory -Path $TempDir
} else {
    New-RegressionDirectory -Path (Join-Path (Join-Path $repoRoot ".tmp") $Suite)
}

$env:TMP = $resolvedTempDir
$env:TEMP = $resolvedTempDir
$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$suiteTargets = switch ($Suite) {
    "smoke" {
        @("tests/integration/test_app_smoke.py")
    }
    "workflow" {
        @(
            "tests/unit/test_workflow_service.py",
            "tests/unit/test_workflow_observability_service.py",
            "tests/unit/test_tool_gateway.py",
            "tests/integration/test_workflows_api.py",
            "tests/integration/test_workflow_templates_api.py",
            "tests/integration/test_workflow_runs_api.py"
        )
    }
    "assistant" {
        @(
            "tests/unit/test_assistant_service.py",
            "tests/unit/test_retrieval_service.py",
            "tests/unit/test_knowledge_repository.py",
            "tests/unit/test_knowledge_parsers_and_chunking.py",
            "tests/integration/test_assistant_api.py",
            "tests/integration/test_assistant_ui.py",
            "tests/integration/test_knowledge_bases_api.py",
            "tests/integration/test_rag_search_tool.py"
        )
    }
    "release-assets" {
        @("tests/integration/test_release_assets.py")
    }
    "runtime" {
        @(
            "tests/unit/test_assistant_repository.py",
            "tests/unit/test_models_scripted_client.py",
            "tests/unit/test_openai_compatible_model_client.py",
            "tests/unit/test_observability.py",
            "tests/unit/test_fault_injection.py",
            "tests/unit/test_vector_index_provider.py",
            "tests/unit/test_embedding_provider.py",
            "tests/integration/test_run_lifecycle.py",
            "tests/integration/test_resume_flow.py",
            "tests/integration/test_tool_approval_flow.py",
            "tests/integration/test_governance_repositories.py",
            "tests/integration/test_state_repositories.py",
            "tests/integration/test_multi_agent_flow.py",
            "tests/integration/test_release_assets.py"
        )
    }
    "full" {
        @()
    }
    "perf" {
        @("tests/perf/test_core_api_regression.py")
    }
}

$pytestArgs = @("-m", "pytest")
if ($suiteTargets.Count -gt 0) {
    $pytestArgs += $suiteTargets
}
$pytestArgs += @("-v", "--basetemp=$resolvedBaseTempDir")
if (-not $UseCacheProvider) {
    $pytestArgs += @("-p", "no:cacheprovider")
}
if ($ExtraPytestArgs.Count -gt 0) {
    $pytestArgs += $ExtraPytestArgs
}

Write-Host "PythonExe=$PythonExe"
Write-Host "Suite=$Suite"
Write-Host "TMP=$env:TMP"
Write-Host "TEMP=$env:TEMP"
Write-Host "BaseTempDir=$resolvedBaseTempDir"
Write-Host "UseCacheProvider=$($UseCacheProvider.IsPresent)"
if ($suiteTargets.Count -gt 0) {
    Write-Host "Targets=$($suiteTargets -join ', ')"
} else {
    Write-Host "Targets=<full pytest suite>"
}

Push-Location $repoRoot
try {
    & $PythonExe @pytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
