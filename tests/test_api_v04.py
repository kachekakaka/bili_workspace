from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.config import ConfigStore
from app.index_store import IndexStore
from app.queue import TaskQueue
from app.urls import Target
from tests.conftest import FAKE_INFO_OUTPUT, wait_terminal


def test_groups_and_preview_endpoints(client):
    groups = client.get('/api/groups')
    assert groups.status_code == 200
    data = groups.json()['data']
    assert data['default_group'] == '未分组'
    assert data['default_min_height'] == 1080
    assert '未分组' in data['items']

    preview = client.post(
        '/api/preview',
        json={
            'item': {'bvid': 'BV1qt4y1X7TW'},
            'min_height': 1080,
            'preferred_quality': '',
        },
    )
    assert preview.status_code == 200
    result = preview.json()['data']
    assert result['metadata']['title'] == '测试作品标题'
    assert result['bvid'] == 'BV1qt4y1X7TW'
    assert result['quality']['highest_label'] == '4K 超清'
    assert result['quality']['parts'][0]['selected']['height'] == 2160


def test_grouped_download_retains_title_bvid_and_actual_quality(client, tmp_env):
    response = client.post(
        '/api/download',
        json={
            'items': [{
                'bvid': 'BV1qt4y1X7TW',
                'title': '分组测试标题',
                'preferred_quality': '',
            }],
            'group': '教程/摄影',
            'min_height': 1080,
        },
    )
    assert response.status_code == 200
    task = wait_terminal(client.state_ref.queue, response.json()['data'][0]['id'])
    assert task['status'] == 'success'
    assert task['title'] == '分组测试标题'
    assert task['bvid'] == 'BV1qt4y1X7TW'
    assert task['group'] == '教程-摄影'
    assert task['output_path'].startswith('groups/教程-摄影/items/')
    assert task['min_height'] == 1080
    assert task['quality_checked'] is True
    assert task['quality_verified'] is True
    assert task['quality_expected_parts'] == 1
    assert task['quality_verified_parts'] == 1
    assert task['selected_quality'] == '4K 超清'
    assert task['selected_resolution'] == '3840x2160'
    assert task['selected_height'] == 2160
    assert (tmp_env.download_dir / task['output_path'] / 'demo.mp4').is_file()

    entry = client.state_ref.index.get('BV1qt4y1X7TW')
    assert entry is not None
    assert entry['group'] == '教程-摄影'
    assert entry['selected_quality'] == '4K 超清'


def test_minimum_above_available_quality_fails_without_media(client, tmp_env):
    response = client.post(
        '/api/download',
        json={'bvids': ['BV0000000404'], 'group': '高画质', 'min_height': 4320},
    )
    task = wait_terminal(client.state_ref.queue, response.json()['data'][0]['id'])
    assert task['status'] == 'failed'
    assert '低于最低要求 8K' in task['error']
    assert client.state_ref.index.get('BV0000000404') is None
    target = tmp_env.download_dir / 'groups' / '高画质' / 'items' / 'BV0000000404'
    assert not target.exists()


def test_force_redownload_can_move_a_work_to_another_group(client, tmp_env):
    first_response = client.post(
        '/api/download',
        json={'bvids': ['BV0000000405'], 'group': '旧分组', 'min_height': 1080},
    )
    first = wait_terminal(client.state_ref.queue, first_response.json()['data'][0]['id'])
    old_dir = tmp_env.download_dir / first['output_path']
    assert old_dir.is_dir()

    second_response = client.post(
        '/api/download',
        json={
            'bvids': ['BV0000000405'],
            'group': '新分组',
            'min_height': 1080,
            'force': True,
        },
    )
    second = wait_terminal(client.state_ref.queue, second_response.json()['data'][0]['id'])
    assert second['status'] == 'success'
    assert second['group'] == '新分组'
    assert second['output_path'].startswith('groups/新分组/items/')
    assert not old_dir.exists()
    assert not (tmp_env.download_dir / 'groups' / '旧分组').exists()


def test_runtime_selected_quality_must_match_explicit_choice(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)

    def runner(argv, **kwargs):
        del kwargs
        if '--only-show-info' in argv:
            return SimpleNamespace(returncode=0, stdout=FAKE_INFO_OUTPUT, stderr='')
        work = Path(argv[argv.index('--work-dir') + 1])
        (work / 'unexpected.mp4').write_bytes(b'video')
        return SimpleNamespace(
            returncode=0,
            stdout='[视频] [4K 超清] [3840x2160] [HEVC] [60] [18000kbps]\n',
            stderr='',
        )

    runner.supports_info = True
    runner.supports_quality_output = True
    queue = TaskQueue(store, index, runner=runner, metadata_fetcher=None)
    try:
        target = Target(
            key='BV0000000406',
            url='https://www.bilibili.com/video/BV0000000406',
            bvid='BV0000000406',
        )
        task = queue.enqueue(
            [target],
            group='指定档位',
            min_height=1080,
            metadata={'BV0000000406': {'preferred_quality': '1080P 高清'}},
        )[0]
        done = wait_terminal(queue, task['id'])
        assert done['status'] == 'failed'
        assert '与指定清晰度 1080P 高清 不一致' in done['error']
        assert index.get('BV0000000406') is None
        assert not (tmp_env.download_dir / 'groups' / '指定档位').exists()
    finally:
        queue.stop()


