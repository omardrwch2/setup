"""Profile runner — wraps py-spy to profile target scripts."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from codexplore.utils import (
    find_python_interpreter,
    generate_run_id,
    get_codexplorer_dir,
    get_run_dir,
)


def run_profile(
    script: str,
    script_args: list[str],
    python: str | None = None,
    rate: int = 100,
    subprocesses: bool = False,
) -> str | None:
    """Run py-spy on the given script and save results.

    Returns the run_id on success, None on failure.
    """
    script_path = Path(script).resolve()
    if not script_path.exists():
        print(f"Error: Script not found: {script_path}", file=sys.stderr)
        return None

    # Resolve the python interpreter from the USER's environment, not ours
    try:
        python_path = find_python_interpreter(python)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return None

    # Find py-spy — it's installed as our dependency, so look next to our own python first
    py_spy_path = shutil.which("py-spy")
    if not py_spy_path:
        # uv tool installs put binaries in the same bin/ dir as the tool's python
        own_bin_dir = Path(sys.executable).parent
        candidate = own_bin_dir / "py-spy"
        if candidate.exists():
            py_spy_path = str(candidate)
    if not py_spy_path:
        print(
            "Error: py-spy not found. It should be installed as a dependency of codexplore.\n"
            "Try: uv tool install . --force",
            file=sys.stderr,
        )
        return None

    # Create run directory in current working directory
    codexplorer_dir = get_codexplorer_dir(None)
    run_id = generate_run_id()
    run_dir = get_run_dir(codexplorer_dir, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Output paths
    profile_output = run_dir / "profile.json"

    # Build py-spy command
    cmd = [
        py_spy_path,
        "record",
        "--format", "speedscope",
        "--output", str(profile_output),
        "--rate", str(rate),
    ]

    if subprocesses:
        cmd.append("--subprocesses")

    cmd.append("--")
    cmd.append(python_path)
    cmd.append(str(script_path))
    cmd.extend(script_args)

    # Save metadata
    meta = {
        "run_id": run_id,
        "script": str(script_path),
        "script_args": script_args,
        "python": python_path,
        "rate": rate,
        "subprocesses": subprocesses,
        "timestamp": datetime.now().isoformat(),
        "cwd": os.getcwd(),
    }

    meta_file = run_dir / "meta.json"
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"🔍 Profiling: {script_path.name}")
    print(f"   Python:    {python_path}")
    print(f"   Rate:      {rate} Hz")
    print(f"   Output:    {run_dir}")
    print(f"   Command:   {' '.join(cmd)}")
    print()

    # Run py-spy
    try:
        result = subprocess.run(
            cmd,
            cwd=str(script_path.parent),
            # Pass through stdin/stdout/stderr so the profiled script can interact
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except PermissionError:
        print(
            "\n❌ Permission denied. py-spy needs permissions to profile processes.\n"
            "   Options:\n"
            "   1. Run with sudo: sudo codexplore run ...\n"
            "   2. Set ptrace scope: echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope\n"
            "   3. Give py-spy CAP_SYS_PTRACE: sudo setcap cap_sys_ptrace+ep $(which py-spy)\n",
            file=sys.stderr,
        )
        return None
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted. Partial profile may have been saved.")

    # Verify output was created
    if not profile_output.exists():
        print(f"Warning: Profile output not created at {profile_output}", file=sys.stderr)
        # Still return the run_id since meta was saved
        meta["error"] = "Profile output not generated"
        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=2)
        return None

    # Update meta with profile info
    try:
        with open(profile_output) as f:
            profile_data = json.load(f)
        meta["profile_format"] = "speedscope"
        meta["profile_file"] = "profile.json"
        meta["num_profiles"] = len(profile_data.get("profiles", []))
        meta["shared_frames"] = len(profile_data.get("shared", {}).get("frames", []))
    except Exception:
        pass

    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)

    return run_id
