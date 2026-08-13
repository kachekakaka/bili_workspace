from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_ROOT = ROOT / "launcher"
for path in (str(ROOT), str(LAUNCHER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
