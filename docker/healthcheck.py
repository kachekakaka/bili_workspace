from __future__ import annotations

import json
import os
import sys
from urllib.request import urlopen

port = int(os.getenv("BILI_PORT", "3398"))
try:
    with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as response:
        payload = json.load(response)
    if response.status != 200 or payload.get("ok") is not True:
        raise RuntimeError("health response is not ready")
except Exception as exc:  # noqa: BLE001
    print(f"healthcheck failed: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc
