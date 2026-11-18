import csv
from decimal import Decimal

from openpyxl import load_workbook

from app.database import Database
from app.exporters import ExportService


def test_export_roundtrip_and_no_xlsx_formula(tmp_path):
    db = Database(tmp_path / "state.sqlite3")
    exports = ExportService(db)
    row = {
        "name": '=HYPERLINK("https://example.com")', "score": Decimal("2.5"),
        "status": "review", "folder": "日期/单位", "rate": Decimal("0.25"),
    }
    fields = ["name", "score", "rate", "status", "folder"]
    for suffix in ("xlsx", "csv", "txt"):
        target = tmp_path / f"中文成绩.{suffix}"
        assert exports.export(target, [row], "scores", fields) == 1
        if suffix == "xlsx":
            book = load_workbook(target)
            try:
                cells = book.active[2]
                assert [cell.value for cell in cells] == [row["name"], 2.5, 0.25, "待复核", "日期/单位"]
                assert cells[0].data_type == "s"
                assert cells[2].number_format == "0.00%"
            finally:
                book.close()
        else:
            with target.open(encoding="utf-8-sig", newline="") as stream:
                values = list(csv.reader(stream, delimiter="\t" if suffix == "txt" else ","))[1]
            assert values == ["'" + row["name"], "2.5", "25.00%", "待复核", "日期/单位"]
    assert len(db.previous_exports()) == 3

