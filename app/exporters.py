import csv
import os
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


SUMMARY_FIELDS = {
    "name": "姓名", "masked_number": "准考证号（脱敏）", "unit": "单位", "trade": "工种",
    "job_title": "职名", "exam_date": "考试日期", "exam_time": "考核时间", "subject": "科目",
    "question": "试题名称", "score": "得分", "maximum": "配分", "rate": "得分率",
    "status": "核验状态", "batch_id": "来源批次", "root": "导入根路径",
    "folder": "相对文件夹", "parent_name": "父文件夹", "relative_path": "相对文件路径",
    "page_start": "起始页", "page_end": "结束页", "imported_at": "导入时间",
}
ITEM_FIELDS = {
    **SUMMARY_FIELDS, "score": "考试得分", "maximum": "考试配分", "rate": "考试得分率",
    "project": "考核项目", "content": "考核步骤", "item_maximum": "小分配分",
    "item_score": "小分得分", "deduction": "原表扣分", "note": "备注", "page": "明细页码",
}
TEMPLATES = {"scores": "考生成绩总表", "items": "考核小分明细表"}
FIELDS = {"scores": SUMMARY_FIELDS, "items": ITEM_FIELDS}
REVIEW_LABELS = {"recognized": "已识别", "review": "待复核", "approved": "已核准"}


def cell_value(row, field, *, spreadsheet):
    value = row[field]
    if field == "status":
        return REVIEW_LABELS[value]
    if field == "rate" and value is not None and not spreadsheet:
        return format(value, ".2%")
    if isinstance(value, str) and not spreadsheet:
        start = value.lstrip()
        if value.startswith(("\t", "\r", "\n")) or start.startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
            return "'" + value
    return value


class ExportService:
    def __init__(self, database):
        self.db = database

    def export(self, target: Path, rows: list[dict], template: str, fields: list[str]) -> int:
        suffix = target.suffix.lower()
        if suffix not in {".xlsx", ".csv", ".txt"}:
            raise ValueError("请选择 XLSX、CSV 或 TXT 文件")
        labels = FIELDS[template]
        if not fields or any(field not in labels for field in fields):
            raise ValueError("请选择至少一个有效的导出字段")
        with self.db.connect() as conn:
            source = conn.execute(
                "SELECT 1 FROM source_files WHERE local_path=? LIMIT 1", (str(target.resolve()),)
            ).fetchone()
        if source:
            raise ValueError("所选路径是已导入的源文件，请使用其他文件名")
        spreadsheet = suffix == ".xlsx"
        headers = [labels[field] for field in fields]
        if template == "items":
            rows = [
                {**exam, **{k: item[k] for k in ("project", "content", "deduction", "note", "page")},
                 "item_score": item["score"], "item_maximum": item["maximum"]}
                for exam in rows for item in self.db.score_items(exam["id"])
            ]
            for row in rows:
                for field in ("item_score", "item_maximum", "deduction"):
                    if row[field] is not None:
                        row[field] = Decimal(row[field])
        values = ([cell_value(row, name, spreadsheet=spreadsheet) for name in fields] for row in rows)
        with NamedTemporaryFile(prefix=".smartreport-export-", suffix=".tmp", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            if spreadsheet:
                self._write_xlsx(temporary, headers, fields, values, TEMPLATES[template])
            else:
                delimiter = "\t" if suffix == ".txt" else ","
                with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream, delimiter=delimiter)
                    writer.writerow(headers)
                    writer.writerows(values)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        self.db.record_export(target, template, len(rows))
        return len(rows)

    @staticmethod
    def _write_xlsx(path, headers, fields, values, title):
        book = Workbook()
        try:
            sheet = book.active
            sheet.title = title
            sheet.freeze_panes = "A2"
            sheet.append(headers)
            for cell in sheet[1]:
                cell.fill = PatternFill("solid", fgColor="153B55")
                cell.font = Font(color="FFFFFF", bold=True)
                cell.alignment = Alignment(vertical="center")
            sheet.row_dimensions[1].height = 24
            widths = [max(12, len(header) * 2 + 3) for header in headers]
            for row_idx, row in enumerate(values, 2):
                for column, value in enumerate(row, 1):
                    cell = sheet.cell(row_idx, column, value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                        width = sum(2 if ord(ch) > 255 else 1 for ch in value)
                        widths[column-1] = max(widths[column-1], min(58, width + 3))
                    if fields[column-1] == "rate":
                        cell.number_format = "0.00%"
            sheet.auto_filter.ref = sheet.dimensions
            for index, width in enumerate(widths, 1):
                sheet.column_dimensions[get_column_letter(index)].width = width
            book.save(path)
        finally:
            book.close()

