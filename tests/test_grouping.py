from __future__ import annotations

from pathlib import Path

from app.artifacts import final_relative_path, remove_relative_target
from app.grouping import MAX_GROUP_LENGTH, normalize_group


def test_group_name_is_safe_for_windows_and_preserves_readability():
    group = normalize_group('  教程/摄影:*?  ')
    assert group.display == '教程-摄影'
    assert group.folder == '教程-摄影'
    assert group.changed is True


def test_windows_reserved_group_name_is_protected():
    assert normalize_group('CON').folder == 'CON-分组'
    assert normalize_group('nul').folder == 'nul-分组'
    assert normalize_group('CON.txt').folder == 'CON-分组.txt'
    assert normalize_group('COM1.log').folder == 'COM1-分组.log'


def test_blank_and_long_group_names_are_normalized():
    assert normalize_group(' ... ').display == '未分组'
    assert len(normalize_group('甲' * 200).folder) == MAX_GROUP_LENGTH


def test_grouped_final_path_and_empty_parent_cleanup(tmp_path: Path):
    relative = final_relative_path('BVTEST001', '摄影教程')
    assert relative == 'groups/摄影教程/items/BVTEST001'
    target = tmp_path / relative
    target.mkdir(parents=True)
    (target / 'demo.mp4').write_bytes(b'video')

    assert remove_relative_target(tmp_path, relative) is True
    assert not target.exists()
    assert not (tmp_path / 'groups' / '摄影教程').exists()
    assert (tmp_path / 'groups').is_dir()
