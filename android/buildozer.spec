[app]
title = NCM Studio
package.name = ncmstudio
package.domain = org.wb40
version = 2.0.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,txt,json
source.include_patterns = ncmdump/*.py,fonts/*.otf
source.exclude_dirs = tests,build,__pycache__,.venv
source.exclude_patterns = tests/data/*,*.ncm,*.part

# pycryptodome 走 python-for-android 官方 recipe；mutagen 是纯 Python
requirements = python3,kivy==2.3.1,pycryptodome,mutagen

orientation = portrait
fullscreen = 0

# Android 11+ 分区存储：读音频需要 READ_MEDIA_AUDIO（33+）或 READ_EXTERNAL_STORAGE（<=32）
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True
android.release_artifact = aab

[buildozer]
log_level = 2
warn_on_root = 1
