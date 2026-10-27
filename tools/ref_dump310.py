# -*- coding: utf-8 -*-
"""
用出厂字节码当参照实现

NCM_Tool_v1.0.0.exe 里打包的是 Python 3.10 字节码，3.13 根本加载不了，
反编译器（decompyle3）在 3.10 上也失败了（只吐出 4 行注释头）。
所以这里换一条更硬的路：直接用便携版 Python 3.10 执行原始的 core.pyc，
把它的输出当作 ground truth。

只有 3.10 能跑本脚本：
    D:\\FORDS\\hermestools\\py310\\python.exe tools/ref_dump310.py in.ncm out.bin

为了让输出只剩纯音频（便于逐字节对比），mutagen 被替换成空桩。
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

PYC = Path(r'C:\Users\Cola-keke\Desktop\NCM_Tool_v1.0.0_extracted\PYZ-00.pyz\ncmdump\core.pyc')


class _Stub(dict):
    def __init__(self, *a, **k):
        super().__init__()
        self.tags = self

    def __getattr__(self, name):
        return lambda *a, **k: None


def load_shipped_core():
    loader = importlib.machinery.SourcelessFileLoader('shipped_ncmdump_core', str(PYC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.mp3 = types.SimpleNamespace(MP3=_Stub, EasyMP3=_Stub)
    mod.flac = types.SimpleNamespace(FLAC=_Stub, Picture=_Stub)
    mod.id3 = types.SimpleNamespace(APIC=_Stub)
    return mod


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    if sys.version_info[:2] != (3, 10):
        print(f'本脚本需要 Python 3.10，当前 {sys.version.split()[0]}', file=sys.stderr)
        return 2
    core = load_shipped_core()
    core.dump(argv[1], argv[2], skip=False)
    print(f'OK {argv[2]} {Path(argv[2]).stat().st_size} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
