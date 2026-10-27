# 交接说明 · NCM Studio 2.0

写给下一位接手的 AI/开发者。按「你现在该做什么 → 这堆代码是什么 → 为什么这么写」的顺序看。

- 上一棒：WorkBuddy / 特莉波卡（2026-10-27）
- 再上一棒：Codex（留下的开发包有严重缺陷，见第 6 节，**别照着它改**）
- 当前状态：Windows 端完整可用并在用；**Android APK 尚未构建**，这是你接手后第一件事

---

## 1. 你接手后要做的第一件事：在 Linux 上出 APK

之前的卡点就是没有 Linux 环境——Windows 上 Buildozer 根本跑不起来，本机 WSL 又被安全策略拦截。
现在双系统有了，直接原生跑，不需要 Docker。

```bash
# 依赖（Ubuntu/Debian，一次性）
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
    autoconf libtool pkg-config zlib1g-dev libncurses-dev libffi-dev libssl-dev cmake

# buildozer 自己一个 venv，别污染系统 python
python3 -m venv ~/.venvs/bz
source ~/.venvs/bz/bin/activate
pip install buildozer cython==0.29.36

# 出包：必须用 build.sh，不能直接 buildozer（原因见下）
cd <挂载点>/FORDS/NCM_Studio
export BUILDOZER_HOME=~/.buildozer          # 或指到大盘，首次要下 SDK/NDK 约 4~6 GB
bash android/build.sh debug
```

### ⚠️ 必须先读：不能直接 `buildozer android debug`

`buildozer.spec` 的 `source.dir = .` 只打包 spec 所在目录（`android/`），
而核心 `ncmdump/` 在项目根。**直接 buildozer 打出来的 APK 能装、能开界面，
但一点「开始转换」就 `ModuleNotFoundError: ncmdump`。**

`android/build.sh` 做的就是「先把 `../ncmdump` 同步成 `android/ncmdump` 再构建」。
`android/ncmdump/` 是构建产物，别在那改，会被覆盖；真源始终是项目根的 `ncmdump/`。

产物：`android/bin/ncmstudio-2.0.0-arm64-v8a_armeabi-v7a-debug.apk`

首次构建 15~25 分钟。常见失败点：

| 症状 | 原因 | 处理 |
|---|---|---|
| 装上后一点转换就报 `No module named ncmdump` | 绕过了 `build.sh` | 用 `bash android/build.sh debug` |
| `cython` 编译报错 | buildozer 新版对 cython 3 不兼容 | 固定 `cython==0.29.36` |
| 卡在下载 SDK | 网络 | 配代理，或用 `android.sdk_path` 指本地 SDK |
| `pycryptodome` 编译失败 | NDK/recipe 不匹配 | spec 里 `android.ndk = 25b` 别乱改 |
| 打出来的 APK 中文全是方框 | 字体没打包进去 | 检查 `android/fonts/*.otf` 是否在包内，见第 5 节 |

装到手机上验证时，**必须验这三件**（代码层面只能保证逻辑，这三条只有真机才能确认）：

1. 首次启动的存储权限弹窗；**故意拒绝**，看是否回退到应用私有目录而不是崩
2. `/storage/emulated/0/Music/NCM Studio` 能不能写进去
3. 100 首以上批量转换时的内存和耗时

---

## 2. 项目地图

```
ncmdump/core.py          转换核心。两端共用，纯 Python，不依赖 UI
desktop/app.py           桌面端：PyQt6 GUI + --cli 批量模式（同一个 exe）
android/main.py          Android 端：Kivy
android/build.sh         ★ APK 构建入口，会先同步核心再调 buildozer
android/buildozer.spec   打包配置（权限、api、架构、字体包含规则都在这）
android/ncmdump/         构建时自动生成的副本，别手改
android/fonts/           思源黑体 GB2312 子集，1.9 MB/个。没有它中文全是方框
android/BUILD.md         APK 构建的补充说明（Docker / GitHub Actions / 签名）
build/ncm_studio.spec    PyInstaller 配置（产 Windows 单文件 exe）
tools/ncm_encode.py      NCM 封装器：把 mp3/flac 封成 NCM，用来造测试样本
tools/ref_dump310.py     用 Python 3.10 执行出厂字节码，当参照实现（见第 3 节）
tests/                   54 项测试，3 个文件
.github/workflows/       GitHub Actions 出 APK（不想本地折腾时用）
```

