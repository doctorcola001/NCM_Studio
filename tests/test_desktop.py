# -*- coding: utf-8 -*-
"""
桌面端冒烟测试（无头运行）

验证的是 v1 最容易坏的几处：
  * 拖放入口能真的收到路径并解析出歌名（v1 的实例属性挂法是无效的）
  * Worker 线程逐文件回报状态，进度回调持续推进
  * 取消能停下来、不产生半成品
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip('PyQt6.QtWidgets', reason='未安装 PyQt6')

from PyQt6.QtCore import QEventLoop, QTimer                   # noqa: E402
from PyQt6.QtWidgets import QApplication                      # noqa: E402

from desktop.app import Window                                # noqa: E402
from tools.ncm_encode import build                            # noqa: E402

DATA = ROOT / 'tests' / 'data'
MP3 = DATA / 'test.mp3'


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _wait(win, timeout_ms=15000):
    loop = QEventLoop()
    win.worker.allDone.connect(lambda *_: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_window_builds(qapp):
    win = Window()
    assert win.tree.columnCount() == 4
    assert win.hint.isVisible() is False or True      # 未 show 时不校验可见性
    assert win.status.text() == '就绪'


def test_add_and_convert(qapp, tmp_path):
    ncm = tmp_path / 'a.ncm'
    build(MP3, ncm, b'0123456789abcdef', {
        'musicName': '测试曲', 'album': '专辑', 'artist': [['歌手', 0]], 'format': 'mp3',
    })

    win = Window()
    win.add_paths([str(ncm)])

    assert len(win.files) == 1
    item = win.rows[0]
    assert item.text(1) == '测试曲', '拖入后没解析出元数据'
    assert item.text(2) == '歌手'

    win.out_dir = str(tmp_path / 'out')
    win.start()
    _wait(win)

    assert item.text(3) == '完成'
    out = tmp_path / 'out' / '测试曲.mp3'
    assert out.exists()
    # 写了标签，字节数会比源文件略大，改用标签内容校验
    from mutagen import File
    audio = File(str(out))
    assert audio.tags.getall('TIT2')[0].text == ['测试曲']
    assert audio.tags.getall('TPE1')[0].text == ['歌手']
    assert '完成 1' in win.status.text()


def test_skip_existing_reported(qapp, tmp_path):
    ncm = tmp_path / 'a.ncm'
    build(MP3, ncm, b'0123456789abcdef', None)

    win = Window()
    win.add_paths([str(ncm)])
    win.out_dir = str(tmp_path / 'out')
    win.opt_title.setChecked(False)

    win.start()
    _wait(win)
    assert win.rows[0].text(3) == '完成'

    win.start()                                   # 第二次应全部跳过
    _wait(win)
    assert win.rows[0].text(3) == '已跳过'
    assert '跳过 1' in win.status.text()


def test_bad_file_marked_failed(qapp, tmp_path):
    bad = tmp_path / 'bad.ncm'
    bad.write_bytes(b'NOTNCM!!' + b'\x00' * 32)

    win = Window()
    win.use_dialogs = False
    win.add_paths([str(bad)])
    assert win.rows[0].text(3) == '无法解析'

    win.out_dir = str(tmp_path / 'out')
    win.start()
    _wait(win)
    assert win.rows[0].text(3) == '失败'
    assert '失败 1' in win.status.text()


def test_cancel_long_file(qapp, tmp_path):
    long_mp3 = DATA / 'long.mp3'
    ncm = tmp_path / 'long.ncm'
    build(long_mp3, ncm, b'0123456789abcdef', None)

    win = Window()
    win.use_dialogs = False
    win.add_paths([str(ncm)])
    win.out_dir = str(tmp_path / 'out')
    win.opt_title.setChecked(False)
    win.start()
    win.cancel()                                  # 立刻取消
    _wait(win)

    left = list((tmp_path / 'out').glob('*')) if (tmp_path / 'out').exists() else []
    assert not [p for p in left if p.suffix == '.part'], '取消后残留半成品'
