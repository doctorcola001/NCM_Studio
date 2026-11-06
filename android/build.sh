#!/usr/bin/env bash
# Android 打包入口。别直接 buildozer —— 见下。
#
# 为什么需要这个脚本：
#   buildozer 只打包 buildozer.spec 所在目录（source.dir = .），
#   而转换核心 ncmdump/ 在项目根，不在 android/ 里。
#   不先同步过来，APK 能编出来，但装到手机上一点「开始转换」就 ImportError。
#
# 用法：
#   bash android/build.sh              # debug APK
#   bash android/build.sh release      # release APK（需先配签名）
#   bash android/build.sh aab          # AAB
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v buildozer >/dev/null 2>&1; then
    echo "找不到 buildozer。先装：" >&2
    echo "  python3 -m venv ~/.venvs/bz && source ~/.venvs/bz/bin/activate" >&2
    echo "  pip install buildozer cython==0.29.36" >&2
    exit 1
fi

# If buildozer is on PATH from a venv but VIRTUAL_ENV was not exported,
# python-for-android may incorrectly try a --user install inside that venv.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    BUILDOZER_BIN="$(command -v buildozer)"
    case "$BUILDOZER_BIN" in
        */bin/buildozer)
            BUILDOZER_ENV="${BUILDOZER_BIN%/bin/buildozer}"
            if [[ -f "$BUILDOZER_ENV/pyvenv.cfg" ]]; then
                export VIRTUAL_ENV="$BUILDOZER_ENV"
            fi
            ;;
    esac
fi

# The generated Gradle wrapper targets a JDK 17 era toolchain. Android Studio's
# bundled JBR can be much newer, so prefer the distro JDK 17 when it is present.
JAVA17_HOME="${JAVA17_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
if [[ -x "$JAVA17_HOME/bin/javac" ]]; then
    export JAVA_HOME="$JAVA17_HOME"
    export PATH="$JAVA_HOME/bin:$PATH"
fi

echo "==> 同步核心到 android/ncmdump（构建产物，勿手改）"
rm -rf ncmdump
cp -r ../ncmdump ./ncmdump

if [[ -d ../android/fonts ]] && [[ ! -f fonts/NotoSansSC-Regular.otf ]]; then
    echo "警告：字体缺失，中文会显示成方框" >&2
fi

TARGET="${1:-debug}"
echo "==> buildozer android $TARGET"
buildozer -v "android" "$TARGET"

echo "==> 产物："
ls -lh bin/*.apk bin/*.aab 2>/dev/null || true
