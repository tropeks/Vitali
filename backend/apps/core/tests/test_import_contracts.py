"""
Import contract gate — P1-01.

Verifies that the import-linter domain-independence contract passes on every
pytest run. Any new cross-domain import will fail here before it reaches CI.

Run manually:
    pytest apps/core/tests/test_import_contracts.py -p no:cacheprovider -q
Or via the LXC harness:
    bash /home/rcosta00/dev/_vitali_test.sh apps/core/tests/test_import_contracts.py
"""

import subprocess
from importlib import import_module
from pathlib import Path

import pytest


def _importlinter_available() -> bool:
    try:
        import_module("importlinter")
        return True
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(
    not _importlinter_available(),
    reason="import-linter not installed; add import-linter==2.1 to requirements/development.txt",
)
def test_domain_independence_contract() -> None:
    """All domain apps must be independent of each other (baseline grandfathered via ignore_imports)."""
    # In the container /app maps to backend/, so the test file sits at:
    # /app/apps/core/tests/test_import_contracts.py
    # parents[3] = /app  (backend root = backend/)
    # On the host this resolves to backend/.importlinter.
    config_path = Path(__file__).resolve().parents[3] / ".importlinter"
    assert config_path.exists(), f".importlinter config not found at {config_path}"

    # Run lint-imports CLI via subprocess so that importlinter's application
    # bootstrap (printer, settings) is isolated from the pytest process.
    # The CLI entrypoint is the `lint-imports` script installed by the package.
    import shutil

    lint_imports_bin = shutil.which("lint-imports")
    assert lint_imports_bin, (
        "lint-imports binary not found on PATH. "
        "Ensure import-linter==2.1 is installed in the active Python environment."
    )

    result = subprocess.run(
        [lint_imports_bin, "--config", str(config_path), "--no-cache"],
        capture_output=True,
        text=True,
        cwd=str(config_path.parent),
    )

    assert result.returncode == 0, (
        "import-linter domain-independence contract FAILED.\n"
        "A new cross-domain import was introduced. "
        "Either remove the import or route it through apps.core.\n\n"
        f"--- lint-imports output ---\n{result.stdout}\n{result.stderr}"
    )
