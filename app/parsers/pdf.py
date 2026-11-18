import re
from datetime import date

import pymupdf

from app.models import Exam, ScoreItem
from app.validators import DECIMAL, number


class ParseError(Exception):
    pass


class DamagedFile(ParseError):
    pass


class UnreadableFile(ParseError):
    pass


class UnrecognizedPdf(ParseError):
    pass


FIELDS = {
    "准考证(?:号码|号)?": "number", "姓名": "name", "职名": "job_title", "工种": "trade",
    "单位": "unit", "试题名称": "question", "考核时长": "duration",
    "考核日期": "date", "考核时间": "time",
}
HEADER = re.compile(
    rf"(?m)^[ \t]*(?P<label>{'|'.join(FIELDS)}|项目)[ \t]*(?:[:：][ \t]*|\n)"
)
SKILL = re.compile(r"操作技能考核评分记录(?:表)?")
SIGNAL = "手信号识别考试系统"


def normalize_date(value: str) -> str:
    match = re.fullmatch(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", value.strip())
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return ""


def clean(value: str | None) -> str:
    return (value or "").replace("\n", "").strip()


def start_skill(text: str, page: int) -> Exam:
    parsed = {}
    section = text.split("\n项目\n", 1)[0] + "\n项目\n"
    matches = list(HEADER.finditer(section))
    for field, following in zip(matches, matches[1:]):
        label = field.group("label")
        key = next(key for pattern, key in FIELDS.items() if re.fullmatch(pattern, label))
        value = clean(section[field.end():following.start()])
        if key == "number":
            value = re.sub(r"^(?:号码|号)[:：]?", "", value).strip()
        parsed[key] = value
    raw = dict(parsed)
    parsed["date"] = normalize_date(parsed.get("date", ""))
    return Exam("操作技能", page, page, raw=raw, **parsed)


def consume_skill(page, text: str, exam: Exam) -> None:
    raw_total = re.search(rf"总得分[：:]\s*({DECIMAL})", text)
    if raw_total:
        exam.raw["printed_score"] = raw_total[1]
        exam.score = number(raw_total[1])
    for table in page.find_tables().tables:
        rows = table.extract()
        if table.col_count == 13:
            header = next((i for i,r in enumerate(rows) if "考核内容" in r and "配分" in r), None)
            if header is None:
                continue
            rows = [[r[i] for i in (0, 2, 7, 9, 10, 12)] for r in rows[header+1:]]
        elif table.col_count == 7 and any(clean(r[0]) == "合计" for r in rows):
            # This template splits assessment content into step and disqualifier columns.
            rows = [[r[0], " ".join(filter(None, (r[1], r[2]))), *r[3:]] for r in rows]
        elif table.col_count != 6:
            if any("(操作)" in (v or "") or "(语音)" in (v or "") for r in rows for v in r):
                exam.issues.append(f"第 {page.number+1} 页评分列无法对齐")
            continue
        project = exam.items[-1].project if exam.items else ""
        for row in rows:
            group, content, cap, scored, deducted, note = map(clean, row)
            if group in ("合计", "小计", "总计"):
                if group != "小计":
                    exam.raw["total_row"] = [cap, scored, deducted, note]
                    exam.maximum = number(cap)
                    table_score = number(scored)
                    if exam.score is None:
                        exam.score = table_score
                    elif table_score is not None and exam.score != table_score:
                        exam.issues.append("合计行与总得分不一致")
                continue
            if not content or content in ("考核内容", "考评员：", "考评员:"):
                continue
            if not any(value is not None for value in map(number, (cap, scored, deducted))):
                if content.startswith(("(操作)", "(语音)", "（操作）", "（语音）")):
                    exam.issues.append(f"第 {page.number+1} 页存在未对齐的小分行")
                else:
                    continue
            project = group or project
            exam.items.append(ScoreItem(
                project, content, number(cap), number(scored), number(deducted), note,
                page.number + 1,
            ))
    if raw_total and exam.maximum is None:
        total_line = re.search(rf"(?:^|\n)合计\s*\n\s*({DECIMAL})\s*\n\s*({DECIMAL})", text)
        if total_line:
            exam.maximum = number(total_line[1])
            if number(total_line[2]) != exam.score:
                exam.issues.append("合计行与总得分不一致")
            exam.raw["total_row_text"] = total_line.group().strip()


def start_signal(text: str, page: int, prior: list[Exam]) -> Exam:
    name = re.search(r"(?m)^姓名[：:][ \t]*([^\n]+)", text)
    day = re.search(r"(?m)^考试日期[：:][ \t]*([^\n]+)", text)
    name_text = name[1].strip() if name else ""
    date_text = day[1].strip() if day else ""
    exam = Exam("手信号识别", page, page, name=name_text, date=normalize_date(date_text))
    exam.raw.update(name=name_text, date=date_text)
    matching = [x for x in prior if x.subject == "操作技能" and x.name == exam.name
                and exam.name and x.date == exam.date and exam.date and x.number]
    identities = {(x.number, x.unit, x.trade, x.job_title) for x in matching}
    if len(identities) == 1:
        exam.number, exam.unit, exam.trade, exam.job_title = identities.pop()
        exam.raw["identity_from_pages"] = [x.page_start for x in matching]
    return exam


def consume_signal(page, text: str, exam: Exam) -> None:
    total = re.search(rf"(?m)^得分[：:]\s*({DECIMAL})\s*/\s*({DECIMAL})", text)
    if total:
        exam.score, exam.maximum = map(number, total.groups())
        exam.raw["printed_total"] = total.group().strip()
    expected = re.search(r"总题数[：:]\s*(\d+)", text)
    if expected:
        exam.raw["question_count"] = int(expected[1])
    words = page.get_text("words")
    anchors = {w[4]: w for w in words if w[4] in ("题号", "该题成绩")}
    if not {"题号", "该题成绩"}.issubset(anchors):
        return
    index_x = anchors["题号"][0]
    score_header = anchors["该题成绩"]
    for x, y, _, _, word, *_ in sorted(words, key=lambda w: w[1]):
        grade = re.fullmatch(rf"({DECIMAL})/({DECIMAL})", word)
        if not grade or abs(x - score_header[0]) > 35 or y <= score_header[1]:
            continue
        indices = [w[4] for w in words if abs(w[1]-y) < 3 and
                   abs(w[0]-index_x) < 25 and w[4].isdigit()]
        if len(indices) == 1:
            score, maximum = map(number, grade.groups())
            exam.items.append(ScoreItem(
                "手信号识别", f"第 {indices[0]} 题", maximum, score, None, "", page.number+1,
            ))


def parse_pdf(data: bytes, page_progress=None) -> tuple[list[Exam], list[str]]:
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError) as exc:
        raise DamagedFile("PDF 文件结构损坏或内容无效") from exc
    exams = []
    warnings = []
    current = None
    with doc:
        if doc.needs_pass:
            raise UnreadableFile("PDF 需要打开密码")
        if not doc.is_pdf or doc.is_repaired or not doc.page_count:
            raise DamagedFile("PDF 结构损坏、需要修复或没有页面")
        for page in doc:
            idx = page.number + 1
            if page_progress:
                page_progress(idx, doc.page_count)
            text = page.get_text()
            first_lines = text.splitlines()[:3]
            if any(SKILL.search(line) for line in first_lines):
                header_fields = text.split("\n项目\n", 1)[0]
                has_exam_header = any(label in header_fields for label in ("准考证", "试题名称", "考核日期"))
                if current is None or current.subject != "操作技能" or has_exam_header:
                    current = start_skill(text, idx)
                    exams.append(current)
            elif any(SIGNAL in line for line in first_lines):
                # A repeated title without an identity header is a continuation.
                if current is None or current.subject != "手信号识别" or "姓名" in text:
                    current = start_signal(text, idx, exams)
                    exams.append(current)
            elif not text.strip():
                warnings.append(f"第 {idx} 页无文字层，需人工核对")
            elif current is None:
                warnings.append(f"第 {idx} 页版式暂未支持，需人工核对")
            elif not (
                current.subject == "操作技能"
                and re.search(r"\(操作\)|\(语音\)|合计|^说明\s*[:：]|考评员|^\s*\d+\s*$", text, re.M)
            ) and not (
                current.subject == "手信号识别"
                and re.search(r"题号|该题成绩|总题数|得分[：:]", text)
            ):
                warnings.append(f"第 {idx} 页未能归入已识别考试，需人工核对")
            if current is None:
                continue
            current.page_end = idx
            if current.subject == "操作技能":
                consume_skill(page, text, current)
            else:
                consume_signal(page, text, current)
    if not exams:
        raise UnrecognizedPdf("未匹配已支持的 PDF 版式或无文字层")
    for exam in exams:
        if exam.subject == "手信号识别" and exam.raw.get("question_count") != len(exam.items):
            exam.issues.append("手信号题数与明细数量不一致")
        if warnings:
            exam.issues.append("来源文件有需人工核对的页面")
    return exams, warnings

