from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QTableView

from app.exporters import REVIEW_LABELS


GRADE_COLUMNS = {
    "name": "姓名", "masked_number": "准考证号", "unit": "单位", "trade": "工种",
    "exam_date": "考试日期", "subject": "科目", "score": "得分", "maximum": "配分",
    "rate": "得分率", "status": "核验状态", "folder": "相对文件夹",
    "batch_id": "批次", "relative_path": "来源文件",
}
FILE_LABELS = {
    "parsed": "已识别", "review": "待复核", "reference": "参考表",
    "duplicate": "重复 · 已跳过", "damaged": "文件损坏", "unreadable": "无法读取",
    "unsupported": "类型不支持 · 已跳过", "excluded": "已排除",
    "unrecognized": "识别失败", "archive": "ZIP 已扫描",
}
FILE_COLUMNS = ("状态", "相对路径", "父文件夹", "处理结果", "导入时间")


def display(value):
    return "" if value is None else str(value)


class RowModel(QAbstractTableModel):
    def __init__(self, columns, render, parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.render = render
        self.rows = []
        self.sorting = (-1, Qt.SortOrder.AscendingOrder)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.render(self.rows[index.row()], index.column())

    def replace(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self._sort_rows()
        self.endResetModel()

    def append(self, row):
        position = len(self.rows)
        self.beginInsertRows(QModelIndex(), position, position)
        self.rows.append(row)
        self.endInsertRows()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if column < 0:
            return
        self.sorting = (column, order)
        self.beginResetModel()
        self._sort_rows()
        self.endResetModel()

    def _sort_rows(self):
        column, order = self.sorting
        if column < 0:
            return
        self.rows.sort(key=lambda row: self.sort_key(row, column),
                       reverse=order == Qt.SortOrder.DescendingOrder)

    def sort_key(self, row, column):
        return self.render(row, column)


class GradeModel(RowModel):
    def __init__(self, parent=None):
        self.fields = tuple(GRADE_COLUMNS)
        super().__init__(GRADE_COLUMNS.values(), self.grade_text, parent)

    def grade_text(self, row, column):
        field = self.fields[column]
        value = row[field]
        if field == "status":
            return REVIEW_LABELS[value]
        if field == "rate" and value is not None:
            return format(value, ".2%")
        return display(value)

    def sort_key(self, row, column):
        value = row[self.fields[column]]
        return (value is not None, value)


def table_view(model, widths=(), sortable=False):
    view = QTableView()
    view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setSortingEnabled(sortable)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(32)
    view.horizontalHeader().setStretchLastSection(True)
    for index, width in enumerate(widths):
        view.setColumnWidth(index, width)
    return view

