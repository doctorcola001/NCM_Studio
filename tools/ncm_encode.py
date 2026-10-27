# -*- coding: utf-8 -*-
"""
NCM 封装器（core.dump 的逆运算）

本机没有任何真实 .ncm 样本，因此用这个脚本把普通 mp3 / flac 封成合规 NCM，
再交给 ncmdump.dump 解回来，逐字节比对——这是在没有样本的前提下
唯一能证明解密实现正确的方法。

用法：
    python tools/ncm_encode.py in.mp3 out.ncm --title 歌名 --artist 歌手
    python tools/ncm_encode.py in.flac out.ncm --no-meta
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Crypto.Cipher import AES                                    # noqa: E402
from Crypto.Util.Padding import pad                              # noqa: E402
from Crypto.Util.strxor import strxor                            # noqa: E402

from ncmdump.core import (                                       # noqa: E402
    CORE_KEY, KEY_PREFIX, MAGIC, META_KEY, META_PREFIX, ID_PREFIX_LEN,
    _build_keystream, _keystream_slice,
)

IDENTIFIER = b"163 key(Don't modify):"                           # 恰好 22 字节
assert len(IDENTIFIER) == ID_PREFIX_LEN


def _encrypt_key(key: bytes) -> bytes:
    plain = pad(KEY_PREFIX + key, 16)
    return bytes(b ^ 0x64 for b in AES.new(CORE_KEY, AES.MODE_ECB).encrypt(plain))


def _encrypt_meta(meta: dict | None) -> bytes:
    if not meta:
        return b''
    body = json.dumps(meta, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    plain = pad(META_PREFIX + body, 16)
    blob = IDENTIFIER + base64.b64encode(AES.new(META_KEY, AES.MODE_ECB).encrypt(plain))
    return bytes(b ^ 0x63 for b in blob)


def build(src: Path, dst: Path, key: bytes, meta: dict | None = None,
          cover: bytes | None = None, cover_space: int | None = None) -> Path:
    audio = src.read_bytes()

    cover = cover or b''
    if cover:
        space = cover_space or ((len(cover) + 15) // 16 * 16)
        if space < len(cover):
            raise ValueError('cover_space 必须 >= 封面实际长度')
    else:
        space = 0

    with open(dst, 'wb') as f:
        f.write(MAGIC)
        f.write(b'\x00\x00')
        kb = _encrypt_key(key)
        f.write(struct.pack('<I', len(kb)))
        f.write(kb)

        mb = _encrypt_meta(meta)
        f.write(struct.pack('<I', len(mb)))
        if mb:
            f.write(mb)

        # CRC + 版本：原版解码器不校验，这里填真实 crc32 以求结构合规
        f.write(struct.pack('<I', zlib.crc32(cover) & 0xFFFFFFFF))
        f.write(b'\x01')

        f.write(struct.pack('<I', space))
        f.write(struct.pack('<I', len(cover)))
        if cover:
            f.write(cover)
            f.write(b'\x00' * (space - len(cover)))

        ks = _build_keystream(key)
        done = 0
        while done < len(audio):
            chunk = audio[done:done + (1 << 20)]
            f.write(strxor(chunk, _keystream_slice(ks, done, len(chunk))))
            done += len(chunk)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description='把 mp3/flac 封装成 NCM')
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--title', default='测试曲目')
    ap.add_argument('--album', default='测试专辑')
    ap.add_argument('--artist', action='append', default=None)
    ap.add_argument('--format', default=None, help='覆盖元数据里的 format 字段')
    ap.add_argument('--cover', default=None, help='封面图片路径')
    ap.add_argument('--no-meta', action='store_true', help='写 0 长度元数据区')
    ap.add_argument('--key', default='0123456789abcdef')
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    fmt = args.format or ('flac' if src.suffix.lower() == '.flac' else 'mp3')
    meta = None if args.no_meta else {
        'musicId': 1,
        'musicName': args.title,
        'album': args.album,
        'artist': [[a, 0] for a in (args.artist or ['测试歌手'])],
        'format': fmt,
        'bitrate': 320000,
        'duration': 2000,
    }
    cover = Path(args.cover).read_bytes() if args.cover else None
    build(src, dst, args.key.encode(), meta, cover)
    print(f'OK  {dst}  ({dst.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
