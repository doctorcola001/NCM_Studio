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
requirements = python3,kivy==2.3.1,pycryptodome,mutagen,filetype

orientation = portrait
fullscreen = 0

# SAF lets users select inputs; scoped-storage MediaStore publishes outputs.
# Legacy permissions are requested only on Android 9 and older.
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True
android.release_artifact = aab

# 固定 python-for-android 版本，避免 master 默认使用 Python 3.14
# v2024.01.21 使用 Python 3.11.5，兼容当前 NDK 25b 与依赖轮子
# 注意：buildozer 只从 [app] 段读 p4a.branch，写进 [buildozer] 段会被静默忽略
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
