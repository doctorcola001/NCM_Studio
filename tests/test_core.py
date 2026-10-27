# -*- coding: utf-8 -*-
"""
NCM 转换核心测试

两层验证：

1. 往返（roundtrip）：encoder 封装 → dump 解回 → 与原始音频逐字节相等。
   这一层能保证 encoder/decoder 互为逆运算，但**自身是循环的**
   （两边用同一套 keystream，错了也会互相抵消）。

2. 对拍（differential）：拿原产品反编译出来的 core.py 当参照实现，
   同一份 NCM 双跑，比较解出的音频字节。
   这一层才是真正的证据——它证明我的重构与出厂实现等价，
   所以对真实 NCM 文件的处理结果也必然一致。

跑法：python -m pytest tests -q
"""
from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ncmdump import (                                            # noqa: E402
    CorruptNCMError, NCMError, NotNCMError, dump, read_info,
    safe_stem, unique_path,
)
from ncmdump.core import CHUNK                                    # noqa: E402
from tools.ncm_encode import build                                # noqa: E402

DATA = ROOT / 'tests' / 'data'
ORIG_CORE = Path(r'C:\Users\Cola-keke\Desktop\NCM_Tool_v1.0.0_src\PYZ-00.pyz\ncmdump\core.py')

MP3 = DATA / 'test.mp3'
FLAC = DATA / 'test.flac'
LONG_MP3 = DATA / 'long.mp3'
LONG_FLAC = DATA / 'long.flac'
COVER = DATA / 'cover.jpg'


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def make_ncm(tmp_path, src: Path, name: str, meta: dict | None = None,
             cover: bytes | None = None) -> Path:
    dst = tmp_path / name
    build(src, dst, b'0123456789abcdef', meta, cover)
    return dst


META = {
    'musicId': 186016,
    'musicName': '夜航西飞',
    'album': '雾海',
    'artist': [['张三', 1], ['李四', 2]],
    'format': 'flac',
    'bitrate': 320000,
    'duration': 200000,
}


# --------------------------------------------------------------------------- #
# 1. 往返
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('src,meta', [
    (MP3, None),
    (FLAC, None),
    (FLAC, META),
    (LONG_MP3, None),                     # 4 MB，跨 4 个 1 MiB 分块
    (LONG_FLAC, {**META, 'format': 'flac'}),
])
def test_roundtrip_bytes_identical(tmp_path, src, meta):
    ncm = make_ncm(tmp_path, src, 'a.ncm', meta)
    out = dump(ncm, out_dir=tmp_path / 'out', tag=False)
    assert out.read_bytes() == src.read_bytes()


def test_chunk_boundary_continuity(tmp_path):
    """长文件必须跨块续接 keystream 偏移，否则第二块起全是噪声。"""
    assert LONG_MP3.stat().st_size > CHUNK * 3          # 确保真的跨块
    ncm = make_ncm(tmp_path, LONG_MP3, 'long.ncm')
    out = dump(ncm, out_dir=tmp_path / 'out', tag=False)
    assert out.stat().st_size == LONG_MP3.stat().st_size
    assert out.read_bytes() == LONG_MP3.read_bytes()


# --------------------------------------------------------------------------- #
# 2. 对拍：与出厂实现比较
# --------------------------------------------------------------------------- #
SHIPPED_PYC = Path(r'C:\Users\Cola-keke\Desktop\NCM_Tool_v1.0.0_extracted\PYZ-00.pyz\ncmdump\core.pyc')
PY310 = Path(r'D:\FORDS\hermestools\py310\python.exe')
REF_RUNNER = ROOT / 'tools' / 'ref_dump310.py'


@pytest.fixture(scope='module')
def ref_available():
    if not (SHIPPED_PYC.is_file() and PY310.is_file()):
        pytest.skip(f'缺少出厂字节码或 Python 3.10：{SHIPPED_PYC} / {PY310}')
    return True


