from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ScoreItem:
    project: str
    content: str
    maximum: Decimal | None
    score: Decimal | None
    deduction: Decimal | None
    note: str
    page: int


@dataclass
class Exam:
    subject: str
    page_start: int
    page_end: int
    name: str = ""
    number: str = ""
    job_title: str = ""
    trade: str = ""
    unit: str = ""
    question: str = ""
    date: str = ""
    time: str = ""
    duration: str = ""
    score: Decimal | None = None
    maximum: Decimal | None = None
    items: list[ScoreItem] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def mask_number(number: str) -> str:
    return "•" * min(len(number), 8) + number[-4:] if len(number) > 4 else "•" * len(number)

