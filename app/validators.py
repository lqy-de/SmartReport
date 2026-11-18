import re
from datetime import time
from decimal import Decimal

from app.models import Exam


DECIMAL = r"[+-]?\d+(?:\.\d+)?"


def number(text: str) -> Decimal | None:
    text = text.strip()
    return Decimal(text) if re.fullmatch(DECIMAL, text) else None


def validate(exam: Exam, filename: str) -> list[str]:
    issues = exam.issues.copy()
    if not exam.name or not exam.number:
        issues.append("考生身份信息不完整")
    if not exam.date:
        issues.append("考核日期缺失或格式异常")
    if exam.subject == "操作技能":
        if not exam.question or not exam.unit or not exam.trade:
            issues.append("操作技能表头字段不完整")
        try:
            times = re.split(r"[~～至]", exam.time)
            if len(times) != 2:
                raise ValueError
            for value in times:
                time.fromisoformat(value.strip())
        except ValueError:
            issues.append("考核时间缺失或格式异常")
    if exam.score is None or exam.maximum is None:
        issues.append("原始得分或配分缺失")
    elif exam.maximum <= 0 or exam.score < 0 or exam.score > exam.maximum:
        issues.append("原始得分超出配分范围")
    if not exam.items:
        issues.append("未识别到小分")
    else:
        for attr, reported, label in (
            ("score", exam.score, "得分"), ("maximum", exam.maximum, "配分")
        ):
            values = [getattr(item, attr) for item in exam.items]
            if any(value is None for value in values):
                issues.append(f"小分{label}有缺失")
            elif reported is not None and sum(values) != reported:
                issues.append(f"小分{label}合计与原表不一致")
        if any(
            i.score is not None and (
                i.score < 0 or (i.maximum is not None and i.score > i.maximum)
            ) for i in exam.items
        ):
            issues.append("小分超出配分范围")
    if any(word in filename for word in ("更正", "修改", "补录", "重考", "补考", "待核")):
        issues.append("文件名标记了修改、补录或复核")
    return list(dict.fromkeys(issues))

