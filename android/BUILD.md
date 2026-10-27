# Android 打包说明

Buildozer 只能在 Linux 上跑。现在有双系统了，**优先走原生 Linux**，不要在 Windows 上折腾。

## 一条命令

```bash
bash android/build.sh          # debug APK
bash android/build.sh release  # release APK（需先配签名）
bash android/build.sh aab      # AAB
```

产物在 `android/bin/`。

### 为什么不能直接 `buildozer android debug`

`buildozer.spec` 里 `source.dir = .`，buildozer **只打包 spec 所在目录**（也就是 `android/`）。
而转换核心 `ncmdump/` 在项目根，不在 `android/` 里。

直接跑 buildozer：编译能过，APK 也能装，但一点「开始转换」就 `ModuleNotFoundError: ncmdump`。
`build.sh` 就是干这件事的——先把 `../ncmdump` 复制成 `android/ncmdump` 再构建。

`android/ncmdump/` 是构建产物，**不要在那里改代码**，下次构建会被覆盖。
核心的唯一真源是项目根的 `ncmdump/`。

## 首次环境

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
    autoconf libtool pkg-config zlib1g-dev libncurses-dev libffi-dev libssl-dev cmake

python3 -m venv ~/.venvs/bz
source ~/.venvs/bz/bin/activate
pip install buildozer==1.5.0 cython==0.29.36
```

首次构建会下载 Android SDK/NDK，约 4~6 GB、15~25 分钟。

`buildozer.spec` 中已固定 `p4a.branch = v2024.01.21`（Python 3.11.5）。
不要随意改回 master，否则 python-for-android 可能默认使用 Python 3.14，
导致 `pycryptodome` / `charset_normalizer` 等依赖没有 Android 轮子而构建失败。

默认缓存在 `~/.buildozer`；想换盘就 `export BUILDOZER_HOME=/data/buildozer`。

## 用 Docker（不想在本机配环境时）

必须挂**项目根**，不是 android 目录：

```bash
cd <项目根>
docker run --rm \
  -v "$PWD":/home/user/hostcwd \
  -v "$HOME/.buildozer":/home/user/.buildozer \
  -w /home/user/hostcwd \
  kivy/buildozer bash android/build.sh
```

## 用 GitHub Actions

仓库带 `.github/workflows/build-apk.yml`，推到 GitHub 手动触发，
APK 作为 artifact 下载。workflow 调的也是 `build.sh`，不会有核心缺失问题。

## 构建时的坑（已在 spec 里处理）

| 坑 | 处理 |
|---|---|
| 核心没进包，运行即 ImportError | `build.sh` 先同步 `ncmdump/` 进 `android/` |
| `pycryptodome` 需要 native 编译 | 用 python-for-android 官方 recipe，写进 requirements 即可 |
| Kivy 默认字体没有中文，界面全是方框 | 内置思源黑体（GB2312 子集，约 1.9 MB/个），启动时顶掉 Roboto |
| Android 11+ 分区存储，写回源目录 Permission denied | 输出默认写 `Music/NCM Studio`，失败退回应用私有目录 |
| API 33 读音频需要新权限 | `READ_MEDIA_AUDIO` + 旧版权限都声明 |
| 只打 arm64 会漏掉老设备 | `arm64-v8a,armeabi-v7a` 双架构 |
| 新版 cython 3 与 buildozer 不兼容 | 固定 `cython==0.29.36` |

## 真机上必须验的三件事

逻辑层面已覆盖（`tests/test_android_logic.py` 11 项），但这三点只有设备能确认：

1. 首次启动的权限弹窗；**故意拒绝**，看是否回退到私有目录而不是崩
2. `/storage/emulated/0/Music/NCM Studio` 是否可写
3. 100 首以上批量转换时的内存与耗时

## Release 签名

spec 里没有写签名配置（避免把 keystore 路径和密码提交进仓库）。
出正式包时自建 keystore，然后在 spec 补：

```ini
android.keystore = /绝对路径/release.keystore
android.keyalias = ncmstudio
```

密码用环境变量传（`P4A_RELEASE_KEYSTORE_PASSWD` 等），或 `buildozer android release`
之后手动 `apksigner` 签名。`android.release_artifact` 已设为 `aab`，要 APK 就改成 `apk`。
