"""不经过 shell 的外部命令执行器。"""

from __future__ import annotations

import os
import subprocess
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    output: str


class CommandError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        tail = result.output.strip().splitlines()[-1:] or ["无输出"]
        super().__init__(f"命令执行失败（{result.returncode}）：{tail[0]}")


class CommandRunner:
    def run(
        self,
        args: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        on_output: Callable[[str], None] | None = None,
        check: bool = True,
    ) -> CommandResult:
        normalized = tuple(os.fspath(argument) for argument in args)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            normalized,
            cwd=os.fspath(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=creationflags,
        )
        lines: deque[str] = deque()
        retained_characters = 0
        max_retained_characters = 2 * 1024 * 1024
        assert process.stdout is not None
        for line in process.stdout:
            if len(line) > max_retained_characters:
                line = line[-max_retained_characters:]
            lines.append(line)
            retained_characters += len(line)
            while lines and retained_characters > max_retained_characters:
                retained_characters -= len(lines.popleft())
            if on_output:
                on_output(line.rstrip("\r\n")[-8192:])
        result = CommandResult(normalized, process.wait(), "".join(lines))
        if check and result.returncode != 0:
            raise CommandError(result)
        return result
