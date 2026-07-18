from __future__ import annotations

import pytest

from app.quality import (
    QualityError,
    SelectedTrackParser,
    decide_quality,
    height_label,
    parse_selected_line,
    parse_track_blocks,
    quality_labels_match,
)


MULTIPART_OUTPUT = '''
视频标题：多分段测试作品
共计3条视频流.
0. [4K 超清] [3840x2160] [HEVC] [60] [18000kbps] [~1.2 GB]
1. [1080P 高清] [1920x1080] [AVC] [30] [6000kbps] [~450 MB]
2. [720P 高清] [1280x720] [AVC] [30] [2500kbps] [~180 MB]
共计2条视频流.
0. [1080P 高清] [1920x1080] [HEVC] [60] [7000kbps] [~500 MB]
1. [720P 高清] [1280x720] [AVC] [30] [2600kbps] [~190 MB]
'''


def test_parse_multipart_tracks_and_title():
    blocks, title = parse_track_blocks(MULTIPART_OUTPUT)
    assert title == '多分段测试作品'
    assert len(blocks) == 2
    assert [track.height for track in blocks[0]] == [2160, 1080, 720]
    assert blocks[1][0].part == 2


def test_auto_quality_is_checked_for_every_part():
    decision = decide_quality(MULTIPART_OUTPUT, min_height=1080)
    assert decision.highest_height == 2160
    assert len(decision.parts) == 2
    assert decision.parts[0]['selected']['dfn'] == '4K 超清'
    assert decision.parts[1]['selected']['dfn'] == '1080P 高清'
    assert decision.dfn_priority.startswith('4K 超清,1080P 高清')


def test_exact_quality_must_exist_in_every_part():
    decision = decide_quality(
        MULTIPART_OUTPUT,
        min_height=1080,
        preferred_quality='1080P 高清',
    )
    assert all(row['selected']['dfn'] == '1080P 高清' for row in decision.parts)

    with pytest.raises(QualityError, match='第 2 部分没有指定清晰度'):
        decide_quality(MULTIPART_OUTPUT, min_height=1080, preferred_quality='4K 超清')


def test_minimum_quality_failure_is_conservative():
    with pytest.raises(QualityError, match='低于最低要求 8K'):
        decide_quality(MULTIPART_OUTPUT, min_height=4320)
    with pytest.raises(QualityError, match='未能从 BBDown'):
        decide_quality('无法识别的输出', min_height=1080)


def test_vertical_resolution_uses_short_edge_as_quality_height():
    track = parse_selected_line('[视频] [1080P 竖屏] [1080x1920] [HEVC] [30] [5000kbps]')
    assert track is not None
    assert track.height == 1080
    assert track.width == 1080


def test_selected_track_parser_handles_carriage_return_chunks():
    parser = SelectedTrackParser()
    first = parser.feed('[视频] [4K 超清] [3840x2160] [HEVC] [60]')
    assert first == []
    second = parser.feed('[18000kbps]\r下载视频 25%\r')
    assert len(second) == 1
    assert second[0].dfn == '4K 超清'
    assert second[0].height == 2160


def test_quality_label_matching_ignores_harmless_separators_only():
    assert quality_labels_match('1080P 高清', '1080P  高清')
    assert quality_labels_match('4K-超清', '4K 超清')
    assert not quality_labels_match('1080P 高清', '4K 超清')



def test_zero_minimum_label_and_real_output_spacing():
    assert height_label(0) == '不限制'
    output = '''
    共计1条视频流.
    0. [1080 P 高清] [1920 x1080] [HEVC] [23.81] [678 kbps] [~10 MB]
    '''
    decision = decide_quality(output, min_height=1080)
    selected = decision.parts[0]['selected']
    assert selected['dfn'] == '1080 P 高清'
    assert selected['resolution'] == '1920 x1080'
    assert selected['height'] == 1080
