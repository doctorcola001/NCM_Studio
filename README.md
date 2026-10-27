# NCM Studio 2.0

网易云音乐 `.ncm` 转换器，重写自 `NCM_Tool_v1.0.0.exe`。桌面端 PyQt6，Android 端 Kivy，
转换核心是一份独立的纯 Python 库（`ncmdump`），两端共用。

## 现在是什么状态

| 部分 | 状态 |
|---|---|
| 转换核心 `ncmdump/core.py` | 完成，54 项测试全绿，与出厂字节码对拍一致 |
| 桌面端 `desktop/app.py` | 完成，GUI 与 `--cli` 均实测可用 |
| Windows 包 | 已构建：`dist/NCM_Studio.exe`（39.5 MB，单文件，无控制台） |
| Android 端 `android/main.py` | 代码完成，逻辑在桌面上跑通 |
| Android APK | **未构建**。Buildozer 需要 Linux，本机 WSL 被安全策略拦截，见 `android/BUILD.md` |

## 快速开始

```bash
# 依赖（venv 按家规放 hermestools）
D:/FORDS/hermestools/venvs/ncm-py313/Scripts/python.exe -m pip install -r requirements.txt

# 桌面 GUI
python desktop/app.py

# 批量（无界面）
python desktop/app.py --cli D:/music -o D:/out --overwrite

# 测试
python -m pytest tests -q
```

打包：

```bash
pyinstaller build/ncm_studio.spec --noconfirm
```

## 目录

```
ncmdump/core.py        转换核心（流式解密、元数据、标签、异常分类）
desktop/app.py         桌面端（GUI + --cli）
android/main.py        Android 端（Kivy，含权限与输出目录处理）
android/fonts/         思源黑体 GB2312 子集（Kivy 默认字体没有中文）
android/buildozer.spec 打包配置
android/BUILD.md       APK 构建的两条路径
tools/ncm_encode.py    NCM 封装器（造测试样本）
tools/ref_dump310.py   用便携 3.10 执行出厂字节码，做参照实现
tests/                 54 项测试
build/ncm_studio.spec  PyInstaller 配置
```

## 怎么验证的（这段是关键）

本机**没有任何真实 `.ncm` 样本**，也没法直接相信"看起来能跑"。所以做了两层验证：

**第一层：往返。** `tools/ncm_encode.py` 把真实 mp3/flac 封成 NCM，再解回来逐字节比对。
问题在于这一层是**循环的**——编码器和解码器用同一套 keystream，算法错了两边会互相抵消，
测试照样绿。

**第二层：对拍。** 真正的证据是拿**出厂实现**当参照。原 exe 里打包的是 Python 3.10 字节码
（`NCM_Tool_v1.0.0_extracted/PYZ-00.pyz/ncmdump/core.pyc`，7943 字节），3.13 加载不了，
反编译也失败（交接包里的"反编译源码"其实是空壳，只有 4 行注释头，`gui_dis` 是 0 字节）。
于是下了个便携版 Python 3.10，直接把那份原始字节码跑起来，与重构实现输出逐字节对比：

```
tests/test_core.py::test_matches_shipped_implementation  (5 个用例，mp3/flac/长文件/带封面)
```

同一份 NCM，出厂实现和重构实现解出的音频**完全一致**，且都等于原始音频。
这同时说明：编码器产出的 NCM 结构是真实的（出厂解码器认），重构的解码器行为与出厂等价。

覆盖的边界：跨 1 MiB 分块的 keystream 续接、非 256 对齐的尾块、无元数据区的格式嗅探、
文件截断、损坏头部、写入中途失败后的临时文件清理、跳过/覆盖语义、文件名非法字符。

## 相比交接版修掉的问题

交接版（codex 版）代码能跑，但在真机上和实际使用中会翻车，逐条列：

| 问题 | 后果 | 现在 |
|---|---|---|
| `self.list.dropEvent = self.drop` 给实例挂属性 | Qt 的事件分发走类型虚函数，实例属性不会被调用，**拖放完全不生效** | 子类化 `DropTree`，重写 `dragEnterEvent/dropEvent` |
| 进度条只在全部结束时 `setValue` | 长任务看着像卡死 | `dump()` 支持逐字节回调，双进度条（总进度 + 当前文件） |
| 无元数据时按 `>16MB` 猜格式 | 小体积 FLAC 被存成 `.mp3`，播放器打不开 | 解密后嗅探文件头（`fLaC` / `ID3` / MPEG 同步字） |
| `f.read()` 一次读全曲 | 大文件/低内存设备直接爆 | 1 MiB 分块流式解密 |
| 输出写回源目录 | Android 上源目录常只读，**必然 Permission denied** | 默认写 `Music/NCM Studio`，失败退回应用私有目录 |
| `except: pass` 吞掉异常 | 转换失败静默消失，用户不知道哪些没成 | 逐文件状态 + 失败原因 |
| Kivy 默认字体 | 中文界面全是方框 | 内置思源黑体（GB2312 子集，3.8 MB） |
| 标签写入失败即整首算失败 | 一首歌标签异常，音频白转 | 标签/封面失败只记警告，音频主体保留 |
| mp3 用 vorbis 风格键名写标签 | `audio['title']` 在 mp3 上是 KeyError，标签根本没写进去 | mp3 走 `TIT2/TALB/TPE1` 帧，flac 走 Vorbis Comment |

## 已知限制

1. **没有真实样本**。逻辑再严，也建议先拿几首真歌跑一遍确认。
2. **APK 未构建**。构建路径和坑已写进 `android/BUILD.md`，需要 Linux 环境或 GitHub Actions。
3. **只支持 mp3 / flac**。遇到 Ogg/RIFF 容器会明确报错，不会产出坏文件。
4. **元数据里的 22 字节标识符**（`163 key(Don't modify):`）按原版行为写进 comment，
   没有丢弃，保持与 v1 输出一致。
5. 原 `NCM_Tool_v1.0.0.exe` 未做任何修改，仍留在桌面。
