# -*- coding: utf-8 -*-
"""
NCM Studio · 桌面端

相对 v1 的改动（都是能直接感觉到的）：
  * 拖放真正可用：v1 用 self.list.dropEvent = self.drop 给实例挂属性，
    Qt 的事件分发走类型上的虚函数，实例属性根本不会被调用
  * 进度条真的在动：v1 只有「全部结束」时才 setValue，长任务看着像卡死
  * 可以中途取消：取消时清掉半成品 .part 文件
  * 可选输出目录、可选「用歌名命名」、可选「跳过已存在」
  * 逐文件状态与错误日志，不再是一个弹窗糊一堆报错
  * 转换在线程里跑，UI 不冻结

跑法：python desktop/app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ncmdump import NCMError, dump, read_info

APP_TITLE = 'NCM Studio'
APP_SUB = '网易云音乐 NCM 转换器 · Python 3.12+ 重构版'

QSS = """
QWidget { background:#0e1117; color:#e6edf7; font-family:'Segoe UI','Microsoft YaHei UI'; font-size:13px; }
QLabel#title { font-size:26px; font-weight:700; color:#ffffff; }
QLabel#sub { color:#7d8798; }
QLabel#hint { color:#7d8798; font-size:12px; }
QFrame#card { background:#151a23; border:1px solid #232b3a; border-radius:12px; }
QTreeWidget { background:transparent; border:0; outline:0; }
QTreeWidget::item { padding:6px 4px; border-radius:6px; }
QTreeWidget::item:selected { background:#1d2634; color:#ffffff; }
QHeaderView::section { background:#151a23; color:#8f9bad; border:0; padding:8px 6px; font-weight:600; }
QPushButton { background:#2f80ed; border:0; border-radius:9px; padding:10px 18px; font-weight:600; color:#ffffff; }
QPushButton:hover { background:#4f97f5; }
QPushButton:disabled { background:#242c3a; color:#5c6577; }
QPushButton#ghost { background:#1b2230; color:#c3cddc; }
QPushButton#ghost:hover { background:#25303f; }
QPushButton#danger { background:#2a1f24; color:#ff8d8d; }
QPushButton#danger:hover { background:#3a2730; }
QProgressBar { border:0; background:#1b2230; height:8px; border-radius:4px; text-align:center; color:transparent; }
QProgressBar::chunk { background:#2f80ed; border-radius:4px; }
QLineEdit { background:#151a23; border:1px solid #232b3a; border-radius:9px; padding:8px 10px; color:#c3cddc; }
QCheckBox { color:#b6c1d1; spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid #38445a; background:#151a23; }
QCheckBox::indicator:checked { background:#2f80ed; border-color:#2f80ed; }
"""


class DropTree(QTreeWidget):
    """支持把文件/文件夹直接拖进来。"""

    dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(False)
        self.setHeaderLabels(['文件', '歌曲', '歌手', '状态'])
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setHighlightSections(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class ConvertWorker(QThread):
    """在线程里跑转换，逐文件、逐字节汇报进度。"""

    fileStarted = pyqtSignal(int, str)          # index, 显示名
    fileProgress = pyqtSignal(int, int, int)    # index, done, total
    fileDone = pyqtSignal(int, str, str)        # index, 状态, 说明
    allDone = pyqtSignal(int, int, int, list)   # ok, skipped, failed, errors

    def __init__(self, files, out_dir, use_title, skip_existing):
        super().__init__()
        self.files = list(files)
        self.out_dir = out_dir
        self.use_title = use_title
        self.skip_existing = skip_existing
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok = skipped = failed = 0
        errors = []
        for idx, path in enumerate(self.files):
            if self._cancel:
                self.fileDone.emit(idx, '已取消', '')
                continue
            self.fileStarted.emit(idx, Path(path).name)
            try:
                out = dump(
                    path,
                    out_dir=self.out_dir,
                    use_title=self.use_title,
                    skip=self.skip_existing,
                    progress=lambda done, total, i=idx: self.fileProgress.emit(i, done, total),
                )
                if out is None:
                    skipped += 1
                    self.fileDone.emit(idx, '已跳过', '目标文件已存在')
                else:
                    ok += 1
                    self.fileDone.emit(idx, '完成', '')
            except Exception as exc:                     # 单首失败不中断整批
                if self._cancel:
                    self.fileDone.emit(idx, '已取消', '')
                    continue
                failed += 1
                msg = str(exc) if isinstance(exc, NCMError) else f'{type(exc).__name__}: {exc}'
                errors.append(f'{Path(path).name} — {msg}')
                self.fileDone.emit(idx, '失败', msg)
        self.allDone.emit(ok, skipped, failed, errors)


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[str] = []
        self.rows: dict[int, QTreeWidgetItem] = {}
        self.worker: ConvertWorker | None = None
        self.out_dir: str = ''
        self.use_dialogs = True                     # 无头测试时关掉，避免模态框卡死

        self.setWindowTitle(APP_TITLE)
        self.resize(960, 660)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(14)

        title = QLabel(APP_TITLE)
        title.setObjectName('title')
        root.addWidget(title)
        sub = QLabel(APP_SUB)
        sub.setObjectName('sub')
        root.addWidget(sub)

        card = QFrame()
        card.setObjectName('card')
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(8, 8, 8, 8)

        self.tree = DropTree()
        self.tree.dropped.connect(self.add_paths)
        card_lay.addWidget(self.tree, 1)

        self.hint = QLabel('把 .ncm 文件或整个文件夹拖到这里，或点下面「添加文件」')
        self.hint.setObjectName('hint')
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(self.hint)
        root.addWidget(card, 1)

        # 输出目录
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText('输出目录（留空 = 与源文件同目录）')
        self.out_edit.setReadOnly(True)
        out_row.addWidget(self.out_edit, 1)
        pick_out = QPushButton('选择目录')
        pick_out.setObjectName('ghost')
        pick_out.clicked.connect(self.pick_out_dir)
        out_row.addWidget(pick_out)
        clear_out = QPushButton('用源目录')
        clear_out.setObjectName('ghost')
        clear_out.clicked.connect(self.clear_out_dir)
        out_row.addWidget(clear_out)
        root.addLayout(out_row)

        # 选项
        opt_row = QHBoxLayout()
        opt_row.setSpacing(22)
        self.opt_title = QCheckBox('用歌名命名文件')
        self.opt_title.setChecked(True)
        self.opt_skip = QCheckBox('跳过已存在的文件')
        self.opt_skip.setChecked(True)
        opt_row.addWidget(self.opt_title)
        opt_row.addWidget(self.opt_skip)
        opt_row.addStretch(1)
        root.addLayout(opt_row)

        # 总进度 + 单文件进度
        self.bar_all = QProgressBar()
        self.bar_all.setRange(0, 1)
        self.bar_all.setValue(0)
        self.bar_one = QProgressBar()
        self.bar_one.setRange(0, 1)
        self.bar_one.setValue(0)
        for name, bar in (('总进度', self.bar_all), ('当前文件', self.bar_one)):
            row = QHBoxLayout()
            row.setSpacing(10)
            tag = QLabel(name)
            tag.setObjectName('hint')
            tag.setFixedWidth(56)
            row.addWidget(tag)
            row.addWidget(bar, 1)
            root.addLayout(row)

        self.status = QLabel('就绪')
        self.status.setObjectName('sub')
        root.addWidget(self.status)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_add = QPushButton('添加文件')
        self.btn_add.clicked.connect(self.pick_files)
        self.btn_dir = QPushButton('添加文件夹')
        self.btn_dir.setObjectName('ghost')
        self.btn_dir.clicked.connect(self.pick_folder)
        self.btn_clear = QPushButton('清空列表')
        self.btn_clear.setObjectName('ghost')
        self.btn_clear.clicked.connect(self.clear_list)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_dir)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        self.btn_open = QPushButton('打开输出目录')
        self.btn_open.setObjectName('ghost')
        self.btn_open.clicked.connect(self.open_out_dir)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.setObjectName('danger')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_go = QPushButton('开始转换')
        self.btn_go.clicked.connect(self.start)
        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_go)
        root.addLayout(btn_row)

    # ---- 列表维护 ----
    def add_paths(self, paths):
        added = 0
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                for f in sorted(p.rglob('*.ncm')):
                    added += self._add_one(f)
            elif p.suffix.lower() == '.ncm':
                added += self._add_one(p)
        self._refresh_hint()
        if added:
            self.status.setText(f'已添加 {added} 个文件，共 {len(self.files)} 个')

    def _add_one(self, p: Path) -> int:
        key = str(p.resolve())
        if key in self.files:
            return 0
        idx = len(self.files)
        self.files.append(key)
        item = QTreeWidgetItem([p.name, '', '', '待转换'])
        try:
            info = read_info(p)
            item.setText(1, info.music_name or '—')
            item.setText(2, info.artist_text or '—')
        except Exception as exc:
            item.setText(1, '—')
            item.setText(2, '—')
            item.setText(3, '无法解析')
            item.setForeground(3, QColor('#ff8d8d'))
            item.setToolTip(3, str(exc))
        self.tree.addTopLevelItem(item)
        self.rows[idx] = item
        return 1

    def _refresh_hint(self):
        self.hint.setVisible(not self.files)
        empty = not self.files
        self.btn_open.setEnabled(not empty or bool(self.out_dir))

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选择 NCM 文件', '', 'NCM 文件 (*.ncm)')
        if files:
            self.add_paths(files)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, '选择包含 NCM 的文件夹')
        if d:
            self.add_paths([d])

    def clear_list(self):
        if self.worker and self.worker.isRunning():
            return
        self.files.clear()
        self.rows.clear()
        self.tree.clear()
        self.bar_all.setRange(0, 1)
        self.bar_all.setValue(0)
        self.bar_one.setRange(0, 1)
        self.bar_one.setValue(0)
        self.status.setText('就绪')
        self._refresh_hint()

    def pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, '选择输出目录')
        if d:
            self.out_dir = d
            self.out_edit.setText(d)
            self.btn_open.setEnabled(True)

    def clear_out_dir(self):
        self.out_dir = ''
        self.out_edit.clear()

    def open_out_dir(self):
        target = self.out_dir or (Path(self.files[0]).parent if self.files else '')
        if target and Path(target).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        else:
            QMessageBox.information(self, '提示', '还没有可打开的输出目录')

    # ---- 转换 ----
    def start(self):
        if not self.files:
            QMessageBox.information(self, '提示', '请先添加 NCM 文件')
            return
        if self.worker and self.worker.isRunning():
            return

        for idx, item in self.rows.items():
            item.setText(3, '排队中')
            item.setForeground(3, QColor('#8f9bad'))
        self.bar_all.setRange(0, len(self.files))
        self.bar_all.setValue(0)
        self.bar_one.setRange(0, 1000)
        self.bar_one.setValue(0)
        self._set_running(True)
        self.status.setText('转换中…')

        self.worker = ConvertWorker(
            self.files, self.out_dir or None,
            self.opt_title.isChecked(), self.opt_skip.isChecked(),
        )
        self.worker.fileStarted.connect(self.on_started)
        self.worker.fileProgress.connect(self.on_progress)
        self.worker.fileDone.connect(self.on_done)
        self.worker.allDone.connect(self.on_all_done)
        self.worker.start()

    def _set_running(self, running: bool):
        self.btn_go.setEnabled(not running)
        self.btn_add.setEnabled(not running)
        self.btn_dir.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
        self.btn_cancel.setEnabled(running)

    def on_started(self, idx, name):
        item = self.rows.get(idx)
        if item:
            item.setText(3, '转换中')
            item.setForeground(3, QColor('#4f97f5'))
            self.tree.scrollToItem(item)
        self.status.setText(f'正在转换：{name}')

    def on_progress(self, idx, done, total):
        self.bar_one.setValue(int(done * 1000 / total) if total else 0)

    def on_done(self, idx, state, detail):
        item = self.rows.get(idx)
        color = {'完成': '#3ddc84', '已跳过': '#c9a227',
                 '失败': '#ff8d8d', '已取消': '#8f9bad'}.get(state, '#8f9bad')
        if item:
            item.setText(3, state)
            item.setForeground(3, QColor(color))
            if detail:
                item.setToolTip(3, detail)
        self.bar_all.setValue(self.bar_all.value() + 1)

    def on_all_done(self, ok, skipped, failed, errors):
        self._set_running(False)
        self.bar_one.setValue(self.bar_one.maximum())
        summary = f'完成 {ok}'
        if skipped:
            summary += f' · 跳过 {skipped}'
        if failed:
            summary += f' · 失败 {failed}'
        self.status.setText(summary)
        if errors:
            self.last_errors = errors
            if self.use_dialogs:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle('部分文件未能转换')
                box.setText(f'{failed} 个文件失败：')
                box.setDetailedText('\n'.join(errors))
                box.exec()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.status.setText('正在取消…')

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


def _cli(argv: list[str]) -> int:
    """
    无界面批量模式，也用于打包后的冒烟验证。

        NCM_Studio.exe --cli a.ncm b.ncm -o D:\\out
        NCM_Studio.exe --cli D:\\music -o D:\\out --overwrite
    """
    import argparse

    ap = argparse.ArgumentParser(prog='ncm-studio', description='NCM 批量转换（无界面）')
    ap.add_argument('inputs', nargs='+', help='.ncm 文件或包含 .ncm 的目录')
    ap.add_argument('-o', '--out', default=None, help='输出目录')
    ap.add_argument('--overwrite', action='store_true', help='覆盖已存在的文件')
    ap.add_argument('--source-name', action='store_true', help='用源文件名而不是歌名命名')
    ap.add_argument('--no-tag', action='store_true', help='不写标签与封面')
    ap.add_argument('-q', '--quiet', action='store_true', help='只输出汇总')
    args = ap.parse_args(argv)

    files: list[str] = []
    for raw in args.inputs:
        p = Path(raw)
        if p.is_dir():
            files += [str(f) for f in sorted(p.rglob('*.ncm'))]
        elif p.suffix.lower() == '.ncm':
            files.append(str(p))

    if not files:
        print('没有找到任何 .ncm 文件', file=sys.stderr)
        return 2

    ok = skipped = failed = 0
    for path in files:
        try:
            out = dump(path, out_dir=args.out, use_title=not args.source_name,
                       skip=not args.overwrite, tag=not args.no_tag)
            if out is None:
                skipped += 1
                if not args.quiet:
                    print(f'跳过  {Path(path).name}')
            else:
                ok += 1
                if not args.quiet:
                    print(f'完成  {out}')
        except Exception as exc:
            failed += 1
            print(f'失败  {Path(path).name} — {exc}', file=sys.stderr)

    print(f'合计 {len(files)} 个：完成 {ok} · 跳过 {skipped} · 失败 {failed}')
    return 0 if failed == 0 else 1


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setFont(QFont('Segoe UI', 10))
    win = Window()
    win.show()
    return app.exec()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--cli', '-c'):
        # 打包成窗口程序后没有控制台，CLI 模式需要挂到父进程的控制台上
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                # 双击启动 / 无父控制台时没有标准输出，挂到父控制台上
                if sys.stdout is None or sys.stderr is None:
                    k32.AttachConsole(-1)
                    k32.SetConsoleOutputCP(65001)
                    sys.stdout = open('CONOUT$', 'w', encoding='utf-8',
                                      errors='replace', buffering=1)
                    sys.stderr = open('CONOUT$', 'w', encoding='utf-8',
                                      errors='replace', buffering=1)
                for stream in (sys.stdout, sys.stderr):
                    if stream is not None and hasattr(stream, 'reconfigure'):
                        # 管道默认走本地代码页（GBK），中文会变成乱码
                        stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        raise SystemExit(_cli(sys.argv[2:]))
    raise SystemExit(main())
