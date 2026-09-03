"""T-BILIBILI-LIVE Windows 本地命令入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.bilibili_live.contracts import LiveTestError, read_summary
from tools.bilibili_live.maintenance import (
    cleanup_stale_run,
    list_stale_runs,
    refresh_fixtures_from_run,
)
from tools.bilibili_live.runner import VALID_IMPACTS, VALID_TARGETS, run_live_test


ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="运行真实 Bilibili 影响域验证")
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--impact", choices=sorted(VALID_IMPACTS), required=True)
    run.add_argument("--target", choices=sorted(VALID_TARGETS), default="source")
    run.add_argument("--candidate-record", type=Path)
    run.add_argument("--tool-provider-record", type=Path)

    stale = subparsers.add_parser("list-stale", help="只读列举满 72 小时的真链 run")
    stale.add_argument("--test-root", type=Path, required=True)

    cleanup = subparsers.add_parser("cleanup", help="精确删除一个满 72 小时的真链 run")
    cleanup.add_argument("--test-root", type=Path, required=True)
    cleanup.add_argument("--run-root", type=Path, required=True)
    cleanup.add_argument("--data-root", type=Path, required=True)

    refresh = subparsers.add_parser("refresh-fixtures", help="显式写回一个结构漂移候选")
    refresh.add_argument("--run-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "run":
            if arguments.target == "candidate" and arguments.candidate_record is None:
                raise ValueError("candidate 目标必须提供 --candidate-record")
            if arguments.target == "source" and arguments.candidate_record is not None:
                raise ValueError("source 目标不接受 --candidate-record")
            if arguments.target == "candidate" and arguments.tool_provider_record is not None:
                raise ValueError("candidate 目标不接受 --tool-provider-record")
            code, run = run_live_test(
                workspace_root=ROOT,
                credential_source=arguments.data_root,
                impact=arguments.impact,
                target=arguments.target,
                candidate_record=arguments.candidate_record,
                tool_provider_record=arguments.tool_provider_record,
            )
            if run is not None:
                print(f"真链运行目录：{run}")
                summary = read_summary(run, ROOT)
                print(f"真链结果：{summary.get('status', 'inconclusive')}")
                if summary.get("reason"):
                    print(f"原因：{summary['reason']}")
            return code
        if arguments.command == "list-stale":
            for run in list_stale_runs(
                test_root=arguments.test_root,
                workspace_root=ROOT,
            ):
                print(run)
            return 0
        if arguments.command == "cleanup":
            parent = cleanup_stale_run(
                run_root=arguments.run_root,
                test_root=arguments.test_root,
                workspace_root=ROOT,
                credential_source=arguments.data_root,
            )
            print(f"已精确删除真链运行；测试根保留：{parent}")
            return 0
        written = refresh_fixtures_from_run(
            run_root=arguments.run_root,
            workspace_root=ROOT,
            tracked_root=ROOT / "SoftwareTesting" / "bilibili_live" / "fixtures",
        )
        for path in written:
            print(path)
        return 0
    except (LiveTestError, ValueError) as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
