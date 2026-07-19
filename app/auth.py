from __future__ import annotations

import ipaddress
import re
from typing import Final

USERNAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,31}$")
DISPLAY_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,12}$"
)

ROLE_ADMIN: Final[str] = "admin"
ROLE_USER: Final[str] = "user"
VALID_ROLES: Final[frozenset[str]] = frozenset({ROLE_ADMIN, ROLE_USER})

ADMIN_PERMISSIONS: Final[tuple[str, ...]] = (
    "admin:*",
    "download:create-library",
    "download:create-device",
    "tasks:read-all",
    "tasks:write-all",
    "users:manage",
    "sessions:manage-all",
)
USER_PERMISSIONS: Final[tuple[str, ...]] = (
    "download:create-device",
    "tasks:read-own",
    "tasks:write-own",
    "sessions:manage-own",
)


def validate_username(value: str) -> str:
    username = str(value or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "登录账号必须为 3–32 位，以英文字母开头，仅包含字母、数字、点、下划线或短横线"
        )
    return username


def validate_display_name(value: str) -> str:
    display_name = str(value or "").strip()
    if not DISPLAY_NAME_RE.fullmatch(display_name):
        raise ValueError("中文显示名必须为 2–12 个汉字，不能包含英文、数字、空格或标点")
    return display_name


def validate_password(value: str, *, allow_default_temp: bool = False) -> str:
    password = str(value or "")
    if allow_default_temp and password == "123456":
        return password
    if not 10 <= len(password) <= 64:
        raise ValueError("密码长度必须为 10–64 个字符")
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in password):
        raise ValueError("密码只能使用可见 ASCII 字符，不能包含中文、空格或控制字符")
    if not any(char.isalpha() for char in password):
        raise ValueError("密码至少需要包含一个英文字母")
    if not any(char.isdigit() for char in password):
        raise ValueError("密码至少需要包含一个数字")
    return password


def permissions_for_role(role: str) -> list[str]:
    return list(ADMIN_PERMISSIONS if role == ROLE_ADMIN else USER_PERMISSIONS)


def is_loopback_address(value: str) -> bool:
    raw = str(value or "").strip()
    if raw in {"localhost", "testclient"}:
        return True
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    elif raw.count(":") == 1:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            raw = host
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return False
