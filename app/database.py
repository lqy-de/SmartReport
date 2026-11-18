import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.models import mask_number
from app.validators import validate


SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    inputs TEXT NOT NULL, duplicate_policy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running', counts TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    root TEXT NOT NULL, relative_path TEXT NOT NULL, folder TEXT NOT NULL,
    parent_name TEXT NOT NULL, local_path TEXT NOT NULL, archive_member TEXT, directory_key TEXT NOT NULL,
    kind TEXT NOT NULL, imported_at TEXT NOT NULL, sha256 TEXT,
    status TEXT NOT NULL, message TEXT NOT NULL,
    duplicate_of INTEGER REFERENCES source_files(id)
);
CREATE INDEX IF NOT EXISTS source_hash ON source_files(sha256);
CREATE INDEX IF NOT EXISTS source_folder ON source_files(batch_id, root, folder);
CREATE TABLE IF NOT EXISTS reference_tables (
    source_id INTEGER PRIMARY KEY REFERENCES source_files(id),
    worksheets TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, number TEXT NOT NULL,
    UNIQUE(name, number)
);
CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS exam_records (
    id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES source_files(id),
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    subject_id INTEGER NOT NULL REFERENCES subjects(id), sequence INTEGER NOT NULL,
    page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
    exam_date TEXT NOT NULL, exam_time TEXT NOT NULL, duration TEXT NOT NULL,
    unit TEXT NOT NULL, trade TEXT NOT NULL, job_title TEXT NOT NULL, question TEXT NOT NULL,
    score TEXT, maximum TEXT, recognition_method TEXT NOT NULL,
    raw_fields TEXT NOT NULL, status TEXT NOT NULL,
    UNIQUE(source_id, sequence)
);
CREATE INDEX IF NOT EXISTS exam_identity ON exam_records(candidate_id, subject_id, exam_date, exam_time);
CREATE TABLE IF NOT EXISTS score_items (
    id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exam_records(id),
    project TEXT NOT NULL, content TEXT NOT NULL, maximum TEXT, score TEXT,
    deduction TEXT, note TEXT NOT NULL, page INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS item_exam ON score_items(exam_id);
CREATE TABLE IF NOT EXISTS validation_issues (
    id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exam_records(id),
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revision_history (
    id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exam_records(id),
    changed_at TEXT NOT NULL, field TEXT NOT NULL, before_value TEXT,
    after_value TEXT, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_history (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, exported_at TEXT NOT NULL,
    template TEXT NOT NULL, record_count INTEGER NOT NULL
);
"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def as_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def sql_number(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_files)")}
            if "directory_key" not in columns:
                conn.execute("ALTER TABLE source_files ADD COLUMN directory_key TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE INDEX IF NOT EXISTS source_directory ON source_files(directory_key, kind)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def start_batch(self, inputs, policy: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "INSERT INTO import_batches (started_at, inputs, duplicate_policy) VALUES (?,?,?)",
                (now(), as_json(inputs), policy),
            ).lastrowid

    def finish_batch(self, batch: int, counts: dict, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE import_batches SET finished_at=?, counts=?, status=? WHERE id=?",
                (now(), as_json(counts), status, batch),
            )

    def previous_file(self, digest: str, conn=None) -> int | None:
        if conn is None:
            with self.connect() as reader:
                return self.previous_file(digest, reader)
        row = conn.execute(
            """SELECT id FROM source_files WHERE sha256=?
               AND status IN ('parsed','review','reference') ORDER BY id LIMIT 1""",
            (digest,),
        ).fetchone()
        return row["id"] if row else None

    def save_file(self, source, batch, outcome, policy, digest=None,
                  exams=(), reference=None) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = self.previous_file(digest, conn) if digest else None
            outcome.duplicate_of = previous
            if previous is not None and policy == "skip":
                outcome.status = "duplicate"
                outcome.message = f"内容相同，已跳过（原文件编号 {previous}）"
            elif previous is not None:
                outcome.message = f"与文件编号 {previous} 内容相同。{outcome.message}"
                for exam in exams:
                    exam.issues.append("相同文件的重新导入版本")
                if exams:
                    outcome.status = "review"
            source_id = conn.execute(
                """INSERT INTO source_files
                   (batch_id,root,relative_path,folder,parent_name,local_path,archive_member,
                    directory_key,kind,imported_at,sha256,status,message,duplicate_of)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (batch, source.root, source.relative, source.folder, source.parent,
                 str(source.path), source.member, as_json(source.directory_key), source.kind, now(), digest,
                 outcome.status, outcome.message, previous),
            ).lastrowid
            if outcome.status == "duplicate":
                return
            if reference is not None:
                conn.execute("INSERT INTO reference_tables VALUES (?,?)", (source_id, as_json(reference)))
            review_count = sum(
                self._save_exam(conn, source_id, seq, exam, source.relative)
                for seq, exam in enumerate(exams, 1)
            )
            outcome.records = len(exams)
            outcome.review = review_count
            if review_count and outcome.status != "review":
                outcome.status = "review"
            if exams:
                detail = f"识别 {len(exams)} 条成绩，其中 {review_count} 条待复核。"
                outcome.message = detail + outcome.message
                conn.execute("UPDATE source_files SET status=?, message=? WHERE id=?",
                             (outcome.status, outcome.message, source_id))

    @staticmethod
    def _save_exam(conn, source_id, seq, exam, filename) -> bool:
        conn.execute("INSERT OR IGNORE INTO candidates(name,number) VALUES (?,?)",
                     (exam.name, exam.number))
        candidate = conn.execute("SELECT id FROM candidates WHERE name=? AND number=?",
                                 (exam.name, exam.number)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO subjects(name) VALUES (?)", (exam.subject,))
        subject = conn.execute("SELECT id FROM subjects WHERE name=?", (exam.subject,)).fetchone()[0]
        issues = validate(exam, Path(filename).name)
        if exam.number and exam.date and (
            exam.subject == "手信号识别" or (exam.time and exam.question)
        ):
            earlier = conn.execute(
                """SELECT score,maximum FROM exam_records WHERE candidate_id=? AND subject_id=?
                   AND exam_date=? AND exam_time=? AND question=?""",
                (candidate, subject, exam.date, exam.time, exam.question),
            ).fetchall()
            if earlier:
                same = any(
                    (r["score"], r["maximum"]) == (sql_number(exam.score), sql_number(exam.maximum))
                    for r in earlier
                )
                issues.append("已有相同考试记录" if same else "同一考试存在不同成绩版本")
        exam_id = conn.execute(
            """INSERT INTO exam_records
               (source_id,candidate_id,subject_id,sequence,page_start,page_end,exam_date,exam_time,
                duration,unit,trade,job_title,question,score,maximum,recognition_method,raw_fields,status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, candidate, subject, seq, exam.page_start, exam.page_end, exam.date, exam.time,
             exam.duration, exam.unit, exam.trade, exam.job_title, exam.question, sql_number(exam.score),
             sql_number(exam.maximum), "PDF 原生文字与版式规则", as_json(exam.raw),
             "review" if issues else "recognized"),
        ).lastrowid
        conn.executemany(
            """INSERT INTO score_items (exam_id,project,content,maximum,score,deduction,note,page)
               VALUES (?,?,?,?,?,?,?,?)""",
            ((exam_id, i.project, i.content, sql_number(i.maximum), sql_number(i.score),
              sql_number(i.deduction), i.note, i.page) for i in exam.items),
        )
        conn.executemany("INSERT INTO validation_issues(exam_id,message) VALUES (?,?)",
                         ((exam_id, issue) for issue in issues))
        return bool(issues)

    def batches(self):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM import_batches ORDER BY id DESC").fetchall()

    def files(self, batch: int):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM source_files WHERE batch_id=? ORDER BY id", (batch,)).fetchall()

    def grades(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT e.*, c.name,c.number,s.name AS subject,f.root,f.folder,f.parent_name,
                   f.relative_path,f.local_path,f.archive_member,f.batch_id,f.imported_at
                   FROM exam_records e
                   JOIN source_files f ON f.id=e.source_id
                   JOIN candidates c ON c.id=e.candidate_id
                   JOIN subjects s ON s.id=e.subject_id
                   ORDER BY f.root,f.folder,f.id,e.sequence"""
            ).fetchall()
        grades = []
        for row in rows:
            grade = dict(row)
            grade["masked_number"] = mask_number(grade.pop("number"))
            for field in ("score", "maximum"):
                if grade[field] is not None:
                    grade[field] = Decimal(grade[field])
            score, maximum = grade["score"], grade["maximum"]
            grade["rate"] = score / maximum if score is not None and maximum and maximum > 0 else None
            grades.append(grade)
        return grades

    def detail(self, exam: dict):
        with self.connect() as conn:
            items = conn.execute("SELECT * FROM score_items WHERE exam_id=? ORDER BY id", (exam["id"],)).fetchall()
            issues = conn.execute("SELECT message FROM validation_issues WHERE exam_id=?", (exam["id"],)).fetchall()
            references = conn.execute(
                """SELECT DISTINCT f.relative_path FROM source_files f
                   JOIN reference_tables r ON r.source_id=COALESCE(
                       CASE WHEN f.status='duplicate' THEN f.duplicate_of END, f.id
                   )
                   JOIN source_files original ON original.id=?
                   WHERE f.kind IN ('xls','xlsx') AND (
                       (f.directory_key <> '' AND f.directory_key=original.directory_key)
                       OR (f.batch_id=original.batch_id AND f.root=original.root AND f.folder=original.folder)
                   ) ORDER BY f.relative_path""",
                (exam["source_id"],),
            ).fetchall()
            changes = conn.execute(
                "SELECT * FROM revision_history WHERE exam_id=? ORDER BY id DESC", (exam["id"],),
            ).fetchall()
        return items, issues, references, changes

    def score_items(self, exam_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM score_items WHERE exam_id=? ORDER BY id", (exam_id,),
            ).fetchall()

    def confirm(self, exam_id: int, score: Decimal, reason: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT score,maximum,status FROM exam_records WHERE id=?", (exam_id,)).fetchone()
            if (old is None or not reason.strip() or not score.is_finite() or score < 0
                or (old["maximum"] is not None and score > Decimal(old["maximum"]))):
                raise ValueError("请填写核准原因和有效得分")
            for field, before, after in (
                ("score", old["score"], sql_number(score)), ("status", old["status"], "approved"),
            ):
                if before != after:
                    conn.execute(
                        """INSERT INTO revision_history
                           (exam_id,changed_at,field,before_value,after_value,reason)
                           VALUES (?,?,?,?,?,?)""",
                        (exam_id, now(), field, before, after, reason.strip()),
                    )
            conn.execute("UPDATE exam_records SET score=?,status='approved' WHERE id=?",
                         (sql_number(score), exam_id))

    def previous_exports(self) -> set[Path]:
        with self.connect() as conn:
            return {Path(row[0]) for row in conn.execute("SELECT DISTINCT path FROM export_history")}

    def record_export(self, path: Path, template: str, count: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO export_history(path,exported_at,template,record_count) VALUES (?,?,?,?)",
                (str(path.resolve()), now(), template, count),
            )

