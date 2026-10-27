# -*- coding: utf-8 -*-
"""
NCM Studio · Android 端（Kivy）

相对交接版的改动：
  * 输出目录不再写回源目录。Android 上源文件常在 /storage 只读或受限位置，
    直接写回会 Permission denied —— 这是交接版在真机上必然踩的坑。
    现在默认写到「Music/NCM Studio」，拿不到权限时退回应用私有目录。
  * 运行时申请存储权限（API 33 要 READ_MEDIA_AUDIO，旧版要 READ/WRITE_EXTERNAL_STORAGE）
  * 逐文件进度 + 失败原因可见（交接版 except 里直接 pass，失败等于静默消失）
  * 支持取消；转换跑在后台线程，界面不卡
  * 中文文件名、非法字符都已由 core.safe_stem 处理

buildozer 需要 Linux 环境，见 README。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform

from ncmdump import NCMError, dump, read_info

IS_ANDROID = platform == 'android'
FONT_DIR = Path(__file__).resolve().parent / 'fonts'

BG = (0.055, 0.067, 0.09, 1)
CARD = (0.082, 0.102, 0.137, 1)
ACCENT = (0.184, 0.502, 0.929, 1)
TEXT = (0.9, 0.93, 0.97, 1)
MUTED = (0.55, 0.60, 0.67, 1)


def register_fonts() -> bool:
    """
    用内置思源黑体顶掉 Kivy 默认的 Roboto。

    必须做：Roboto 不含 CJK 字形，不换字体的话所有中文都是方框。
    字体已按 GB2312 全集子集化（约 1.9 MB/个），常规 + 粗体共 3.8 MB。
    """
    regular = FONT_DIR / 'NotoSansSC-Regular.otf'
    bold = FONT_DIR / 'NotoSansSC-Bold.otf'
    if not regular.is_file():
        return False
    from kivy.core.text import LabelBase
    b = bold if bold.is_file() else regular
    LabelBase.register(name='Roboto', fn_regular=str(regular), fn_bold=str(b),
                       fn_italic=str(regular), fn_bolditalic=str(b))
    return True


register_fonts()


# --------------------------------------------------------------------------- #
# 路径与权限（纯逻辑，不依赖 Kivy 组件，便于在桌面上测试）
# --------------------------------------------------------------------------- #
def output_root() -> Path:
    """默认输出目录：Android 走公共音乐目录，失败再退回应用私有目录。"""
    if IS_ANDROID:
        try:
            from android.storage import primary_external_storage_path
            return Path(primary_external_storage_path()) / 'Music' / 'NCM Studio'
        except Exception:
            from android.storage import app_storage_path
            return Path(app_storage_path()) / 'output'
    return Path.home() / 'NCMStudio'


def start_dir() -> str:
    """文件选择器的起始目录。"""
    for cand in (
        '/storage/emulated/0/Download',
        '/storage/emulated/0/Music',
        '/sdcard/Download',
    ):
        if Path(cand).is_dir():
            return cand
    if IS_ANDROID:
        try:
            from android.storage import primary_external_storage_path
            return primary_external_storage_path()
        except Exception:
            return '/'
    return str(Path.home())


def request_storage_permissions() -> None:
    """申请存储权限。权限被拒不会崩，只是拿不到外部目录。"""
    if not IS_ANDROID:
        return
    try:
        from android.permissions import Permission, request_permissions
        perms = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
        if hasattr(Permission, 'READ_MEDIA_AUDIO'):
            perms.append(Permission.READ_MEDIA_AUDIO)
        request_permissions(perms)
    except Exception:
        pass


def collect_ncm(paths) -> list[str]:
    """把文件和目录展开成 .ncm 列表，去重保序。"""
    seen, out = set(), []
    for raw in paths:
        p = Path(raw)
        items = sorted(p.rglob('*.ncm')) if p.is_dir() else [p]
        for f in items:
            if f.suffix.lower() != '.ncm' or not f.is_file():
                continue
            key = str(f.resolve()) if f.exists() else str(f)
            if key in seen:
                continue
            seen.add(key)
            out.append(str(f))
    return out


def convert_batch(files, out_dir=None, use_title=True, skip=True,
                  on_progress=None, on_file_done=None, should_cancel=None):
    """
    批量转换（纯逻辑，无 UI 依赖）。

    on_progress(index, done_bytes, total_bytes)
    on_file_done(index, state, detail)   state ∈ 完成/已跳过/失败/已取消
    should_cancel() 返回 True 时中断
    返回 (ok, skipped, failed)
    """
    ok = skipped = failed = 0
    for idx, path in enumerate(files):
        if should_cancel and should_cancel():
            if on_file_done:
                on_file_done(idx, '已取消', '')
            continue
        try:
            cb = None
            if on_progress:
                cb = (lambda d, t, i=idx: on_progress(i, d, t))
            out = dump(path, out_dir=out_dir, use_title=use_title, skip=skip, progress=cb)
            if out is None:
                skipped += 1
                if on_file_done:
                    on_file_done(idx, '已跳过', '目标已存在')
            else:
                ok += 1
                if on_file_done:
                    on_file_done(idx, '完成', str(out))
        except Exception as exc:
            if should_cancel and should_cancel():
                if on_file_done:
                    on_file_done(idx, '已取消', '')
                continue
            failed += 1
            detail = str(exc) if isinstance(exc, NCMError) else f'{type(exc).__name__}: {exc}'
            if on_file_done:
                on_file_done(idx, '失败', detail)
    return ok, skipped, failed


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
class NCMApp(App):
    title = 'NCM Studio'

    def build(self):
        Window.clearcolor = BG
        self._cancel = False
        self.files: list[str] = []

        root = BoxLayout(orientation='vertical', padding=dp(14), spacing=dp(10))

        title = Label(text='NCM Studio', font_size='26sp', bold=True, color=TEXT,
                      size_hint_y=None, height=dp(44), halign='left', valign='middle')
        title.bind(size=lambda *_: setattr(title, 'text_size', (title.width, None)))
        root.add_widget(title)

        sub = Label(text='选择 .ncm 文件，转换为原始 MP3 / FLAC', font_size='13sp',
                    color=MUTED, size_hint_y=None, height=dp(22), halign='left')
        sub.bind(size=lambda *_: setattr(sub, 'text_size', (sub.width, None)))
        root.add_widget(sub)

        self.chooser = FileChooserListView(path=start_dir(), filters=['*.ncm'],
                                           multiselect=True, size_hint_y=1)
        self.chooser.bind(selection=self.on_selection)
        root.add_widget(self.chooser)

        self.count_label = Label(text='未选择文件', font_size='13sp', color=MUTED,
                                 size_hint_y=None, height=dp(22))
        root.add_widget(self.count_label)

        root.add_widget(self._option_row('用歌名命名文件', True, 'opt_title'))
        root.add_widget(self._option_row('跳过已存在的文件', True, 'opt_skip'))

        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(10))
        root.add_widget(self.progress)

        self.status = Label(text='就绪', font_size='13sp', color=TEXT, size_hint_y=None,
                            height=dp(24), halign='left')
        self.status.bind(size=lambda *_: setattr(self.status, 'text_size', (self.status.width, None)))
        root.add_widget(self.status)

        self.log_label = Label(text='', font_size='11sp', color=MUTED, size_hint_y=None,
                               halign='left', valign='top')
        self.log_label.bind(width=lambda *_: setattr(self.log_label, 'text_size',
                                                     (self.log_label.width, None)))
        self.log_label.bind(texture_size=lambda *_: setattr(self.log_label, 'height',
                                                            self.log_label.texture_size[1]))
        scroll = ScrollView(size_hint_y=None, height=dp(96))
        scroll.add_widget(self.log_label)
        root.add_widget(scroll)

        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        self.btn_go = Button(text='开始转换', background_color=ACCENT, background_normal='')
        self.btn_go.bind(on_release=self.start)
        self.btn_cancel = Button(text='取消', background_color=(0.25, 0.16, 0.19, 1),
                                 background_normal='', disabled=True)
        self.btn_cancel.bind(on_release=self.cancel)
        btn_out = Button(text='输出目录', background_color=CARD, background_normal='')
        btn_out.bind(on_release=self.show_out_dir)
        row.add_widget(btn_out)
        row.add_widget(self.btn_cancel)
        row.add_widget(self.btn_go)
        root.add_widget(row)

        Clock.schedule_once(lambda *_: request_storage_permissions(), 0.5)
        return root

    def _option_row(self, text, active, attr):
        row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
        cb = CheckBox(active=active, size_hint_x=None, width=dp(34),
                      color=ACCENT)
        setattr(self, attr, cb)
        lb = Label(text=text, font_size='13sp', color=TEXT, halign='left')
        lb.bind(size=lambda *_: setattr(lb, 'text_size', (lb.width, None)))
        row.add_widget(cb)
        row.add_widget(lb)
        return row

    # ---- 选择 ----
    def on_selection(self, _chooser, selection):
        self.files = collect_ncm(selection)
        self.count_label.text = f'已选择 {len(self.files)} 个文件' if self.files else '未选择文件'

    def show_out_dir(self):
        self._log(f'输出目录：{output_root()}')

    # ---- 转换 ----
    def start(self, *_):
        if not self.files:
            self.status.text = '请先在文件列表里选中 .ncm 文件'
            return
        if getattr(self, '_running', False):
            return
        self._running = True
        self._cancel = False
        self.btn_go.disabled = True
        self.btn_cancel.disabled = False
        self.progress.max = len(self.files)
        self.progress.value = 0
        self.log_label.text = ''
        self.status.text = f'准备转换 {len(self.files)} 个文件…'

        out = output_root()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception:
            out = None
        files = list(self.files)
        Thread(target=self._work, args=(files, out), daemon=True).start()

    def _post(self, fn):
        """回调派发：主线程直接跑，子线程才排进 Kivy 时钟。"""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            Clock.schedule_once(lambda dt: fn(), 0)

    def _work(self, files, out):
        ok, skipped, failed = convert_batch(
            files,
            out_dir=out,
            use_title=self.opt_title.active,
            skip=self.opt_skip.active,
            on_progress=lambda i, d, t: self._post(lambda: self._progress(i, d, t)),
            on_file_done=lambda i, s, d: self._post(lambda: self._file_done(i, s, d)),
            should_cancel=lambda: self._cancel,
        )
        self._post(lambda: self._finished(ok, skipped, failed))

    def _progress(self, idx, done, total):
        if total:
            self.status.text = (f'正在转换第 {idx + 1}/{len(self.files)} 个 '
                                f'· {done * 100 // total}%')

    def _file_done(self, idx, state, detail):
        self.progress.value = min(self.progress.value + 1, self.progress.max)
        name = Path(self.files[idx]).name if idx < len(self.files) else ''
        # 用纯 ASCII 标记：不依赖字体是否覆盖 ✓/✗ 这类符号
        mark = {'完成': '+', '已跳过': '·', '失败': '!', '已取消': '-'}.get(state, '·')
        if state == '失败':
            self._log(f'{mark} {name}  {detail}')
        else:
            self._log(f'{mark} {name}  {state}')

    def _finished(self, ok, skipped, failed):
        self._running = False
        self.btn_go.disabled = False
        self.btn_cancel.disabled = True
        summary = f'完成 {ok}'
        if skipped:
            summary += f' · 跳过 {skipped}'
        if failed:
            summary += f' · 失败 {failed}'
        self.status.text = summary
        self._log(f'输出目录：{output_root()}')

    def _log(self, line):
        self.log_label.text = (self.log_label.text + '\n' + line).strip('\n')

    def cancel(self, *_):
        self._cancel = True
        self.btn_cancel.disabled = True
        self.status.text = '正在取消…'


if __name__ == '__main__':
    NCMApp().run()
