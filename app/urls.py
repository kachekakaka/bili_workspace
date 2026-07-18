from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.constants import MAX_BATCH_ITEMS, MAX_INPUT_LENGTH

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
AV_RE = re.compile(r"(?:^|[^A-Za-z0-9])(?:av)(\d+)(?:$|[^0-9])", re.IGNORECASE)
EP_RE = re.compile(r"(?:^|[^A-Za-z0-9])(?:ep)(\d+)(?:$|[^0-9])", re.IGNORECASE)
SS_RE = re.compile(r"(?:^|[^A-Za-z0-9])(?:ss)(\d+)(?:$|[^0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class Target:
    key: str
    url: str
    bvid: str | None = None


def _allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return (
        host == "bilibili.com"
        or host.endswith(".bilibili.com")
        or host == "b23.tv"
        or host.endswith(".b23.tv")
    )


def _target_from_identifier(text: str) -> Target | None:
    bv = BV_RE.search(text)
    if bv:
        bvid = "BV" + bv.group(1)[2:]
        return Target(key=bvid, url=f"https://www.bilibili.com/video/{bvid}", bvid=bvid)

    av = AV_RE.search(f" {text} ")
    if av:
        aid = av.group(1)
        return Target(key=f"av{aid}", url=f"https://www.bilibili.com/video/av{aid}")

    ep = EP_RE.search(f" {text} ")
    if ep:
        epid = ep.group(1)
        return Target(key=f"ep{epid}", url=f"https://www.bilibili.com/bangumi/play/ep{epid}")

    ss = SS_RE.search(f" {text} ")
    if ss:
        ssid = ss.group(1)
        return Target(key=f"ss{ssid}", url=f"https://www.bilibili.com/bangumi/play/ss{ssid}")
    return None


def normalize_line(line: str) -> Target | None:
    text = str(line).strip()
    if not text:
        return None
    if len(text) > MAX_INPUT_LENGTH:
        raise ValueError(f"输入过长（上限 {MAX_INPUT_LENGTH} 字符）")

    if text.lower().startswith(("http://", "https://")):
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https":
            raise ValueError(f"仅支持 HTTPS 链接: {text}")
        if not host or not _allowed_host(host):
            raise ValueError(f"不支持的链接主机: {text}")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"链接不得包含用户名或密码: {text}")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"链接端口无效: {text}") from exc
        if port not in (None, 443):
            raise ValueError(f"链接端口不受支持: {text}")

        identifier = _target_from_identifier(parsed.path)
        if identifier is not None:
            return identifier

        canonical_netloc = host if port is None else f"{host}:{port}"
        canonical = urlunparse(("https", canonical_netloc, parsed.path or "/", "", parsed.query, ""))
        return Target(key=canonical, url=canonical)

    identifier = _target_from_identifier(text)
    if identifier is not None:
        return identifier
    raise ValueError(f"无法识别的输入: {text}")


def parse_inputs(
    urls: list[str] | None = None,
    bvids: list[str] | None = None,
    *,
    max_items: int = MAX_BATCH_ITEMS,
) -> list[Target]:
    lines: list[str] = []
    for item in urls or []:
        lines.extend(str(item).splitlines())
    lines.extend(str(item) for item in (bvids or []))

    seen: set[str] = set()
    result: list[Target] = []
    errors: list[str] = []
    for line in lines:
        try:
            target = normalize_line(line)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if target is None or target.key in seen:
            continue
        seen.add(target.key)
        result.append(target)
        if len(result) > max_items:
            raise ValueError(f"单次最多提交 {max_items} 个作品")

    if errors:
        suffix = f"（另有 {len(errors) - 1} 条错误）" if len(errors) > 1 else ""
        raise ValueError(errors[0] + suffix)
    if not result:
        raise ValueError("请提供有效的链接或 BV/av/ep/ss 编号")
    return result
