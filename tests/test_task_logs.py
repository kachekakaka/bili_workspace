from pathlib import Path

from app.task_logs import append_task_log, read_task_log, task_log_path


def test_task_log_persists_and_redacts_sensitive_values(tmp_path: Path):
    task_id = "abcdef123456"
    cookie_fields = (
        "SESS" + "DATA=super-secret-session; "
        + "bili" + "_jct=csrf-secret; "
        + "Dede" + "UserID=123456"
    )
    text = (
        f"Cookie: {cookie_fields}\n"
        "Authorization: Bearer dangerous-token\n"
        "普通日志\r进度 50%\n"
    )
    cleaned, size = append_task_log(tmp_path, task_id, text)
    assert size > 0
    assert "super-secret" not in cleaned
    assert "csrf-secret" not in cleaned
    assert "dangerous-token" not in cleaned
    data = read_task_log(tmp_path, task_id, tail_chars=10000)
    assert "***" in data["text"]
    assert "普通日志\n进度 50%" in data["text"]
    assert task_log_path(tmp_path, task_id).is_file()


def test_task_log_tail_marks_truncation(tmp_path: Path):
    task_id = "123456abcdef"
    append_task_log(tmp_path, task_id, "A" * 5000)
    data = read_task_log(tmp_path, task_id, tail_chars=100)
    assert data["text"] == "A" * 100
    assert data["truncated"] is True


def test_delete_task_log_is_scoped_and_removes_file(tmp_path: Path):
    from app.task_logs import delete_task_log

    task_id = "fedcba654321"
    append_task_log(tmp_path, task_id, "hello\n")
    assert delete_task_log(tmp_path, task_id) is True
    assert not task_log_path(tmp_path, task_id).exists()
    assert delete_task_log(tmp_path, task_id) is False
