from __future__ import annotations

import hashlib
import time
import urllib.parse
from functools import reduce
from typing import Any

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def _encode_value(value: Any) -> str:
    # Match encodeURIComponent: uppercase percent encodings, space as %20
    return urllib.parse.quote(str(value), safe="!'()*~")


def sign_params(
    params: dict[str, Any],
    img_key: str,
    sub_key: str,
    *,
    wts: int | None = None,
) -> dict[str, Any]:
    mixin = get_mixin_key(img_key + sub_key)
    signed = dict(params)
    signed["wts"] = int(wts if wts is not None else time.time())
    filtered = {
        k: "".join(ch for ch in str(v) if ch not in "!'()*")
        for k, v in signed.items()
    }
    query = "&".join(
        f"{k}={_encode_value(filtered[k])}" for k in sorted(filtered.keys())
    )
    w_rid = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
    signed["w_rid"] = w_rid
    return signed
