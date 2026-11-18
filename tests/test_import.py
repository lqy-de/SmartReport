from collections import Counter
from io import BytesIO
from zipfile import ZipFile

import pymupdf
from openpyxl import Workbook

from app.database import Database
from app.exporters import ExportService
from app.services.importer import ImportService


from samples.generate_samples import generate


def reference_workbook(destination):
    workbook = Workbook()
    workbook.active.append(["姓名", "参考得分"])
    workbook.active.append(["测试名称", 999])
    workbook.save(destination)
    workbook.close()


def test_recursive_import_provenance_references_and_duplicate_policy(tmp_path, samples):
    root = tmp_path / "导入目录"
    subtree = root / "东区" / "同名"
    second = root / "西区" / "同名"
    output = root / "自选输出目录"
    cache = root / ".smartreport"
    for path in (subtree, second, output, cache):
        path.mkdir(parents=True)
    source = subtree / "成绩.PDF"
    source.write_bytes(samples[0].read_bytes())
    (second / "副本.pdf").write_bytes(source.read_bytes())
    reference_workbook(subtree / "参考.xlsx")
    reference_workbook(cache / "被排除.xlsx")
    reference_workbook(output / "被排除.xlsx")
    (root / "跳过.zip").write_bytes(b"not selected explicitly")
    (root / "说明.docx").write_text("unsupported", encoding="utf-8")
    (second / "已损坏.pdf").write_bytes(b"corrupt")
    missing = tmp_path / "不可读取.pdf"
    db = Database(tmp_path / "state" / "grades.sqlite3")
    service = ImportService(db, excluded_roots=[output])
    progress = []
    batch, counts = service.run([source, root, missing], progress=lambda *args: progress.append(args[:3]))
    assert counts == {
        "excluded": 2, "unreadable": 1, "unsupported": 2, "parsed": 1, "duplicate": 1,
        "damaged": 1, "reference": 1, "records": 1, "review_records": 0,
    }
    assert progress[0][0] == "扫描"
    assert progress[-1] == ("解析", 4, 4)
    exam, = db.grades()
    assert (exam["batch_id"], exam["folder"], exam["parent_name"], exam["relative_path"]) == (
        batch, "东区/同名", "同名", "东区/同名/成绩.PDF",
    )
    assert exam["imported_at"]
    assert (exam["score"], exam["maximum"]) == (73.75, 100)
    assert [row[0] for row in db.detail(exam)[2]] == ["东区/同名/参考.xlsx"]
    original = [f for f in db.files(batch) if f["status"] == "parsed"][0]
    duplicate = [f for f in db.files(batch) if f["status"] == "duplicate"][0]
    assert original["sha256"] == duplicate["sha256"]
    assert duplicate["duplicate_of"] == original["id"]

    batch2, counts = service.run([second / "副本.pdf"], policy="reimport")
    assert counts["records"] == counts["review_records"] == 1
    repeated, = db.files(batch2)
    assert repeated["duplicate_of"] == original["id"]
    assert len(db.grades()) == 2


def test_explicit_zip_keeps_internal_parent_and_rejects_traversal(tmp_path, samples):
    db = Database(tmp_path / "grades.sqlite3")
    service = ImportService(db)
    zipped = tmp_path / "兼容.zip"
    workbook = BytesIO()
    reference_workbook(workbook)
    with ZipFile(zipped, "w") as target:
        target.writestr("批次A/二级/工作表.xlsx", workbook.getvalue())
        target.writestr("批次A/二级/成绩.pdf", samples[0].read_bytes())
        target.writestr("批次A/说明.txt", "unsupported")
    batch, counts = service.run([zipped])
    assert counts["archive"] == counts["unsupported"] == counts["reference"] == 1
    exam, = db.grades()
    assert (exam["folder"], exam["parent_name"], exam["archive_member"]) == (
        "批次A/二级", "二级", "批次A/二级/成绩.pdf",
    )
    assert exam["batch_id"] == batch
    assert len(db.detail(exam)[2]) == 1
    unsafe = tmp_path / "不安全.zip"
    with ZipFile(unsafe, "w") as target:
        target.writestr("../不应创建.pdf", b"unsafe")
    batch, counts = service.run([unsafe])
    assert counts["damaged"] == 1
    assert len(db.files(batch)) == 1
    assert not (tmp_path.parent / "不应创建.pdf").exists()


def test_rejects_zip_compression_bomb(tmp_path):
    from zipfile import ZIP_DEFLATED

    zipped = tmp_path / "异常压缩比.zip"
    with ZipFile(zipped, "w", compression=ZIP_DEFLATED) as target:
        target.writestr("空白.pdf", b"0" * (1024 * 1024))
    db = Database(tmp_path / "state.sqlite3")
    batch, counts = ImportService(db).run([zipped])
    assert counts["damaged"] == 1
    assert "压缩比" in db.files(batch)[0]["message"]


def test_password_protected_pdf_unreadable(tmp_path):
    pdf = tmp_path / "需要密码.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(pdf, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                      owner_pw="owner-password", user_pw="user-password")
    db = Database(tmp_path / "state.sqlite3")
    batch, counts = ImportService(db).run([pdf])
    assert counts["unreadable"] == 1
    assert "密码" in db.files(batch)[0]["message"]


def test_synthetic_folder_to_database_and_xlsx(tmp_path):
    from openpyxl import load_workbook

    tree = tmp_path / "样本"
    generate(tree / "模拟批次")
    reference_workbook(tree / "模拟批次" / "参考.xlsx")
    db = Database(tmp_path / "data" / "grades.sqlite3")
    service = ImportService(db)
    batch, counts = service.run([tree])
    assert counts["reference"] == 1
    assert counts["records"] == 3
    assert counts["review_records"] == 1
    assert counts.get("damaged", 0) == counts.get("unreadable", 0) == counts.get("unrecognized", 0) == 0
    rows = db.grades()
    assert Counter(row["subject"] for row in rows) == {"操作技能": 2, "手信号识别": 1}
    assert Counter(row["folder"] for row in rows) == {"模拟批次": 3}
    assert all(row["batch_id"] == batch and db.detail(row)[2] for row in rows)
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reference_tables").fetchone()[0] == 1
    # These expectations come exclusively from our fictional generator.
    by_source = {row["relative_path"]: row for row in rows}
    assert {path.rsplit("/", 1)[-1]: (r["score"], r["maximum"])
            for path, r in by_source.items()} == {
        "demo_skill_a.pdf": (73.75, 100), "demo_skill_b.pdf": (36.25, 100),
        "demo_signal.pdf": (9, 20),
    }
    first = by_source["模拟批次/demo_skill_a.pdf"]
    assert (first["page_start"], first["page_end"]) == (1, 1)
    items = db.detail(first)[0]
    assert (items[0]["maximum"], items[0]["score"], items[0]["deduction"]) == ("40", "31.25", None)
    assert "虚构数据" in items[0]["note"]
    assert {item["page"] for item in items} == {1}
    count = ExportService(db).export(tree / "汇总.xlsx", rows, "scores", ["score", "maximum", "folder"])
    book = load_workbook(tree / "汇总.xlsx", read_only=True)
    try:
        assert book.active.max_row == count + 1 == 4
    finally:
        book.close()
    second_batch, skipped = service.run([tree])
    assert skipped["duplicate"] == 4
    assert skipped["excluded"] == 1
    assert len(db.grades()) == 3
    assert any(row["status"] == "excluded" for row in db.files(second_batch))