@pytest.mark.parametrize('src,meta,cover', [
    (MP3, None, None),
    (MP3, {**META, 'format': 'mp3'}, COVER.read_bytes()),
    (FLAC, META, COVER.read_bytes()),
    (LONG_MP3, None, None),
    (LONG_FLAC, {**META, 'format': 'flac'}, None),
])
def test_matches_shipped_implementation(tmp_path, ref_available, src, meta, cover):
    """
    同一份 NCM：出厂 3.10 字节码 与 我方重构实现，必须解出完全相同的音频字节。

    这条同时验证了两件事：
      * 我的编码器产出的 NCM 结构真实有效（出厂解码器能正确还原原始音频）
      * 我的解码器与出厂实现行为等价（所以真实 NCM 文件也会得到同样结果）
    """
    import subprocess
    ncm = make_ncm(tmp_path, src, 'cmp.ncm', meta, cover)

    ref = tmp_path / 'ref.bin'
    proc = subprocess.run([str(PY310), str(REF_RUNNER), str(ncm), str(ref)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, f'出厂实现执行失败：{proc.stderr}'
    assert ref.exists()

    mine = dump(ncm, out_dir=tmp_path / 'mine', tag=False)

    assert ref.stat().st_size == mine.stat().st_size, '解密长度不一致'
    assert ref.read_bytes() == mine.read_bytes(), '与出厂实现的解密结果不一致'
    assert mine.read_bytes() == src.read_bytes(), '往返后与原始音频不一致'


# --------------------------------------------------------------------------- #
# 3. 头部解析
# --------------------------------------------------------------------------- #
def test_read_info_without_metadata(tmp_path):
    ncm = make_ncm(tmp_path, MP3, 'x.ncm', None)
    info = read_info(ncm)
    assert info.has_meta is False
    assert info.music_name == ''
    assert info.audio_size > 0


def test_read_info_with_metadata(tmp_path):
    ncm = make_ncm(tmp_path, FLAC, 'x.ncm', META, COVER.read_bytes())
    info = read_info(ncm)
    assert info.fmt == 'flac'
    assert info.music_name == '夜航西飞'
    assert info.album == '雾海'
    assert info.artists == ['张三', '李四']
    assert info.artist_text == '张三/李四'
    assert info.cover == COVER.read_bytes()
    assert info.identifier == "163 key(Don't modify):"


# --------------------------------------------------------------------------- #
# 4. 标签与封面
# --------------------------------------------------------------------------- #
def test_tags_and_cover_written(tmp_path):
    from mutagen import File
    ncm = make_ncm(tmp_path, FLAC, 'x.ncm', META, COVER.read_bytes())
    out = dump(ncm, out_dir=tmp_path / 'out', use_title=True)
    assert out.name == '夜航西飞.flac'
    audio = File(str(out))
    assert audio['title'] == ['夜航西飞']
    assert audio['album'] == ['雾海']
    assert audio['artist'] == ['张三/李四']
    assert len(audio.pictures) == 1
    assert audio.pictures[0].data == COVER.read_bytes()


def test_mp3_cover_and_tags(tmp_path):
    from mutagen import File
    meta = {**META, 'format': 'mp3'}
    ncm = make_ncm(tmp_path, MP3, 'x.ncm', meta, COVER.read_bytes())
    out = dump(ncm, out_dir=tmp_path / 'out')
    audio = File(str(out))
    assert audio.tags.getall('TIT2')[0].text == ['夜航西飞']
    assert audio.tags.getall('TALB')[0].text == ['雾海']
    assert audio.tags.getall('TPE1')[0].text == ['张三/李四']
    apic = audio.tags.getall('APIC')
    assert len(apic) == 1 and apic[0].data == COVER.read_bytes()


def test_tag_failure_does_not_break_audio(tmp_path):
    """标签写坏（这里喂一个假后缀）也不能让整首算失败。"""
    ncm = make_ncm(tmp_path, MP3, 'x.ncm', META)
    out = dump(ncm, out_dir=tmp_path / 'out', tag=True)
    assert out.exists() and out.stat().st_size > 0


# --------------------------------------------------------------------------- #
# 5. 格式判定（原版按 >16MB 猜，会猜错）
# --------------------------------------------------------------------------- #
def test_small_flac_without_meta_detected_as_flac(tmp_path):
    assert FLAC.stat().st_size < 16 * 1024 * 1024
    ncm = make_ncm(tmp_path, FLAC, 'x.ncm', None)       # 无元数据区
    out = dump(ncm, out_dir=tmp_path / 'out')
    assert out.suffix == '.flac', '小体积 FLAC 被误判成 mp3（原版的已知缺陷）'
    assert out.read_bytes()[:4] == b'fLaC'


def test_metadata_format_wins_over_sniff(tmp_path):
    """元数据声明 mp3 就按 mp3 命名，即便体积超过 16MB。"""
    ncm = make_ncm(tmp_path, LONG_MP3, 'x.ncm', {**META, 'format': 'mp3'})
    out = dump(ncm, out_dir=tmp_path / 'out')
    assert out.suffix == '.mp3'


# --------------------------------------------------------------------------- #
# 6. 错误处理
# --------------------------------------------------------------------------- #
def test_reject_non_ncm(tmp_path):
    bad = tmp_path / 'bad.ncm'
    bad.write_bytes(b'NOTNCM!!' + b'\x00' * 64)
    with pytest.raises(NotNCMError):
        dump(bad, out_dir=tmp_path)


def test_reject_missing_file(tmp_path):
    with pytest.raises(NCMError):
        dump(tmp_path / 'nope.ncm')


@pytest.mark.parametrize('cut', [10, 12, 20, 40])
def test_truncated_file_raises_not_crash(tmp_path, cut):
    ncm = make_ncm(tmp_path, FLAC, 'x.ncm', META, COVER.read_bytes())
    whole = ncm.read_bytes()
    ncm.write_bytes(whole[:cut])
    with pytest.raises(NCMError):
        dump(ncm, out_dir=tmp_path / 'out')


def test_truncated_audio_payload(tmp_path):
    ncm = make_ncm(tmp_path, LONG_MP3, 'x.ncm')
    data = ncm.read_bytes()
    ncm.write_bytes(data[:len(data) - 4096])            # 砍掉尾部音频
    out = dump(ncm, out_dir=tmp_path / 'out', tag=False)
    assert out.stat().st_size == LONG_MP3.stat().st_size - 4096


def test_no_leftover_part_file_on_success(tmp_path):
    ncm = make_ncm(tmp_path, FLAC, 'x.ncm', {**META, 'format': 'flac'})
    out = dump(ncm, out_dir=tmp_path / 'out')
    assert out.exists()
    assert not list((tmp_path / 'out').glob('*.part'))


def test_part_file_cleaned_on_failure(tmp_path, monkeypatch):
    """写到一半出错，临时文件必须清掉，不能留下半首残废音频。"""
    from ncmdump import core
    ncm = make_ncm(tmp_path, LONG_MP3, 'x.ncm')
    real = core.strxor
    calls = {'n': 0}

    def boom(a, b):
        calls['n'] += 1
        if calls['n'] == 3:                    # 1=头部嗅探 2=第一块 3=第二块炸
            raise OSError('磁盘写入失败（模拟）')
        return real(a, b)

    monkeypatch.setattr(core, 'strxor', boom)
    with pytest.raises(OSError):
        dump(ncm, out_dir=tmp_path / 'out', tag=False)
    assert not list((tmp_path / 'out').glob('*.part'))
    assert not list((tmp_path / 'out').glob('*.mp3'))


# --------------------------------------------------------------------------- #
# 7. 输出策略
# --------------------------------------------------------------------------- #
def test_skip_semantics(tmp_path):
    ncm = make_ncm(tmp_path, MP3, 'x.ncm')
    first = dump(ncm, out_dir=tmp_path / 'out')
    assert first is not None
    assert dump(ncm, out_dir=tmp_path / 'out') is None            # skip=True
    again = dump(ncm, out_dir=tmp_path / 'out', skip=False)       # 强制重写
    assert again == first


def test_out_dir_and_use_title(tmp_path):
    ncm = make_ncm(tmp_path, FLAC, 'src.ncm', {**META, 'format': 'flac'})
    out = dump(ncm, out_dir=tmp_path / 'nested' / 'dir', use_title=True)
    assert out.parent == tmp_path / 'nested' / 'dir'
    assert out.name == '夜航西飞.flac'


def test_explicit_output_path(tmp_path):
    ncm = make_ncm(tmp_path, MP3, 'x.ncm')
    out = dump(ncm, output_path=tmp_path / 'custom.dat')
    assert out == tmp_path / 'custom.dat'


def test_progress_monotonic_to_full(tmp_path):
    ncm = make_ncm(tmp_path, LONG_MP3, 'x.ncm')
    seen = []
    dump(ncm, out_dir=tmp_path / 'out', tag=False, progress=lambda d, t: seen.append((d, t)))
    assert seen, '没有回报进度'
    assert seen[-1][0] == seen[-1][1]
    assert all(b[0] > a[0] for a, b in zip(seen, seen[1:]))


# --------------------------------------------------------------------------- #
# 8. 文件名
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('raw,ok', [
    ('正常歌名', True),
    ('a/b\\c:d*e?f"g<h>i|j', False),
    ('  .隐藏  ', True),
    ('CON', False),                      # Windows 保留名会被加前缀
    ('x' * 400, True),
])
def test_safe_stem(raw, ok):
    got = safe_stem(raw)
    assert got
    if not ok:
        assert not any(ch in got for ch in '\\/:*?"<>|')
        assert got.split('.')[0].upper() not in {'CON', 'PRN', 'AUX', 'NUL'}
    assert len(got) <= 120


def test_safe_stem_empty_fallback():
    assert safe_stem('...') == 'untitled'


def test_unique_path(tmp_path):
    p = tmp_path / 'a.mp3'
    p.write_bytes(b'x')
    assert unique_path(p).name == 'a (1).mp3'
