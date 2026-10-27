# -*- coding: utf-8 -*-
"""
Android 端逻辑测试（跑在桌面上）

Kivy 在无显示环境里拿不到 window provider，所以测试前把 main.Window 换成桩，
其余（widget 树构建、选文件展开、批量转换、取消）都是真跑的。

真正上真机才能验的部分：权限弹窗、/storage 路径可写性、buildozer 打包。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'android'))

pytest.importorskip('kivy', reason='未安装 Kivy')

import main                                                  # noqa: E402
from kivy.clock import Clock                                  # noqa: E402
from tools.ncm_encode import build                          # noqa: E402

DATA = ROOT / 'tests' / 'data'
MP3 = DATA / 'test.mp3'


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'Window', types.SimpleNamespace(clearcolor=None))
    monkeypatch.setattr(main, 'output_root', lambda: tmp_path / 'out')
    a = main.NCMApp()
    a.build()
    return a


def make_ncm(tmp_path, name, meta=None):
    ncm = tmp_path / name
    build(MP3, ncm, b'0123456789abcdef', meta)
    return ncm


# --------------------------------------------------------------------------- #
# 纯逻辑
# --------------------------------------------------------------------------- #
def test_collect_ncm_expands_dirs_and_dedups(tmp_path):
    d = tmp_path / 'a'
    d.mkdir()
    n1 = make_ncm(tmp_path, 'x.ncm')
    n2 = make_ncm(d, 'y.ncm')
    (d / 'ignore.mp3').write_bytes(b'x')
    got = main.collect_ncm([str(n1), str(d), str(n1)])
    assert len(got) == 2, '应去重并展开目录'
    assert any(p.endswith('y.ncm') for p in got)


def test_output_root_is_writable_path():
    root = main.output_root()
    assert isinstance(root, Path)
    assert root.name in ('NCM Studio', 'output', 'NCMStudio')


def test_convert_batch_all_success(tmp_path):
    files = [str(make_ncm(tmp_path, 'a.ncm')), str(make_ncm(tmp_path, 'b.ncm'))]
    done, prog = [], []
    ok, skipped, failed = main.convert_batch(
        files, out_dir=tmp_path / 'out',
        on_progress=lambda i, d, t: prog.append((i, d, t)),
        on_file_done=lambda i, s, d: done.append((i, s)),
    )
    assert (ok, skipped, failed) == (2, 0, 0)
    assert len(done) == 2 and all(s == '完成' for _, s in done)
    assert prog and prog[-1][1] == prog[-1][2]
    assert len(list((tmp_path / 'out').glob('*.mp3'))) == 2


def test_convert_batch_reports_failure_reason(tmp_path):
    bad = tmp_path / 'bad.ncm'
    bad.write_bytes(b'NOTNCM!!' + b'\x00' * 40)
    done = []
    ok, skipped, failed = main.convert_batch(
        [str(bad)], out_dir=tmp_path / 'out',
        on_file_done=lambda i, s, d: done.append((s, d)),
    )
    assert failed == 1 and ok == 0
    assert done[0][0] == '失败'
    assert 'NCM' in done[0][1] or '文件头' in done[0][1], '失败原因不该是空的'


def test_convert_batch_skip_existing(tmp_path):
    f = str(make_ncm(tmp_path, 'a.ncm'))
    main.convert_batch([f], out_dir=tmp_path / 'out', use_title=False)
    done = []
    ok, skipped, failed = main.convert_batch(
        [f], out_dir=tmp_path / 'out', use_title=False,
        on_file_done=lambda i, s, d: done.append(s),
    )
    assert skipped == 1 and done == ['已跳过']


def test_convert_batch_cancel(tmp_path):
    files = [str(make_ncm(tmp_path, f'{i}.ncm')) for i in range(3)]
    state = {'n': 0}

    def cancel_when():
        state['n'] += 1
        return state['n'] > 1

    done = []
    ok, skipped, failed = main.convert_batch(
        files, out_dir=tmp_path / 'out', use_title=False,
        on_file_done=lambda i, s, d: done.append(s),
        should_cancel=cancel_when,
    )
    assert ok == 1, '取消后不该继续转'
    assert done.count('已取消') == 2


# --------------------------------------------------------------------------- #
# UI 构建
# --------------------------------------------------------------------------- #
def test_ui_builds(app, tmp_path):
    assert app.chooser.filters == ['*.ncm']
    assert app.chooser.multiselect is True
    assert app.opt_title.active is True
    assert app.opt_skip.active is True
    assert app.progress.max == 1
    assert app.btn_cancel.disabled is True


def test_selection_updates_count(app, tmp_path):
    ncm = make_ncm(tmp_path, 'x.ncm')
    app.on_selection(app.chooser, [str(ncm)])
    assert app.files == [str(ncm)]
    assert '1' in app.count_label.text


def test_full_ui_conversion(app, tmp_path):
    ncm = make_ncm(tmp_path, 'x.ncm', {'musicName': '夜航西飞', 'format': 'mp3'})
    app.on_selection(app.chooser, [str(ncm)])
    app._work(list(app.files), tmp_path / 'out')      # 同步跑，跳过线程
    Clock.tick()
    assert '完成 1' in app.status.text
    assert (tmp_path / 'out' / '夜航西飞.mp3').exists()


def test_ui_logs_failure(app, tmp_path):
    bad = tmp_path / 'bad.ncm'
    bad.write_bytes(b'NOTNCM!!' + b'\x00' * 40)
    app.on_selection(app.chooser, [str(bad)])
    app._work(list(app.files), tmp_path / 'out')
    Clock.tick()
    assert '失败 1' in app.status.text
    assert 'bad.ncm' in app.log_label.text


def test_start_without_selection_warns(app):
    app.files = []
    app.start()
    assert '请先' in app.status.text