def test_default_group_and_minimum_quality_are_web_editable(client):
    response = client.put(
        '/api/config',
        json={'default_group': '音乐/现场', 'default_min_height': 2160},
    )
    assert response.status_code == 200
    config = response.json()['data']
    assert config['default_group'] == '音乐-现场'
    assert config['default_min_height'] == 2160
    groups = client.get('/api/groups').json()['data']
    assert groups['default_group'] == '音乐-现场'
    assert groups['default_min_height'] == 2160



def test_indexed_download_preserves_unrestricted_minimum(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    relative = 'groups/自由画质/items/BV0000000407'
    target_dir = tmp_env.download_dir / relative
    target_dir.mkdir(parents=True)
    media = target_dir / '自由画质 [BV0000000407] [720P].mp4'
    media.write_bytes(b'video')
    stat = media.stat()
    index.put(
        'BV0000000407',
        title='自由画质作品',
        path=relative,
        files=[{
            'path': f'{relative}/{media.name}',
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
        }],
        extra={
            'group': '自由画质',
            'min_height': 0,
            'quality_checked': True,
            'quality_verified': True,
            'quality_expected_parts': 1,
            'quality_verified_parts': 1,
            'selected_quality': '720P 高清',
            'selected_resolution': '1280x720',
            'selected_height': 720,
            'selected_tracks': [{
                'index': -1,
                'dfn': '720P 高清',
                'resolution': '1280x720',
                'width': 1280,
                'height': 720,
                'codec': 'AVC',
                'fps': '30',
                'bandwidth_kbps': 2500,
                'size_text': '',
                'part': 1,
            }],
        },
    )

    def unused_runner(*args, **kwargs):
        del args, kwargs
        raise AssertionError('有效索引任务不应再次调用 BBDown')

    queue = TaskQueue(store, index, runner=unused_runner, metadata_fetcher=None)
    try:
        target = Target(
            key='BV0000000407',
            url='https://www.bilibili.com/video/BV0000000407',
            bvid='BV0000000407',
        )
        task = queue.enqueue([target], min_height=1080)[0]
        assert task['status'] == 'skipped'
        assert task['group'] == '自由画质'
        assert task['min_height'] == 0
        assert task['min_height_label'] == '不限制'
        assert task['quality_verified'] is True
        assert task['quality_expected_parts'] == 1
        assert task['quality_verified_parts'] == 1
    finally:
        queue.stop()


def test_multipart_runtime_quality_requires_every_selected_stream(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    info_output = '''
    视频标题：双分段测试
    共计2条视频流.
    0. [4K 超清] [3840x2160] [HEVC] [60] [18000kbps]
    1. [1080P 高清] [1920x1080] [AVC] [30] [6000kbps]
    共计1条视频流.
    0. [1080P 高清] [1920x1080] [HEVC] [30] [7000kbps]
    '''

    def runner(argv, **kwargs):
        del kwargs
        if '--only-show-info' in argv:
            return SimpleNamespace(returncode=0, stdout=info_output, stderr='')
        work = Path(argv[argv.index('--work-dir') + 1])
        (work / 'incomplete-check.mp4').write_bytes(b'video')
        return SimpleNamespace(
            returncode=0,
            stdout='[视频] [4K 超清] [3840x2160] [HEVC] [60] [18000kbps]\n',
            stderr='',
        )

    runner.supports_info = True
    runner.supports_quality_output = True
    queue = TaskQueue(store, index, runner=runner, metadata_fetcher=None)
    try:
        target = Target(
            key='BV0000000408',
            url='https://www.bilibili.com/video/BV0000000408',
            bvid='BV0000000408',
        )
        created = queue.enqueue([target], group='多分P', min_height=1080)[0]
        done = wait_terminal(queue, created['id'])
        assert done['status'] == 'failed'
        assert done['quality_expected_parts'] == 2
        assert done['quality_verified_parts'] == 1
        assert done['quality_verified'] is False
        assert '仅确认了 1/2 个分段' in done['error']
        assert index.get('BV0000000408') is None
        assert not (tmp_env.download_dir / 'groups' / '多分P').exists()
    finally:
        queue.stop()


def test_group_cards_include_active_and_failed_task_counts(client, monkeypatch):
    group = client.state_ref.nas.create_group("待处理课程")
    monkeypatch.setattr(
        client.state_ref.queue,
        "list_tasks",
        lambda: [
            {"status": "queued", "group_id": group["id"], "group": "待处理课程"},
            {"status": "running", "group_id": group["id"], "group": "待处理课程"},
            {"status": "failed", "group_id": group["id"], "group": "待处理课程"},
            {"status": "success", "group_id": group["id"], "group": "待处理课程"},
        ],
    )
    records = client.get("/api/groups").json()["data"]["records"]
    current = next(item for item in records if item["id"] == group["id"])
    assert current["active_count"] == 2
    assert current["failed_count"] == 1
