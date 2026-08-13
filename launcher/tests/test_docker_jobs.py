from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

import bili_workspace_launcher.docker_jobs as docker_jobs_module
from bili_workspace_launcher.commands import CommandError, CommandResult
from bili_workspace_launcher.constants import (
    BUILD_LABEL_KEY,
    JOB_LABEL_KEY,
    OWNER_LABEL_KEY,
    OWNER_LABEL_VALUE,
)
from bili_workspace_launcher.docker_jobs import (
    DockerJobError,
    DockerJobs,
    _git_boundary,
    _task_export_paths,
    expected_export_paths,
)
from bili_workspace_launcher.paths import AppPaths


class FakeDocker:
    def __init__(self, architecture: str = "amd64") -> None:
        self.architecture = architecture
        self.calls: list[tuple[str, ...]] = []
        self.tag = ""
        self.labels: dict[str, str] = {}
        self.image_id = "sha256:" + "a" * 64
        self.config_payload = b"{}"
        self.exists = False

    def run(self, args, *, cwd=None, on_output=None, check=True):
        del cwd, check
        call = tuple(str(value) for value in args)
        self.calls.append(call)
        if call[:2] == ("docker", "version"):
            return CommandResult(call, 0, "27.0\n")
        if call[:2] == ("docker", "build"):
            self.tag = call[call.index("--tag") + 1]
            indices = [index for index, value in enumerate(call) if value == "--label"]
            self.labels = dict(call[index + 1].split("=", 1) for index in indices)
            self.config_payload = json.dumps(
                {
                    "architecture": self.architecture,
                    "os": "linux",
                    "config": {"Labels": self.labels},
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.image_id = "sha256:" + hashlib.sha256(self.config_payload).hexdigest()
            self.exists = True
            if on_output:
                on_output("fake build")
            return CommandResult(call, 0, "built\n")
        if call[:3] == ("docker", "image", "inspect"):
            if not self.exists:
                return CommandResult(call, 1, "not found\n")
            payload = [
                {
                    "Id": self.image_id,
                    "Os": "linux",
                    "Architecture": self.architecture,
                    "Size": 123456,
                    "Config": {"Labels": self.labels},
                }
            ]
            return CommandResult(call, 0, json.dumps(payload))
        if call[:3] == ("docker", "image", "ls"):
            return CommandResult(call, 0, f"{self.image_id}\n" if self.exists else "")
        if call[:3] == ("docker", "image", "save"):
            output = Path(call[call.index("--output") + 1])
            digest = self.image_id.split(":", 1)[1]
            manifest = json.dumps(
                [{"Config": f"{digest}.json", "RepoTags": [self.tag], "Layers": []}]
            ).encode("utf-8")
            with tarfile.open(output, "w") as archive:
                info = tarfile.TarInfo("manifest.json")
                info.size = len(manifest)
                archive.addfile(info, io.BytesIO(manifest))
                config = self.config_payload
                config_info = tarfile.TarInfo(f"{digest}.json")
                config_info.size = len(config)
                archive.addfile(config_info, io.BytesIO(config))
            return CommandResult(call, 0, "saved\n")
        if call[:3] == ("docker", "image", "rm"):
            self.exists = False
            return CommandResult(call, 0, "removed\n")
        raise AssertionError(call)


def _source(root: Path) -> Path:
    docker = root / "docker-context" / "docker"
    docker.mkdir(parents=True)
    (docker / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    return root


def _verified_jobs(paths: AppPaths, runner: FakeDocker) -> DockerJobs:
    return DockerJobs(paths, runner, resource_verifier=lambda _root, _build_id: None)


def test_git_boundary_recognizes_reparse_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    output = checkout / "exports"
    output.mkdir(parents=True)
    marker = checkout / ".git"
    original = docker_jobs_module._is_reparse_point
    monkeypatch.setattr(
        docker_jobs_module,
        "_is_reparse_point",
        lambda path: path == marker or original(path),
    )

    assert _git_boundary(output) == checkout.resolve()


def test_export_is_fixed_amd64_triad_and_exact_cleanup(tmp_path: Path) -> None:
    runner = FakeDocker()
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    jobs = _verified_jobs(paths, runner)
    result = jobs.export_image(
        source_root=_source(paths.resources_dir / "0123456789ab"),
        output_dir=output,
        build_id="0123456789ab",
        overwrite=False,
    )
    assert result.paths.tar.is_file()
    assert result.paths.checksum.is_file()
    manifest = json.loads(result.paths.manifest.read_text(encoding="utf-8"))
    assert manifest["platform"] == "linux/amd64"
    assert manifest["build_id"] == "0123456789ab"
    assert manifest["image_id"] == runner.image_id
    build = next(call for call in runner.calls if call[:2] == ("docker", "build"))
    assert build[build.index("--platform") + 1] == "linux/amd64"
    assert f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}" in build
    assert any(value.startswith(f"{JOB_LABEL_KEY}=") for value in build)
    assert f"{BUILD_LABEL_KEY}=0123456789ab" in build
    assert not any(
        call[:3] in {
            ("docker", "system", "prune"),
            ("docker", "image", "prune"),
            ("docker", "builder", "prune"),
        }
        for call in runner.calls
    )


def test_export_rejects_non_amd64_and_existing_without_confirmation(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    jobs = _verified_jobs(paths, FakeDocker(architecture="arm64"))
    with pytest.raises(DockerJobError, match="linux/amd64"):
        jobs.export_image(
            source_root=_source(paths.resources_dir / "0123456789ab"),
            output_dir=output,
            build_id="0123456789ab",
            overwrite=False,
        )

    existing = output / "bili-workspace-0.7.0-0123456789ab-linux-amd64.tar"
    existing.write_bytes(b"old")
    with pytest.raises(DockerJobError, match="确认覆盖"):
        DockerJobs(paths, FakeDocker()).export_image(
            source_root=tmp_path / "resources",
            output_dir=output,
            build_id="0123456789ab",
            overwrite=False,
        )


def test_export_rejects_target_created_after_preflight(tmp_path: Path) -> None:
    runner = FakeDocker()
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    jobs = _verified_jobs(paths, runner)
    build_id = "0123456789ab"
    preflight = jobs.preflight_export(output, build_id)
    appeared = preflight.paths.tar
    appeared.write_bytes(b"appeared-after-confirmation")

    with pytest.raises(DockerJobError, match="覆盖确认后发生变化"):
        jobs.export_image(
            source_root=_source(paths.resources_dir / build_id),
            output_dir=output,
            build_id=build_id,
            overwrite=False,
            preflight=preflight,
        )

    assert appeared.read_bytes() == b"appeared-after-confirmation"
    assert not any(call[:2] == ("docker", "build") for call in runner.calls)


def test_export_rejects_target_changed_during_build(tmp_path: Path) -> None:
    runner = FakeDocker()
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    jobs = _verified_jobs(paths, runner)
    build_id = "0123456789ab"
    targets = expected_export_paths(output, build_id)
    targets.tar.write_bytes(b"confirmed-old")
    preflight = jobs.preflight_export(output, build_id)
    original_run = runner.run

    def mutate_after_build(args, **kwargs):
        result = original_run(args, **kwargs)
        if tuple(args)[:2] == ("docker", "build"):
            targets.tar.write_bytes(b"changed-during-build")
        return result

    runner.run = mutate_after_build  # type: ignore[method-assign]
    with pytest.raises(DockerJobError, match="构建期间发生变化"):
        jobs.export_image(
            source_root=_source(paths.resources_dir / build_id),
            output_dir=output,
            build_id=build_id,
            overwrite=True,
            preflight=preflight,
        )

    assert targets.tar.read_bytes() == b"changed-during-build"
    assert not targets.checksum.exists()
    assert not targets.manifest.exists()


def test_publish_validation_failure_restores_exact_previous_triad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeDocker()
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    build_id = "0123456789ab"
    targets = expected_export_paths(output, build_id)
    old_payloads = (b"old-tar", b"old-checksum", b"old-manifest")
    for target, payload in zip(
        (targets.tar, targets.checksum, targets.manifest), old_payloads, strict=True
    ):
        target.write_bytes(payload)
    jobs = _verified_jobs(paths, runner)

    def reject_published(*_args, **_kwargs):
        raise DockerJobError("injected final validation failure")

    monkeypatch.setattr(jobs, "_validate_triad", reject_published)
    with pytest.raises(DockerJobError, match="injected final validation failure"):
        jobs.export_image(
            source_root=_source(paths.resources_dir / build_id),
            output_dir=output,
            build_id=build_id,
            overwrite=True,
        )

    for target, payload in zip(
        (targets.tar, targets.checksum, targets.manifest), old_payloads, strict=True
    ):
        assert target.read_bytes() == payload
    assert not list(output.glob(".*.bak"))


def test_export_revalidates_resource_tree_before_docker_build(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    source = _source(paths.resources_dir / "0123456789ab")
    output = tmp_path / "exports"
    output.mkdir()
    verified: list[tuple[Path, str]] = []

    def reject(root: Path, build_id: str) -> None:
        verified.append((root, build_id))
        raise DockerJobError("injected resource verification failure")

    runner = FakeDocker()
    jobs = DockerJobs(paths, runner, resource_verifier=reject)
    with pytest.raises(DockerJobError, match="resource verification failure"):
        jobs.export_image(
            source_root=source,
            output_dir=output,
            build_id="0123456789ab",
            overwrite=False,
        )

    assert verified == [(source.resolve(), "0123456789ab")]
    assert not any(call[:2] == ("docker", "build") for call in runner.calls)


def test_build_failure_keeps_redacted_journal_without_ambiguous_inspect(tmp_path: Path) -> None:
    class FailingBuildDocker(FakeDocker):
        def run(self, args, **kwargs):
            call = tuple(str(value) for value in args)
            if call[:2] == ("docker", "build"):
                self.calls.append(call)
                raise CommandError(CommandResult(call, 1, "Cookie: do-not-store-this\n"))
            if call[:3] in {
                ("docker", "image", "inspect"),
                ("docker", "image", "ls"),
            }:
                raise AssertionError("构建失败路径不应猜测镜像存在性")
            return super().run(args, **kwargs)

    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    output = tmp_path / "exports"
    output.mkdir()
    jobs = _verified_jobs(paths, FailingBuildDocker())

    with pytest.raises(DockerJobError, match="Cookie: \\*\\*\\*"):
        jobs.export_image(
            source_root=_source(paths.resources_dir / "0123456789ab"),
            output_dir=output,
            build_id="0123456789ab",
            overwrite=False,
        )

    journals = list(jobs.journal_dir.glob("image-export-*.json"))
    assert len(journals) == 1
    journal_text = journals[0].read_text(encoding="utf-8")
    assert "do-not-store-this" not in journal_text
    assert json.loads(journal_text)["state"] == "failed"


def test_daemon_failure_does_not_delete_stale_image_journal(tmp_path: Path) -> None:
    class UnavailableDocker(FakeDocker):
        def run(self, args, **kwargs):
            del kwargs
            call = tuple(str(value) for value in args)
            if call[:3] in {
                ("docker", "image", "inspect"),
                ("docker", "image", "ls"),
            }:
                return CommandResult(call, 1, "daemon unavailable\n")
            return super().run(args)

    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, UnavailableDocker())
    retained = jobs._new_retained("0123456789ab")
    jobs._write_journal(retained, state="failed")

    assert jobs.stale_images() == []
    assert retained.journal_path.is_file()


def test_recovery_rejects_journal_paths_outside_fixed_output_directory(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    jobs.journal_dir.mkdir()
    output = tmp_path / "exports"
    output.mkdir()
    outside = tmp_path / "must-not-touch.txt"
    outside.write_text("keep", encoding="utf-8")
    build_id = "0123456789ab"
    job_id = "a" * 32
    tag = f"bili-workspace-export:0.7.0-{build_id}-{job_id}"
    targets = expected_export_paths(output, build_id)
    journal = jobs.journal_dir / f"image-export-{job_id}.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "image-export",
                "product_version": "0.7.0",
                "platform": "linux/amd64",
                "job_id": job_id,
                "build_id": build_id,
                "tag": tag,
                "state": "publishing",
                "created_at": 1,
                "output_dir": str(output),
                "targets": [str(targets.tar), str(targets.checksum), str(targets.manifest)],
                "temporary": [str(output / f".{path.name}.{job_id}.tmp") for path in (
                    targets.tar,
                    targets.checksum,
                    targets.manifest,
                )],
                "backups": [str(outside), str(output / "wrong-2"), str(output / "wrong-3")],
                "had_existing": [False, False, False],
                "old_files": [{"exists": False}, {"exists": False}, {"exists": False}],
                "export_manifest": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockerJobError, match="事务路径"):
        jobs.recover_pending_outputs()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_docker_journal_directory_reparse_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    jobs.journal_dir.mkdir()
    monkeypatch.setattr(
        "bili_workspace_launcher.docker_jobs._is_reparse_point",
        lambda path: Path(path) == jobs.journal_dir,
    )
    with pytest.raises(DockerJobError, match="journal 目录类型无效"):
        jobs.recover_pending_outputs()


def test_docker_journal_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    jobs.journal_dir.mkdir()
    journal = jobs.journal_dir / f"image-export-{'d' * 32}.json"
    journal.write_bytes(b"\xff")

    with pytest.raises(DockerJobError, match="journal 无效"):
        jobs.recover_pending_outputs()


def test_stale_scan_removes_owned_journal_when_image_is_already_missing(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    retained = jobs._new_retained("0123456789ab")
    jobs._write_journal(retained, state="failed")

    assert jobs.stale_images() == []
    assert not retained.journal_path.exists()


def test_recovery_cleans_only_fixed_temporary_files_from_exporting_state(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    jobs.journal_dir.mkdir()
    output = tmp_path / "exports"
    output.mkdir()
    build_id = "0123456789ab"
    job_id = "b" * 32
    tag = f"bili-workspace-export:0.7.0-{build_id}-{job_id}"
    targets = expected_export_paths(output, build_id)
    temporary, backups = _task_export_paths(targets, job_id)
    for path in (temporary.tar, temporary.checksum, temporary.manifest):
        path.write_bytes(b"partial")
    unrelated = output / "unrelated.tmp"
    unrelated.write_bytes(b"keep")
    journal = jobs.journal_dir / f"image-export-{job_id}.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "image-export",
                "product_version": "0.7.0",
                "platform": "linux/amd64",
                "job_id": job_id,
                "build_id": build_id,
                "tag": tag,
                "state": "exporting",
                "created_at": 1,
                "output_dir": str(output),
                "targets": [str(targets.tar), str(targets.checksum), str(targets.manifest)],
                "temporary": [
                    str(temporary.tar),
                    str(temporary.checksum),
                    str(temporary.manifest),
                ],
                "backups": [str(backups.tar), str(backups.checksum), str(backups.manifest)],
            }
        ),
        encoding="utf-8",
    )

    messages = jobs.recover_pending_outputs()

    assert messages
    assert not any(path.exists() for path in (temporary.tar, temporary.checksum, temporary.manifest))
    assert unrelated.read_bytes() == b"keep"
    recovered = json.loads(journal.read_text(encoding="utf-8"))
    assert recovered["state"] == "cleanup-required"
    assert recovered["output_recovered"] is True


def test_recovery_restores_exact_old_triad_after_interrupted_publish(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    jobs = DockerJobs(paths, FakeDocker())
    jobs.journal_dir.mkdir()
    output = tmp_path / "exports"
    output.mkdir()
    build_id = "0123456789ab"
    job_id = "c" * 32
    tag = f"bili-workspace-export:0.7.0-{build_id}-{job_id}"
    targets = expected_export_paths(output, build_id)
    temporary, backups = _task_export_paths(targets, job_id)
    old_payloads = (b"old-tar", b"old-sha", b"old-json")
    old_files = []
    for backup, payload in zip(
        (backups.tar, backups.checksum, backups.manifest), old_payloads, strict=True
    ):
        backup.write_bytes(payload)
        old_files.append(
            {
                "exists": True,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    targets.tar.write_bytes(b"incomplete-new-tar")
    journal = jobs.journal_dir / f"image-export-{job_id}.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "image-export",
                "product_version": "0.7.0",
                "platform": "linux/amd64",
                "job_id": job_id,
                "build_id": build_id,
                "tag": tag,
                "state": "publishing",
                "created_at": 1,
                "output_dir": str(output),
                "targets": [str(targets.tar), str(targets.checksum), str(targets.manifest)],
                "temporary": [
                    str(temporary.tar),
                    str(temporary.checksum),
                    str(temporary.manifest),
                ],
                "backups": [str(backups.tar), str(backups.checksum), str(backups.manifest)],
                "had_existing": [True, True, True],
                "old_files": old_files,
                "export_manifest": {},
            }
        ),
        encoding="utf-8",
    )

    messages = jobs.recover_pending_outputs()

    assert any("已恢复" in message for message in messages)
    for target, payload in zip(
        (targets.tar, targets.checksum, targets.manifest), old_payloads, strict=True
    ):
        assert target.read_bytes() == payload
    assert not any(path.exists() for path in (backups.tar, backups.checksum, backups.manifest))
    recovered = json.loads(journal.read_text(encoding="utf-8"))
    assert recovered["state"] == "cleanup-required"
    assert recovered["output_recovered"] is True
