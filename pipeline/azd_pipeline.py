from __future__ import annotations

import sys
from pathlib import Path

# Compatibility entry point. The Cleaner is now a function-level component;
# the overall weekly-report pipeline lives one layer above it.
#
# When this file is executed directly (``python pipeline/azd_pipeline.py``),
# Python puts only ``pipeline/`` on sys.path. Add the repository root so the
# sibling ``functions/`` package remains importable on Windows/Git Bash, CMD,
# PowerShell, and normal Python shells.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.cleaner.azd_pipeline import *  # noqa: F401,F403,E402
from functions.cleaner.azd_pipeline import main  # noqa: E402


if __name__ == "__main__":
    main()
