from pathlib import Path, PurePosixPath

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.exporters import ExportService, REVIEW_LABELS
from app.ui.dialogs import ExamDialog, ExportDialog
from app.ui.tables import GradeModel, table_view


ROLE = Qt.ItemDataRole.UserRole


class GradesPage(QWidget):
    def __init__(self, database, output, parent=None):
        super().__init__(parent)
        self.db = database
        self.output = output
        self.data = []
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(140)
        self.delay.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(15)
        heading = QHBoxLayout()
        title = QLabel("成绩管理")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        export = QPushButton("导出成绩")
        export.setObjectName("primary")
        export.clicked.connect(self.export)
        heading.addWidget(export)
        layout.addLayout(heading)
        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索姓名、单位或相对路径")
        self.search.textChanged.connect(lambda: self.delay.start())
        filter_row.addWidget(self.search, 2)
        self.filters = {}
        for field, label in (
            ("batch_id", "全部批次"), ("exam_date", "全部日期"), ("unit", "全部单位"),
            ("trade", "全部工种"), ("subject", "全部科目"), ("status", "全部状态"),
        ):
            widget = QComboBox()
            widget.setAccessibleName(label)
            widget.addItem(label)
            widget.currentIndexChanged.connect(self.apply_filters)
            self.filters[field] = (widget, label)
            filter_row.addWidget(widget, 1)
        layout.addLayout(filter_row)
        switches = QHBoxLayout()
        self.grouping = QCheckBox("按文件夹分组")
        self.grouping.setChecked(True)
        self.grouping.toggled.connect(self.toggle_tree)
        switches.addWidget(self.grouping)
        switches.addStretch()
        self.count = QLabel()
        self.count.setObjectName("muted")
        switches.addWidget(self.count)
        layout.addLayout(switches)
        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("来源文件夹")
        self.tree.setMinimumWidth(175)
        self.tree.currentItemChanged.connect(self.apply_filters)
        splitter.addWidget(self.tree)
        self.model = GradeModel(self)
        self.table = table_view(self.model, (76, 120, 122, 105, 108, 90, 65, 65, 70, 82, 152, 58, 255), True)
        self.table.doubleClicked.connect(self.open_exam)
        splitter.addWidget(self.table)
        splitter.setSizes([230, 740])
        layout.addWidget(splitter, 1)

    def reload(self):
        self.data = self.db.grades()
        for field, (widget, label) in self.filters.items():
            current = widget.currentData()
            widget.blockSignals(True)
            widget.clear()
            widget.addItem(label, None)
            for value in sorted({row[field] for row in self.data if row[field] != ""}):
                text = REVIEW_LABELS.get(value, f"批次 #{value}" if field == "batch_id" else str(value))
                widget.addItem(text, value)
            widget.setCurrentIndex(max(widget.findData(current), 0))
            widget.blockSignals(False)
        self.rebuild_tree()
        self.apply_filters()

    def rebuild_tree(self):
        selection = self.tree.currentItem()
        previous = selection.data(0, ROLE) if selection else None
        counts = {}
        for row in self.data:
            root, folder = row["root"], PurePosixPath(row["folder"])
            for branch in dict.fromkeys((folder, *folder.parents)):
                key = (root, branch.as_posix())
                counts[key] = counts.get(key, 0) + 1
        self.tree.blockSignals(True)
        self.tree.clear()
        all_node = QTreeWidgetItem(self.tree, [f"全部文件夹 ({len(self.data)})"])
        nodes = {}
        for key, count in sorted(counts.items()):
            root, folder = key
            path = PurePosixPath(folder)
            parent = all_node if folder == "." else nodes[(root, path.parent.as_posix())]
            title = (Path(root).name or root) if folder == "." else path.name
            node = QTreeWidgetItem(parent, [f"{title} ({count})"])
            node.setData(0, ROLE, key)
            node.setToolTip(0, f"{root}\n{folder}")
            nodes[key] = node
        self.tree.expandToDepth(1)
        self.tree.setCurrentItem(nodes.get(tuple(previous), all_node) if previous else all_node)
        self.tree.blockSignals(False)

    def toggle_tree(self, visible):
        self.tree.setVisible(visible)
        self.apply_filters()

    def apply_filters(self, *_):
        criteria = {name: combo.currentData() for name, (combo, _) in self.filters.items()}
        selected = self.tree.currentItem()
        group = selected.data(0, ROLE) if selected is not None and self.grouping.isChecked() else None
        terms = self.search.text().casefold().split()
        rows = []
        for row in self.data:
            if any(value is not None and row[key] != value for key, value in criteria.items()):
                continue
            if group and (row["root"] != group[0] or not PurePosixPath(row["folder"]).is_relative_to(group[1])):
                continue
            haystack = " ".join(str(row[k]) for k in (
                "name", "masked_number", "unit", "trade", "exam_date", "subject", "relative_path", "parent_name"
            )).casefold()
            if all(term in haystack for term in terms):
                rows.append(row)
        self.model.replace(rows)
        self.count.setText(f"显示 {len(rows)} 条 · 共 {len(self.data)} 条")

    def open_exam(self, index):
        exam = self.model.rows[index.row()]
        if ExamDialog(self.db, exam, self).exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def export(self):
        if not self.data:
            QMessageBox.information(self, "暂无成绩", "请先导入包含成绩的文件夹。")
            return
        options = ExportDialog(len(self.model.rows), len(self.data), self)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        rows = list(self.model.rows if options.scope.currentData() == "current" else self.data)
        if options.stage.currentData() == "official":
            rows = [row for row in rows if row["status"] == "approved"]
        if not rows:
            QMessageBox.information(self, "暂无符合条件的成绩", "可调整筛选，或在成绩详情中核准成绩。")
            return
        target = options.target(self.output)
        if target is None:
            return
        try:
            count = ExportService(self.db).export(target, rows, options.template.currentData(), options.fields())
        except ValueError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        except Exception:
            QMessageBox.warning(self, "导出失败", "请检查目标文件是否被占用、目录权限和可用空间。")
            return
        message = QMessageBox(self)
        message.setWindowTitle("导出成功")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText(f"已写入 {count} 行\n{target.name}")
        view = message.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
        message.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
        message.exec()
        if message.clickedButton() is view:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