依赖：`pip install -r requirements.txt`（pycryptodome / mutagen / PyQt6 / kivy / pytest / pyinstaller / fonttools）

---

## 3. 这套东西怎么验证的（重要，别省这一步）

**机器上一开始没有任何真实 `.ncm` 样本**，所以不能靠"跑一遍看着有输出"就说对。做了两层：

### 第一层：往返

`tools/ncm_encode.py` 把真 mp3/flac 封成 NCM，`ncmdump.dump()` 解回来，逐字节比对。

**但这层是循环论证**：编码器和解码器共用同一套 keystream，算法错了会互相抵消，测试照样全绿。
单靠这一层没有任何说服力。

### 第二层：与出厂实现逐字节对拍（真正的证据）

原产品 `NCM_Tool_v1.0.0.exe` 里打包的是 **Python 3.10 字节码**：

```
<桌面>/NCM_Tool_v1.0.0_extracted/PYZ-00.pyz/ncmdump/core.pyc     # 7943 字节
```

反编译是失败的（Codex 留下的"NCM_Tool_v1.0.0_src/…/core.py"只有 4 行注释头，`gui_dis` 是 0 字节，
别浪费时间读它）。正确做法是**直接执行字节码**：

```python
import importlib.machinery, importlib.util
loader = importlib.machinery.SourcelessFileLoader('shipped', '/path/to/core.pyc')
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
mod.dump(in_ncm, out_file, skip=False)
```

需要 Python 3.10（bytecode 版本绑定，3.11+ 加载不了）。Linux 上 `apt install python3.10`
或 pyenv 装一个即可。`.pyc` 是跨平台的，Linux 上同样能跑。

`tests/test_core.py::test_matches_shipped_implementation`（5 个用例）就是在跑这条：
同一份 NCM，出厂实现与重构实现解出的音频必须逐字节一致，且都等于原始音频。

> 这个测试里的路径常量写在 `tests/test_core.py` 顶部（`SHIPPED_PYC` / `PY310`），
> 换机器要按实际位置改。找不到时会 skip 而不是 fail——**别因此以为跑过了**。

覆盖到的边界：跨 1 MiB 分块的 keystream 续接、非 256 对齐尾块、无元数据区的格式嗅探、
文件截断、头部损坏、写入中途失败后 `.part` 清理、跳过/覆盖语义、非法文件名。

---

## 4. NCM 格式与解密链（别重新逆向，直接用）

```
[8]    magic  "CTENFDAM"
[2]    保留
[4]    key_len (u32 LE)
[key_len]  key 块：逐字节 ^0x64 → AES-128-ECB 解密（core_key）→ 去 PKCS7 → 切掉前 17 字节
[4]    meta_len
[meta_len] meta 块：逐字节 ^0x63 → 前 22 字节是标识符 "163 key(Don't modify):"
                   → 余下 base64 → AES-128-ECB（meta_key）→ 去 PKCS7 → 切掉前 6 字节 "music:" → JSON
[4]    CRC32（不校验）
[1]    版本
[4]    image_space（封面占位长度，通常 16 字节对齐后的值）
[4]    image_size（真实长度）
[image_size]   封面原始字节
[image_space - image_size]  填充
余下   音频密文：与 keystream 逐字节 XOR
```

常量：

```python
core_key = 687A4852416D736F356B496E62617857
meta_key = 2331346C6A6B5F215C5D2630553C2728
```

keystream：对 key 做标准 RC4 KSA 得 S 盒，然后

```python
table[i] = S[(S[i] + S[(i + S[i]) & 0xFF]) & 0xFF]     # i in 0..255
keystream[i] = table[(i + 1) % 256]                     # 注意这个 +1 偏移
```

**那个 `+1` 是最容易写错的地方**。原版写法是 `stream * n` 后切 `[1:1+len]`，看起来像 bug，
其实是真的从第 1 个字节开始取。`core.py` 里已用 `_build_keystream` 把偏移吸收掉了。

元数据里的 `format` 字段不可全信：缺失时按解密后的文件头嗅探（`fLaC` / `ID3` / MPEG 同步字 `0xFF 0xEx`）。

---

## 5. 已经踩过的坑（别回退）

