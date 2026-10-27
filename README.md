# NCM Studio 2.0

网易云音乐 `.ncm` 转换器，重写自 Nzix 的 `NCM_Tool_v1.0.0`。

桌面端使用 PyQt6，Android 端使用 Kivy，转换核心 `ncmdump` 是一份独立的纯 Python 库，两端共用。

项目地址：<https://github.com/doctorcola001/NCM_Studio>

> 本项目为个人自用工具，在原项目基础上重写和扩展。
> 感谢原作者的分享，具体署名与原项目许可说明见文末「致谢」和「开源协议」。

## 现在是什么状态

| 部分 | 状态 |
|---|---|
| 转换核心 `ncmdump/core.py` | 完成，54 项自动测试全绿，并已用真实 `.ncm` 文件人工回归 |
| 桌面端 `desktop/app.py` | 完成，GUI 与 `--cli` 均实测可用 |
| Windows 包 | 已构建：`dist/NCM_Studio.exe`（单文件、无控制台） |
| Android 端 `android/main.py` | 代码完成，Buildozer / GitHub Actions 构建链已配置 |
| 实际使用验证 | 人工批量转换无异常，封面与元数据正常保留，速度很快 |

## 功能特点

- 支持网易云音乐 `.ncm` 转 `.mp3` / `.flac`
- 保留歌曲元数据与封面
- 流式解密，1 MiB 分块处理，大文件不一次性读入内存
- 桌面端和 Android 端共用同一份转换核心
- 桌面端支持 GUI 拖放和 `--cli` 批量模式
- Android 端默认输出到 `Music/NCM Studio`，失败时回退到应用私有目录
- 自动嗅探解密后的音频格式，不依赖元数据中的 `format` 字段
- 单文件状态与失败原因可见，不静默吞异常

## 快速开始

```bash
# 安装依赖
python -m pip install -r requirements.txt

# 桌面 GUI
python desktop/app.py

# 批量转换（无界面）
python desktop/app.py --cli /path/to/music -o /path/to/out --overwrite

# 测试
python -m pytest tests -q
```

## 打包

### Windows

```bash
pyinstaller build/ncm_studio.spec --noconfirm
```

产物在 `dist/NCM_Studio.exe`。

### Android APK

推荐使用 GitHub Actions，无需本地配置 Android SDK / NDK：

1. 打开仓库的 Actions 页面
2. 选择 `build-apk`
3. 点击 `Run workflow`
4. 构建完成后下载 Artifact：`ncm-studio-apk`

本地 Linux 构建：

```bash
bash android/build.sh debug
```

产物在 `android/bin/`。

注意：不要直接运行 `buildozer android debug`，必须走 `android/build.sh`，否则 `ncmdump/` 不会被打进 APK。

## 目录结构

```text
ncmdump/core.py        转换核心（流式解密、元数据、标签、异常分类）
desktop/app.py         桌面端（PyQt6 GUI + --cli）
android/main.py        Android 端（Kivy）
android/fonts/         内置中文字体
android/buildozer.spec Android 打包配置
android/build.sh       Android 构建入口，会先同步核心
tools/ncm_encode.py    NCM 封装器，用于生成测试样本
tools/ref_dump310.py   用 Python 3.10 执行出厂字节码作为参照实现
tests/                 自动测试
build/ncm_studio.spec  PyInstaller 配置
.github/workflows/     GitHub Actions 自动构建 APK
```

## 验证情况

### 1. 自动测试

```bash
python -m pytest tests -q
```

覆盖内容包括：

- NCM 往返转换
- 跨 1 MiB 分块的 keystream 续接
- 非 256 对齐的尾块
- 无元数据时的格式嗅探
- 文件截断、损坏头部
- 写入失败后的临时文件清理
- 跳过 / 覆盖语义
- 文件名非法字符
- 标签与封面写入
- Android 端路径与权限逻辑

### 2. 与出厂实现逐字节对拍

测试会将重构实现与 `NCM_Tool_v1.0.0` 中的原始字节码进行输出对比，确认同一份 NCM 解出的音频完全一致。

### 3. 真实文件人工验证

除自动测试外，已使用真实 `.ncm` 文件进行人工批量测试：

- 转换结果正常，无失败文件
- 封面完整保留
- 元数据正常写入
- 转换速度很快，日常批量使用无压力

## 已知限制

1. 仅支持 mp3 / flac；遇到 Ogg、RIFF 等容器会明确报错。
2. 元数据中的 22 字节标识符 `163 key(Don't modify):` 按原版行为保留。
3. `--cli` 模式目前为串行处理，没有并发。
4. Release APK 签名未提交到仓库，正式分发前需要自行配置 keystore。
5. Android 端仍建议在目标真机上验证存储权限、批量转换内存占用和耗时。

## 致谢

本项目的 NCM 解密算法、格式信息和部分实现思路来自 **Nzix** 的开源项目 **NCM_Tool / NCM_Tool_v1.0.0**。

原项目以开源方式发布，本项目是在其基础上的重写与扩展。由于本项目最初属于个人自用开发，事先未联系原作者，在此向 Nzix 表示感谢。

如果原作者对署名、许可方式或代码使用有任何异议，请联系我，我会立即调整署名、许可证或移除相关代码。

感谢所有开源工具与依赖的贡献者，包括但不限于：

- [Kivy](https://kivy.org/)
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- [pycryptodome](https://www.pycryptodome.org/)
- [mutagen](https://mutagen.readthedocs.io/)
- [Buildozer](https://buildozer.readthedocs.io/)
- [python-for-android](https://python-for-android.readthedocs.io/)

## 开源协议

除明确标注来自第三方的代码外，本项目新增的 GUI、Android 封装、构建脚本、文档与工具代码采用 **MIT License**。

`ncmdump/core.py` 中来源于 Nzix / NCM_Tool 的算法与实现思路，版权归原作者所有。若原项目另有明确许可证，则相关部分优先遵循原项目许可证。

完整协议见仓库中的 [`LICENSE`](LICENSE)。
