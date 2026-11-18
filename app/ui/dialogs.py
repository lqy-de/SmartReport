from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.exporters import FIELDS, REVIEW_LABELS, TEMPLATES
from app.ui.tables import RowModel, display, table_view
from app.validators import number


class ExamDialog(QDialog):
    def __init__(self, database, exam, parent=None):
        super().__init__(parent)
        self.db, self.exam = database, exam
        self.setWindowTitle("成绩详情")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        title = QLabel(f"{exam['name']} · {exam['subject']}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("title")
        layout.addWidget(title)
        items, issues, references, changes = database.detail(exam)
        summary = QLabel(
            f"{exam['masked_number']}　{exam['unit']}　{exam['trade']}　{exam['exam_date']}\n"
            f"得分 {display(exam['score'])} / {display(exam['maximum'])}　"
            f"{REVIEW_LABELS[exam['status']]}　来源批次 #{exam['batch_id']}\n"
            f"{exam['relative_path']} · 第 {exam['page_start']}–{exam['page_end']} 页\n"
            f"导入时间 {exam['imported_at']}"
        )
        self._add_text(layout, summary)
        if issues:
            self._add_text(layout, QLabel("核验提示　" + "；".join(x[0] for x in issues)))
        if references:
            self._add_text(layout, QLabel("同目录参考表　" + "；".join(x[0] for x in references)))
        keys = ("project", "content", "maximum", "score", "deduction", "note", "page")
        model = RowModel(
            ("项目", "步骤", "配分", "得分", "原表扣分", "备注", "页码"),
            lambda row, col: display(row[keys[col]]), self,
        )
        model.replace(items)
        layout.addWidget(table_view(model, (135, 315, 56, 56, 74, 115, 52)), 1)
        if changes:
            latest = changes[0]
            self._add_text(layout, QLabel(f"最近核准　{latest['changed_at']}　{latest['reason']}"))
            history = QPushButton("查看修改记录")
            history.clicked.connect(lambda: self.show_history(changes))
            layout.addWidget(history)
        form = QFormLayout()
        self.score = QLineEdit(display(exam["score"]))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("例如已逐项核对原始评分表")
        form.addRow("核准得分", self.score)
        form.addRow("核准原因", self.reason)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        view = buttons.addButton(
            "打开来源 ZIP" if exam["archive_member"] else "打开来源 PDF",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        confirm = buttons.addButton("核准成绩", QDialogButtonBox.ButtonRole.AcceptRole)
        view.clicked.connect(self.open_source)
        confirm.clicked.connect(self.confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_text(self, layout, label):
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)

    def show_history(self, changes):
        field_labels = {"score": "得分", "status": "状态"}
        lines = [
            f"{r['changed_at']} · {field_labels[r['field']]}\n"
            f"{REVIEW_LABELS.get(r['before_value'], r['before_value'])} → "
            f"{REVIEW_LABELS.get(r['after_value'], r['after_value'])}\n{r['reason']}"
            for r in changes
        ]
        message = QMessageBox(self)
        message.setWindowTitle("修改记录")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText("\n\n".join(lines))
        message.exec()

    def open_source(self):
        url = QUrl.fromLocalFile(self.exam["local_path"])
        if not self.exam["archive_member"]:
            url.setFragment(f"page={self.exam['page_start']}")
        if not Path(self.exam["local_path"]).is_file() or not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "无法打开来源", "请检查原文件是否已移动或删除。")

    def confirm(self):
        try:
            score = number(self.score.text())
            if score is None:
                raise ValueError("请输入原始或更正后的数字得分")
            self.db.confirm(self.exam["id"], score, self.reason.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法核准", str(exc))
        else:
            self.accept()


class ExportDialog(QDialog):
    def __init__(self, current, all_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出成绩")
        self.resize(590, 470)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.template = QComboBox()
        for key, label in TEMPLATES.items():
            self.template.addItem(label, key)
        self.scope = QComboBox()
        self.scope.addItem(f"当前筛选 · {current} 条", "current")
        self.scope.addItem(f"全部记录 · {all_count} 条", "all")
        self.stage = QComboBox()
        self.stage.addItem("核对稿 · 保留核验状态", "draft")
        self.stage.addItem("正式报表 · 仅已核准", "official")
        self.format = QComboBox()
        self.format.addItems(["XLSX", "CSV", "TXT"])
        for name, widget in (("模板", self.template), ("范围", self.scope),
                             ("用途", self.stage), ("格式", self.format)):
            form.addRow(name, widget)
        layout.addLayout(form)
        layout.addWidget(QLabel("导出字段"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        self.grid = QGridLayout(panel)
        scroll.setWidget(panel)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.check_fields)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.template.currentIndexChanged.connect(self.reset_fields)
        self.stage.currentIndexChanged.connect(self.reset_fields)
        self.reset_fields()

    def reset_fields(self):
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.checkboxes = {}
        for index, (key, label) in enumerate(FIELDS[self.template.currentData()].items()):
            check = QCheckBox(label)
            check.setChecked(True)
            check.setEnabled(key != "status" or self.stage.currentData() == "official")
            self.checkboxes[key] = check
            self.grid.addWidget(check, index // 3, index % 3)

    def fields(self):
        return [key for key, check in self.checkboxes.items() if check.isChecked()]

    def check_fields(self):
        if not self.fields():
            QMessageBox.warning(self, "缺少字段", "请至少选择一个导出字段。")
        else:
            self.accept()

    def target(self, directory):
        template = self.template.currentData()
        extension = self.format.currentText().lower()
        stage = "核对稿" if self.stage.currentData() == "draft" else "已核准"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suggested = directory / f"{TEMPLATES[template]}-{stage}-{timestamp}.{extension}"
        path, _ = QFileDialog.getSaveFileName(
            self, "选择导出位置", str(suggested), f"{extension.upper()} 文件 (*.{extension})",
        )
        if not path:
            return None
        target = Path(path)
        if target.suffix and target.suffix.lower() != "." + extension:
            QMessageBox.warning(self.parentWidget(), "扩展名不匹配", f"请选择 .{extension} 文件名。")
            return None
        if not target.suffix:
            target = target.with_suffix("." + extension)
            if target.exists() and QMessageBox.question(
                self.parentWidget(), "替换导出文件", "该文件已存在。要替换吗？",
            ) != QMessageBox.StandardButton.Yes:
                return None
        return target

