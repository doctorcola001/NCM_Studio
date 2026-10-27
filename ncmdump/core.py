# -*- coding: utf-8 -*-
"""
NCM Studio 转换核心

算法来源：NCM_Tool_v1.0.0.exe 反编译出的 ncmdump/core.py（原作者 Nzix）。
解密流程与原始实现**字节级一致**，本文件的改动只在工程层面：

  * 音频流改为分块流式解密（原版 f.read() 一次性读全曲，大文件 / 手机上容易爆内存）
  * 无元数据时按解密后的文件头嗅探真实格式（原版按 >16MB 猜 flac，会猜错）
  * 输出目录、覆盖策略、逐字节进度回调、异常分类、文件名安全化
  * 标签 / 封面写入失败不影响音频主体（原版直接抛异常，整首记作失败）

关键细节：keystream 从表的第 1 个字节开始取用（下标 (i + 1) % 256）。
原版靠 `stream * n` 后切片 `[1:1+len]` 实现，这里按块等价计算。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from Crypto.Util.strxor import strxor

MAGIC = binascii.a2b_hex('4354454e4644414d')            # b'CTENFDAM'
CORE_KEY = binascii.a2b_hex('687A4852416D736F356B496E62617857')
META_KEY = binascii.a2b_hex('2331346C6A6B5F215C5D2630553C2728')
KEY_PREFIX = b'neteasecloudmusic'                        # 17 字节，解密后切掉
META_PREFIX = b'music:'                                  # 6 字节，解密后切掉
ID_PREFIX_LEN = 22                                       # "163 key(Don't modify):"

CHUNK = 1 << 20                                          # 1 MiB 一块

SUPPORTED_FORMATS = ('mp3', 'flac')


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class NCMError(Exception):
    """所有转换错误的基类，调用方只需捕获这一个。"""


class NotNCMError(NCMError):
    """文件头不是 CTENFDAM，不是合法 NCM。"""


class CorruptNCMError(NCMError):
    """结构损坏或截断，无法解析。"""


class UnsupportedFormatError(NCMError):
    """解出的音频不是受支持的容器格式。"""


# --------------------------------------------------------------------------- #
# 元数据
# --------------------------------------------------------------------------- #
@dataclass
class NcmInfo:
    path: str
    fmt: str = ''                        # 'mp3' / 'flac'，元数据缺失时可能为空
    music_name: str = ''
    album: str = ''
    artists: list = field(default_factory=list)
    identifier: str = ''
    cover: bytes | None = None
    cover_mime: str = ''
    has_meta: bool = False
    audio_offset: int = 0
    audio_size: int = 0
    warnings: list = field(default_factory=list)

    @property
    def artist_text(self) -> str:
        return '/'.join(self.artists) if self.artists else ''


def read_info(path: str | os.PathLike) -> NcmInfo:
    """只解析头部，不解密音频。用于列表预览与快速筛选。"""
    p = Path(path)
    with open(p, 'rb') as f:
        info = NcmInfo(path=str(p))
        _parse_header(f, info)
        info.audio_offset = f.tell()
    info.audio_size = p.stat().st_size - info.audio_offset
    return info


def _read_exact(f, n: int, what: str) -> bytes:
    buf = f.read(n)
    if len(buf) != n:
        raise CorruptNCMError(
            f'文件在读取「{what}」时提前结束（需要 {n} 字节，实际 {len(buf)}）')
    return buf


def _u32(f, what: str) -> int:
    return struct.unpack('<I', _read_exact(f, 4, what))[0]


def _parse_header(f, info: NcmInfo):
    """填充 info 的头部字段，文件指针停在音频数据起点；返回派生出的密钥。"""
    if _read_exact(f, 8, '文件头') != MAGIC:
        raise NotNCMError('不是 NCM 文件（文件头不是 CTENFDAM）')

    f.seek(2, 1)                                          # 2 字节保留位

    # ---- 密钥区：XOR 0x64 → AES-ECB 解密 → 去填充 → 切掉 17 字节前缀 ----
    key_len = _u32(f, '密钥长度')
    if key_len == 0 or key_len > (1 << 20):
        raise CorruptNCMError(f'密钥长度异常：{key_len}')
    raw = bytes(b ^ 0x64 for b in _read_exact(f, key_len, '密钥数据'))
    try:
        plain = unpad(AES.new(CORE_KEY, AES.MODE_ECB).decrypt(raw), 16)
    except (ValueError, KeyError) as exc:
        raise CorruptNCMError(f'密钥解密失败：{exc}') from exc
    key = plain[len(KEY_PREFIX):]
    if not key:
        raise CorruptNCMError('派生密钥为空')

    # ---- 元数据区：XOR 0x63 → 前 22 字节标识符 → 余下 base64 → AES-ECB ----
    meta_len = _u32(f, '元数据长度')
    if meta_len:
        blob = bytes(b ^ 0x63 for b in _read_exact(f, meta_len, '元数据'))
        try:
            identifier = blob[:ID_PREFIX_LEN].decode('utf-8')
            payload = base64.b64decode(blob[ID_PREFIX_LEN:])
            dec = unpad(AES.new(META_KEY, AES.MODE_ECB).decrypt(payload), 16)
            meta = json.loads(dec[len(META_PREFIX):].decode('utf-8'))
            info.identifier = identifier
        except Exception:
            meta = {}                                     # 元数据坏掉不该毁掉整首歌
        info.has_meta = bool(meta)
        info.fmt = str(meta.get('format') or '').lower()
        info.music_name = str(meta.get('musicName') or '')
        info.album = str(meta.get('album') or '')
        for item in meta.get('artist') or []:
            if isinstance(item, (list, tuple)) and item:
                info.artists.append(str(item[0]))
            elif isinstance(item, str):
                info.artists.append(item)

    f.seek(5, 1)                                          # 4 字节 CRC + 1 字节版本

    # ---- 封面：image_space 是占位总长，image_size 是真实长度 ----
    space = _u32(f, '封面占位长度')
    size = _u32(f, '封面长度')
    if size:
        if size > space:
            raise CorruptNCMError(f'封面长度 {size} 大于占位长度 {space}')
        info.cover = _read_exact(f, size, '封面数据')
        info.cover_mime = 'image/png' if info.cover[:4] == b'\x89PNG' else 'image/jpeg'
    if space > size:
        f.seek(space - size, 1)

    return key


# --------------------------------------------------------------------------- #
# keystream
# --------------------------------------------------------------------------- #
def _build_keystream(key: bytes) -> bytes:
    """RC4 KSA 得 S 盒后派生 256 字节流，并预先按原版的 +1 偏移排好。"""
    klen = len(key)
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % klen]) & 0xFF
        S[i], S[j] = S[j], S[i]

    table = bytes(S[(S[i] + S[(i + S[i]) & 0xFF]) & 0xFF] for i in range(256))
    return table[1:] + table[:1]                          # 第 i 字节 = table[(i+1) % 256]


def _keystream_slice(ks: bytes, offset: int, length: int) -> bytes:
    start = offset % 256
    end = start + length
    if end <= 256:
        return ks[start:end]
    return (ks * (end // 256 + 1))[start:end]


# --------------------------------------------------------------------------- #
# 文件名
# --------------------------------------------------------------------------- #
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | \
            {f'COM{i}' for i in range(1, 10)} | \
            {f'LPT{i}' for i in range(1, 10)}


def safe_stem(name: str, limit: int = 120) -> str:
    """压成跨平台安全的文件名主干（Windows 非法字符 / 保留名 / 长度）。"""
    name = _ILLEGAL.sub('_', name).strip().strip('.')
    name = re.sub(r'\s+', ' ', name)
    if not name:
        return 'untitled'
    if name.split('.')[0].upper() in _RESERVED:
        name = '_' + name
    return name[:limit].rstrip() or 'untitled'


# --------------------------------------------------------------------------- #
# 格式嗅探
# --------------------------------------------------------------------------- #
def _sniff_format(head: bytes) -> str:
    """按解密后的真实字节判断容器格式。无法判断时返回空串。"""
    if head[:4] == b'fLaC':
        return 'flac'
    if head[:3] == b'ID3':
        return 'mp3'
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return 'mp3'                                      # MPEG 帧同步字
    if head[:4] in (b'OggS', b'RIFF', b'M4A ', b'ftyp'):
        raise UnsupportedFormatError(
            f'解出的音频是 {head[:4]!r} 容器，仅支持 mp3 / flac')
    return ''


def unique_path(path: Path) -> Path:
    """目标已存在时追加 (1)(2)…，供 UI 的“保留两份”模式使用。"""
    if not path.exists():
        return path
    for i in range(1, 10000):
        cand = path.with_name(f'{path.stem} ({i}){path.suffix}')
        if not cand.exists():
            return cand
    raise NCMError(f'无法为 {path.name} 生成不冲突的文件名')


# --------------------------------------------------------------------------- #
# 标签写入
# --------------------------------------------------------------------------- #
def _write_tags(path: Path, info: NcmInfo, tag: bool) -> list[str]:
    """
    写标题/专辑/艺术家/封面。任何失败都只记录警告，不回滚音频。

    mp3 与 flac 的标签体系完全不同，必须分开处理：
      flac → Vorbis Comment，键名直接是 title/album/artist，大小写不敏感
      mp3  → ID3v2 帧，必须用 TIT2/TALB/TPE1 这类帧名，'title' 不是合法 ID3 key
    原版混用 EasyMP3 与 MP3，在只有 ID3 头没有 ID3v1 的情况下容易出错。
    """
    warns = []
    if not tag:
        return warns
    try:
        from mutagen import File as MFile
        audio = MFile(str(path))
    except Exception as exc:
        return [f'标签解析失败（不影响音频）：{exc}']
    if audio is None:
        return ['无法识别的音频容器，跳过标签写入']

    if info.fmt == 'flac' and hasattr(audio, 'add_picture'):
        try:
            if info.cover:
                from mutagen import flac
                pic = flac.Picture()
                pic.type, pic.mime, pic.desc = 3, info.cover_mime, 'Cover'
                pic.data = info.cover
                audio.clear_pictures()
                audio.add_picture(pic)
        except Exception as exc:
            warns.append(f'封面写入失败：{exc}')
        try:
            if info.has_meta:
                if info.music_name:
                    audio['title'] = info.music_name
                if info.album:
                    audio['album'] = info.album
                if info.artists:
                    audio['artist'] = info.artist_text
                if info.identifier:
                    audio['description'] = info.identifier
        except Exception as exc:
            warns.append(f'元数据写入失败：{exc}')

    elif info.fmt == 'mp3':
        try:
            from mutagen.id3 import ID3, APIC, COMM, TALB, TIT2, TPE1
            try:
                tags = audio.tags if audio.tags is not None else ID3()
            except Exception:
                tags = ID3()
            if info.cover:
                tags.delall('APIC')
                tags.add(APIC(encoding=0, mime=info.cover_mime, type=3,
                              desc='Cover', data=info.cover))
            if info.has_meta:
                if info.music_name:
                    tags.setall('TIT2', [TIT2(encoding=3, text=[info.music_name])])
                if info.album:
                    tags.setall('TALB', [TALB(encoding=3, text=[info.album])])
                if info.artists:
                    tags.setall('TPE1', [TPE1(encoding=3, text=[info.artist_text])])
                if info.identifier:
                    tags.delall('COMM')
                    tags.add(COMM(encoding=3, lang='eng', desc='', text=[info.identifier]))
            audio.tags = tags
            tags.save(str(path))
            return warns
        except Exception as exc:
            warns.append(f'ID3 写入失败：{exc}')

    else:
        try:
            if info.has_meta:
                if info.music_name:
                    audio['title'] = info.music_name
                if info.album:
                    audio['album'] = info.album
                if info.artists:
                    audio['artist'] = info.artist_text
        except Exception as exc:
            warns.append(f'元数据写入失败：{exc}')

    try:
        audio.save()
    except Exception as exc:
        warns.append(f'标签保存失败：{exc}')
    return warns


# --------------------------------------------------------------------------- #
# 转换
# --------------------------------------------------------------------------- #
def dump(
    input_path: str | os.PathLike,
    output_path: str | os.PathLike | Callable[[NcmInfo], str] | None = None,
    skip: bool = True,
    *,
    out_dir: str | os.PathLike | None = None,
    use_title: bool = False,
    progress: Callable[[int, int], None] | None = None,
    tag: bool = True,
) -> Path | None:
    """
    解密单个 NCM 文件。

    input_path   源 .ncm
    output_path  显式输出路径，或 (info) -> path 的函数
    skip         True 且目标已存在时直接跳过，返回 None（兼容 v1 行为）
    out_dir      输出目录，缺省写回源文件所在目录
    use_title    用歌曲元数据命名（否则沿用源文件主干名）
    progress     progress(done_bytes, total_bytes)，按字节回报进度
    tag          是否写入标签与封面

    返回实际写出的路径；被 skip 跳过时返回 None。
    """
    src = Path(input_path)
    if not src.is_file():
        raise NCMError(f'文件不存在：{src}')

    total_file = src.stat().st_size
    info = NcmInfo(path=str(src))

    with open(src, 'rb') as f:
        key = _parse_header(f, info)
        start = f.tell()
        payload_len = total_file - start
        info.audio_offset, info.audio_size = start, payload_len
        if payload_len <= 0:
            raise CorruptNCMError('文件没有音频数据区（可能被截断）')

        ks = _build_keystream(key)

        # ---- 先解出文件头 16 字节：元数据没写格式时，只能靠真实字节判定 ----
        head_enc = f.read(16)
        head = strxor(head_enc, _keystream_slice(ks, 0, len(head_enc)))
        sniffed = _sniff_format(head)
        if info.fmt not in SUPPORTED_FORMATS:
            info.fmt = sniffed or info.fmt
        if info.fmt not in SUPPORTED_FORMATS:
            raise UnsupportedFormatError('无法判定音频格式：元数据缺失且文件头不可识别')
        f.seek(start)                                     # 回到音频起点，正式开写

        # ---- 目标路径（此时格式已确定，skip 判断才可靠）----
        if callable(output_path):
            target = Path(output_path(info))
        elif output_path:
            target = Path(output_path)
        else:
            stem = safe_stem(info.music_name if (use_title and info.music_name) else src.stem)
            folder = Path(out_dir) if out_dir else src.parent
            target = folder / f'{stem}.{info.fmt}'

        if skip and target.exists() and target.stat().st_size > 0:
            return None

        target.parent.mkdir(parents=True, exist_ok=True)

        tmp = target.with_name(target.name + '.part')
        done = 0
        try:
            with open(tmp, 'wb') as out:
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    out.write(strxor(chunk, _keystream_slice(ks, done, len(chunk))))
                    done += len(chunk)
                    if progress:
                        progress(done, payload_len)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        if done != payload_len:
            tmp.unlink(missing_ok=True)
            raise CorruptNCMError(f'音频数据不完整（读出 {done} / 应有 {payload_len} 字节）')

        tmp.replace(target)

    info.warnings = _write_tags(target, info, tag)
    return target


def dump_many(
    inputs,
    on_result: Callable[[str, Path | None, Exception | None], None] | None = None,
    **kwargs,
):
    """批量转换。on_result(path, out_path_or_None, exc_or_None)。"""
    results = []
    for item in inputs:
        try:
            out = dump(item, **kwargs)
            results.append((item, out, None))
            if on_result:
                on_result(item, out, None)
        except Exception as exc:                          # 单首失败不影响整批
            results.append((item, None, exc))
            if on_result:
                on_result(item, None, exc)
    return results