| 坑 | 后果 | 现状 |
|---|---|---|
| 核心 `ncmdump/` 不在 `android/` 下 | APK 能编能装，一点转换就 ImportError | `android/build.sh` 构建前自动同步 |
| `list.dropEvent = self.drop` 给实例挂属性 | Qt 走类型虚函数，实例属性不会被调用，拖放**完全不生效** | 子类化 `DropTree` 重写事件 |
| 按 `>16MB` 猜格式 | 小 FLAC 被存成 `.mp3`，播放器打不开 | 解密后嗅探文件头 |
| `f.read()` 一次读全曲 | 大文件/低内存设备爆内存 | 1 MiB 分块流式 |
| 输出写回源目录 | Android 分区存储下必 Permission denied | 默认 `Music/NCM Studio`，失败退私有目录 |
| `except: pass` | 转换失败静默消失 | 逐文件状态 + 失败原因 |
| Kivy 默认 Roboto | 中文界面全是方框（这条不修，APK 装了也是废品） | 内置思源黑体，`register_fonts()` 在 import 时顶掉 Roboto |
| mp3 用 `audio['title']` | mp3 的 ID3 不认这个键，标签**根本没写进去** | mp3 走 `TIT2/TALB/TPE1` 帧，flac 走 Vorbis Comment |
| 标签写失败即整首失败 | 一首歌标签异常，音频白转 | 只记警告，音频保留 |
| PyInstaller 窗口程序无控制台 | `--cli` 模式 print 丢失/乱码 | `AttachConsole(-1)` + `SetConsoleOutputCP(65001)` + `reconfigure(encoding='utf-8')` |

字体子集化（改字号/换字体时用）：

```bash
python -m fontTools.subset 源字体.otf --unicodes-file=codes.txt --output-file=输出.otf
```

`codes.txt` 是 GB2312 全集 + Latin-1 + 常用标点/符号的码位，一个一行十六进制。

---

## 6. 关于 Codex 留下的那份开发包

`NCM_Tool_v2_dev.zip` / `NCM_Tool_Android_dev.zip` 里的代码**能跑但会在真机上翻车**，
核心问题已在第 5 节列全。特别是 Android 版：写回源目录 + 无权限申请 + 无中文字体，
装上去基本不可用。要参考可以，别当基线。

唯一值得保留的是它对 NCM 算法的搬运（`ncmdump/core.py` 与出厂版一致）——这部分已完整保留在新核心中。

原 `NCM_Tool_v1.0.0.exe` **不要修改**，留在原处（Windows 桌面）。

---

## 7. 已知限制 / 未完成

1. **APK 未构建、未在真机验证**。这是最大的一块空白。
2. **没有真实 `.ncm` 样本做过回归**。所有测试样本都是自己封装的，结构合规但与网易云实际写出的文件
   是否 100% 同构，只有拿真歌跑过才知道。建议第一步先跑 20~30 首混批（mp3 + flac）。
3. 仅支持 mp3 / flac。遇到 Ogg/RIFF 会明确报错，不产出坏文件。
4. 元数据里 22 字节标识符按原版行为写进 comment/description，没丢弃（保持与 v1 输出一致）。
5. `--cli` 模式没有并发，大批量是串行的。
6. `tests/test_desktop.py` 用 `QT_QPA_PLATFORM=offscreen` 跑，弹窗已被 `use_dialogs=False` 关掉。

---

## 8. 两边的环境

- **Windows 侧**：venv 在 `D:\FORDS\hermestools\venvs\ncm-py313`（Python 3.13），
  装了 pycryptodome 4.2.0 / mutagen 1.48.1 / PyQt6 6.11 / kivy 2.3.1 / pyinstaller 6.22.3。
  `dist/NCM_Studio.exe` 是这条链产出的，GUI 与 `--cli` 都实测过。
- **Linux 侧**：这个包里的 venv 都用不了（跨平台），重新建。核心和测试是跨平台的，
  `python3 -m pytest tests -q` 应该直接过（ref 对拍那 5 项会 skip，除非你装好 3.10 并改路径）。
- **磁盘挂载**：D 盘在 Linux 下的挂载点因人而异，`findmnt -T <路径>` 或 `lsblk -f` 确认，
  挂载后注意 NTFS 的大小写与权限（测试会写临时文件，用 `/tmp` 更稳）。

---

## 9. 约定

- 别往作业提交目录塞工具、缓存、venv；统一放 `hermestools/`（这条对家里所有 agent 通用）。
- 产物命名别带个人信息；这个包里的路径常量已尽量用占位符，改代码时保持一致。
- 改了核心逻辑，**先跑 `pytest tests -q` 再提交**。ref 对拍那几项如果 skip 了，说明你没在验真东西。
