from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path",),
    [
        ("README.md",),
        (".env.example",),
        ("Dockerfile",),
        ("docker-compose.yml",),
        ("scripts/start-local.ps1",),
        ("scripts/start-local.sh",),
        ("scripts/run-regression.ps1",),
    ],
)
def test_v1_release_asset_exists(relative_path: str) -> None:
    assert (PROJECT_ROOT / relative_path).is_file()


def test_readme_mentions_supported_v1_runtime_paths() -> None:
    readme_path = PROJECT_ROOT / "README.md"
    assert readme_path.is_file()

    readme_text = readme_path.read_text(encoding="utf-8").lower()
    missing_terms = [
        required_text
        for required_text in ("agent_rag", "fresh environment", "docker compose", "/health")
        if required_text.lower() not in readme_text
    ]

    assert not missing_terms, f"README.md is missing required v1 terms: {missing_terms}"
    assert "operations-runbook.md" in readme_text
    assert "deferred-roadmap.md" in readme_text
    for required_text in (
        "docker compose up --build",
        "runtime.db",
        "read-only",
        "host_published_port",
        "container_agent_runtime_host",
        "container_agent_runtime_port",
        "container_agent_runtime_db_url",
        "container_agent_runtime_embedding_model_root",
        "single-service topology",
    ):
        assert required_text in readme_text
    assert "nlp_gte_sentence-embedding_chinese-base" in readme_text
    assert "production deployment guidance" in readme_text or "production-oriented" in readme_text


def test_dockerfile_builds_runtime_entrypoint_contract() -> None:
    dockerfile_path = PROJECT_ROOT / "Dockerfile"
    assert dockerfile_path.is_file()

    dockerfile_text = dockerfile_path.read_text(encoding="utf-8").lower()
    for required_text in (
        "from python:",
        "workdir",
        "pip install",
        "agent_runtime.main:app",
        "uvicorn",
    ):
        assert required_text in dockerfile_text


def test_compose_file_documents_standard_runtime_topology() -> None:
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.is_file()

    compose_text = compose_path.read_text(encoding="utf-8").lower()
    for required_text in (
        "services:",
        "agent-runtime:",
        "build:",
        "dockerfile: dockerfile",
        "container_agent_runtime_host",
        "container_agent_runtime_port",
        "container_agent_runtime_db_url",
        "container_agent_runtime_embedding_model_root",
        "host_published_port",
        "agent_runtime_host",
        "agent_runtime_port",
        "agent_runtime_db_url",
        "agent_runtime_embedding_model_root",
        "runtime.db",
        "read_only: true",
    ):
        assert required_text in compose_text
    assert "${host_published_port:-8000}:${container_agent_runtime_port:-8000}" in compose_text
    assert "os.environ.get('agent_runtime_port', '8000')" in compose_text


def test_env_example_lists_runtime_startup_configuration() -> None:
    env_example_path = PROJECT_ROOT / ".env.example"
    assert env_example_path.is_file()

    env_text = env_example_path.read_text(encoding="utf-8")
    for required_name in (
        "AGENT_RUNTIME_HOST",
        "AGENT_RUNTIME_PORT",
        "AGENT_RUNTIME_DB_URL",
        "AGENT_RUNTIME_EMBEDDING_MODEL_ROOT",
        "HOST_PUBLISHED_PORT",
        "HOST_EMBEDDING_MODEL_ROOT",
        "CONTAINER_AGENT_RUNTIME_HOST",
        "CONTAINER_AGENT_RUNTIME_PORT",
        "CONTAINER_AGENT_RUNTIME_DB_URL",
        "CONTAINER_AGENT_RUNTIME_EMBEDDING_MODEL_ROOT",
        "PYTHONPATH",
    ):
        assert required_name in env_text
    assert r"AGENT_RUNTIME_EMBEDDING_MODEL_ROOT=C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base" in env_text


def test_powershell_quick_start_script_is_loadable() -> None:
    powershell_executable = shutil.which("powershell") or shutil.which("pwsh")
    if powershell_executable is None:
        pytest.skip("PowerShell is not available in this environment")

    result = subprocess.run(
        [
            powershell_executable,
            "-NoProfile",
            "-Command",
            "Get-Command -Name './scripts/start-local.ps1' | Out-Null",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_powershell_regression_script_is_loadable_and_documents_local_tmp_contract() -> None:
    powershell_script_path = PROJECT_ROOT / "scripts" / "run-regression.ps1"
    assert powershell_script_path.is_file()

    powershell_executable = shutil.which("powershell") or shutil.which("pwsh")
    if powershell_executable is None:
        pytest.skip("PowerShell is not available in this environment")

    result = subprocess.run(
        [
            powershell_executable,
            "-NoProfile",
            "-Command",
            "Get-Command -Name './scripts/run-regression.ps1' | Out-Null",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    script_text = powershell_script_path.read_text(encoding="utf-8").lower()
    for required_text in (
        ".pytest_tmp",
        ".tmp",
        "tmp",
        "temp",
        "--basetemp",
        "-p",
        "no:cacheprovider",
        "pytest",
    ):
        assert required_text in script_text


def test_local_startup_scripts_default_to_deepseek() -> None:
    powershell_script = (PROJECT_ROOT / "scripts" / "start-local.ps1").read_text(encoding="utf-8").lower()
    shell_script = (PROJECT_ROOT / "scripts" / "start-local.sh").read_text(encoding="utf-8").lower()

    for script_text in (powershell_script, shell_script):
        assert "agent_runtime_model_base_url" in script_text
        assert "https://api.deepseek.com" in script_text
        assert "agent_runtime_model_name" in script_text
        assert "deepseek-v4-flash" in script_text
        assert "nlp_gte_sentence-embedding_chinese-base" in script_text
