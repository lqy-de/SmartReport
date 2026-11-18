from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from app.controllers import ImportWorker
from app.ui.tables import FILE_COLUMNS, FILE_LABELS, RowModel, table_view


SUMMARY_LABELS = (
    ("parsed", "已识别"), ("review", "待复核文件"), ("reference", "参考表"),
    ("duplicate", "重复跳过"), ("damaged", "损坏"), ("unreadable", "无法读取"),
    ("unrecognized", "识别失败"), ("unsupported", "类型跳过"), ("excluded", "已排除"),
)


def plain(label):
    widget = QLabel(label)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


class ImportPage(QWidget):
    imported = Signal()

    def __init__(self, database, service, parent=None):
        super().__init__(parent)
        self.db = database
        self.service = service
        self.worker = None
        self.latest_batch = None
        self.last_location = QDir.homePath()
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(15)
        heading = QHBoxLayout()
        title = QLabel("文件导入")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        self.history = QComboBox()
        self.history.setAccessibleName("导入批次")
        self.history.setMinimumWidth(240)
        self.history.currentIndexChanged.connect(self.show_batch)
        heading.addWidget(self.history)
        layout.addLayout(heading)

        panel = QWidget()
        panel.setObjectName("card")
        card = QVBoxLayout(panel)
        card.setContentsMargins(18, 16, 18, 16)
        card.setSpacing(12)
        hint = QLabel("选择成绩文件夹，或将文件夹和文件拖到此页")
        hint.setObjectName("muted")
        card.addWidget(hint)
        actions = QHBoxLayout()
        self.folder_button = QPushButton("导入文件夹")
        self.folder_button.setObjectName("primary")
        self.folder_button.clicked.connect(self.choose_folder)
        self.file_button = QPushButton("导入文件")
        self.file_button.clicked.connect(self.choose_files)
        self.zip_button = QPushButton("兼容导入 ZIP")
        self.zip_button.clicked.connect(self.choose_zip)
        for button in (self.folder_button, self.file_button, self.zip_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(QLabel("重复文件"))
        self.policy = QComboBox()
        self.policy.setAccessibleName("重复文件处理方式")
        self.policy.addItem("跳过", "skip")
        self.policy.addItem("重新导入", "reimport")
        actions.addWidget(self.policy)
        card.addLayout(actions)
        self.progress_text = plain("就绪")
        self.progress_text.setWordWrap(True)
        card.addWidget(self.progress_text)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFixedHeight(8)
        card.addWidget(self.bar)
        layout.addWidget(panel)

        summary = QGridLayout()
        self.metrics = {}
        for index, (key, label) in enumerate(SUMMARY_LABELS):
            tile = QWidget()
            tile.setObjectName("card")
            box = QVBoxLayout(tile)
            box.setContentsMargins(10, 7, 10, 7)
            caption = QLabel(label)
            caption.setObjectName("muted")
            box.addWidget(caption)
            value = QLabel("0")
            value.setObjectName("stat")
            box.addWidget(value)
            summary.addWidget(tile, 0, index)
            self.metrics[key] = value
        layout.addLayout(summary)
        self.model = RowModel(FILE_COLUMNS, lambda row, col: row[col], self)
        self.table = table_view(self.model, (138, 260, 130, 365, 175))
        self.table.viewport().setAcceptDrops(False)
        layout.addWidget(self.table, 1)
        self.fill_history()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择成绩文件夹", self.last_location)
        if folder:
            self.last_location = folder
            self.start([folder])

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择成绩文件或参考表", self.last_location, "成绩文件 (*.pdf *.xls *.xlsx)",
        )
        if paths:
            self.last_location = str(Path(paths[0]).parent)
            self.start(paths)

    def choose_zip(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 ZIP 文件", self.last_location, "ZIP 压缩包 (*.zip)",
        )
        if paths:
            self.last_location = str(Path(paths[0]).parent)
            self.start(paths)

    def dragEnterEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if self.worker is None and paths:
            event.acceptProposedAction()
            self.start(paths)

    @property
    def busy(self):
        return self.worker is not None

    def start(self, paths):
        if self.busy:
            return
        self.latest_batch = None
        self.model.replace([])
        for value in self.metrics.values():
            value.setText("0")
        self.toggle_actions(False)
        self.show_progress("扫描", 0, 0, "正在扫描…")
        worker = ImportWorker(self.service, paths, self.policy.currentData(), self)
        self.worker = worker
        worker.progress.connect(self.show_progress)
        worker.file_result.connect(self.show_result)
        worker.completed.connect(self.completed)
        worker.failed.connect(self.failed)
        worker.finished.connect(self.release_worker)
        worker.start()

    def toggle_actions(self, enabled):
        for widget in (self.folder_button, self.file_button, self.zip_button, self.history, self.policy):
            widget.setEnabled(enabled)

    @Slot(str, int, int, str)
    def show_progress(self, stage, done, total, description):
        self.bar.setRange(0, total or (0 if stage == "扫描" else 1))
        self.bar.setValue(done)
        status = f"{stage} {done}/{total}" if total else stage
        self.progress_text.setText(f"{status}　{description}")

    @Slot(object, object)
    def show_result(self, source, outcome):
        if outcome.status in self.metrics:
            value = self.metrics[outcome.status]
            value.setText(str(int(value.text()) + 1))
        self.model.append((FILE_LABELS[outcome.status], source.relative, source.parent, outcome.message, ""))

    @Slot(int, object)
    def completed(self, batch, counts):
        self.latest_batch = batch

    @Slot(str)
    def failed(self, message):
        QMessageBox.warning(self, "导入异常", message)

    @Slot()
    def release_worker(self):
        self.worker.deleteLater()
        self.worker = None
        self.toggle_actions(True)
        self.fill_history(self.latest_batch)
        self.imported.emit()

    def fill_history(self, selected=None):
        self.history.blockSignals(True)
        self.history.clear()
        for row in self.db.batches():
            title = f"批次 #{row['id']} · {row['started_at'][:16].replace('T', ' ')}"
            self.history.addItem(title, row["id"])
        if not self.history.count():
            self.history.addItem("暂无导入批次")
        self.history.setCurrentIndex(max(0, self.history.findData(selected)))
        self.history.blockSignals(False)
        self.show_batch()

    def show_batch(self, *_):
        import json

        batch = self.history.currentData()
        if batch is None:
            return
        row = next(row for row in self.db.batches() if row["id"] == batch)
        counts = json.loads(row["counts"])
        for key, value in self.metrics.items():
            value.setText(str(counts.get(key, 0)))
        records, pending = counts.get("records", 0), counts.get("review_records", 0)
        state = {"finished": "导入完成", "failed": "导入中断", "running": "批次未完成"}
        status = state[row["status"]]
        self.progress_text.setText(f"{status}　批次 #{batch} · {records} 条成绩 · {pending} 条待复核")
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.model.replace(
            (FILE_LABELS[f["status"]], f["relative_path"], f["parent_name"], f["message"], f["imported_at"])
            for f in self.db.files(batch)
        )

