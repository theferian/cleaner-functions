from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_project_pipeline_direct_help_runs_from_repo_root():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1256"
    completed = subprocess.run(
        [sys.executable, str(root / "pipeline" / "project_pipeline.py"), "--help"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--project" in completed.stdout
    assert "--stage" in completed.stdout


def test_cleaner_next_stage_guidance_uses_project_launcher_for_non_azd():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "functions" / "cleaner" / "azd_pipeline.py").read_text(encoding="utf-8")
    assert "project_pipeline.py --project {project_code}" in source
    assert "project_code == \"AZD\"" in source
