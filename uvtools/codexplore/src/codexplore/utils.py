"""Shared utility functions for codexplore."""

import json
import os
from datetime import datetime
from pathlib import Path


def get_codexplorer_dir(base_dir: str | None = None) -> Path:
    """Get the codexplorer/ directory, creating it if necessary."""
    base = Path(base_dir) if base_dir else Path.cwd()
    codexplorer_dir = base / "codexplorer"
    codexplorer_dir.mkdir(parents=True, exist_ok=True)
    return codexplorer_dir


def generate_run_id() -> str:
    """Generate a timestamped run ID."""
    return datetime.now().strftime("run_%Y-%m-%d_%H%M%S")


def get_run_dir(codexplorer_dir: Path, run_id: str) -> Path:
    """Get the directory for a specific run."""
    return codexplorer_dir / run_id


def list_runs(codexplorer_dir: Path) -> list[dict]:
    """List all profiling runs in the codexplorer directory."""
    runs = []
    if not codexplorer_dir.exists():
        return runs

    for entry in sorted(codexplorer_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith("run_"):
            meta_file = entry / "meta.json"
            if meta_file.exists():
                with open(meta_file) as f:
                    meta = json.load(f)
                runs.append(
                    {
                        "id": entry.name,
                        "timestamp": meta.get("timestamp", "unknown"),
                        "script": meta.get("script", "unknown"),
                        "path": str(entry),
                    }
                )
    return runs


def find_python_interpreter(python_override: str | None = None) -> str:
    """Find the Python interpreter to use for running the target script.

    Priority:
    1. Explicit --python flag
    2. VIRTUAL_ENV environment variable
    3. 'python' in current PATH
    """
    if python_override:
        return python_override

    # Check for active virtualenv
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        venv_python = Path(venv) / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)

    # Fall back to PATH
    import shutil
    python_path = shutil.which("python3") or shutil.which("python")
    if python_path:
        return python_path

    raise RuntimeError(
        "Could not find a Python interpreter. "
        "Activate a virtualenv or pass --python explicitly."
    )
