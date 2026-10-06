from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_weekly_report_pipeline_direct_script_can_import_sibling_functions():
    root = Path(__file__).resolve().parents[1]
    script = root / "pipeline" / "weekly_report_pipeline.py"
    env = os.environ.copy()
    # Reproduce the Windows/Git-Bash code page that exposed the original bug.
    # CLI help and orchestration messages must remain printable even when the
    # terminal is not UTF-8.
    env["PYTHONIOENCODING"] = "cp1256"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "board-to-log" in completed.stdout


def test_azd_cleaner_compatibility_launcher_can_import_sibling_functions():
    root = Path(__file__).resolve().parents[1]
    script = root / "pipeline" / "azd_pipeline.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1256"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--stage" in completed.stdout
    assert "FIELD_VALIDATION" in completed.stdout


def test_weekly_report_pipeline_help_lists_retrieve():
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = root / "pipeline" / "weekly_report_pipeline.py"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1256"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "retrieve" in completed.stdout
    assert "audit-coverage" in completed.stdout
    assert "engineering-lists" in completed.stdout
