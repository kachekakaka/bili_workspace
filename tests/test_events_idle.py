
from types import SimpleNamespace

from app.task_ownership_api import _sse_counts_changed


def _fake_queue(count: int):
    return SimpleNamespace(change_count=lambda: count)


def test_sse_counts_changed_reports_first_frame():
    changed, library, export = _sse_counts_changed(
        _fake_queue(0), _fake_queue(0), last_library=-1, last_export=-1
    )
    assert changed is True
    assert (library, export) == (0, 0)


def test_sse_counts_unchanged_while_idle():
    changed, library, export = _sse_counts_changed(
        _fake_queue(3), _fake_queue(7), last_library=3, last_export=7
    )
    assert changed is False
    assert (library, export) == (3, 7)


def test_sse_counts_changed_on_library_update():
    changed, library, export = _sse_counts_changed(
        _fake_queue(4), _fake_queue(7), last_library=3, last_export=7
    )
    assert changed is True
    assert (library, export) == (4, 7)


def test_sse_counts_changed_on_export_update():
    changed, library, export = _sse_counts_changed(
        _fake_queue(3), _fake_queue(8), last_library=3, last_export=7
    )
    assert changed is True
    assert (library, export) == (3, 8)
