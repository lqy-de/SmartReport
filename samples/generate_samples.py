"""Generate fictional PDFs without reading any existing report or personal data."""

import argparse
from pathlib import Path

import pymupdf


def text(page, x, y, value, size=11):
    page.insert_text((x, y), value, fontname="china-s", fontsize=size)


def skill_pdf(path, label, scores):
    with pymupdf.open() as document:
        page = document.new_page(width=700, height=520)
        text(page, 40, 35, "操作技能考核评分记录表", 18)
        fields = [
            ("姓名", f"模拟考生{label}"), ("准考证号", f"DEMO-ONLY-{label}"),
            ("职名", "模拟岗位"), ("工种", "模拟工种"), ("单位", "虚构测试单位"),
            ("试题名称", "合成流程测试"), ("考核日期", "2099-01-01"),
            ("考核时间", "09:00~09:30"),
        ]
        for i, (key, value) in enumerate(fields):
            text(page, 40, 65 + i * 22, f"{key}：{value}")
        columns = [40, 110, 400, 460, 530, 585, 660]
        rows = [
            ["项目", "考核内容", "配分", "得分", "扣分", "备注"],
            ["模拟项目", "(操作)合成步骤一", "40", str(scores[0]), "", "虚构数据"],
            ["模拟项目", "(操作)合成步骤二", "60", str(scores[1]), "", "虚构数据"],
            ["合计", "", "100", str(sum(scores)), "", ""],
        ]
        top, height = 255, 35
        for y in range(len(rows) + 1):
            page.draw_line((columns[0], top + y * height), (columns[-1], top + y * height))
        for x in columns:
            page.draw_line((x, top), (x, top + len(rows) * height))
        for i, row in enumerate(rows):
            for x, value in zip(columns, row):
                text(page, x + 5, top + i * height + 23, value, 10)
        text(page, 40, 430, f"总得分：{sum(scores)}")
        text(page, 40, 475, "仅用于软件测试，所有身份、单位、日期和分值均为程序虚构。", 10)
        document.set_metadata({"title": "SmartReport synthetic skill sample", "author": "Synthetic data generator"})
        document.save(path)


def signal_pdf(path):
    with pymupdf.open() as document:
        page = document.new_page(width=500, height=420)
        for y, value in [(35, "手信号识别考试系统"), (70, "姓名：模拟考生丙"),
                         (95, "考试日期：2099-01-01")]:
            text(page, 40, y, value)
        text(page, 40, 140, "题号")
        text(page, 200, 140, "该题成绩")
        for y, index, score in [(175, "1", "4/10"), (210, "2", "5/10")]:
            text(page, 40, y, index)
            text(page, 200, y, score)
        text(page, 40, 265, "总题数：2")
        text(page, 40, 290, "得分：9/20")
        text(page, 40, 345, "虚构数据；独立报告缺少准考证号，应进入待复核。", 10)
        document.set_metadata({"title": "SmartReport synthetic signal sample", "author": "Synthetic data generator"})
        document.save(path)


def generate(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    first = destination / "demo_skill_a.pdf"
    second = destination / "demo_skill_b.pdf"
    signal = destination / "demo_signal.pdf"
    skill_pdf(first, "甲", (31.25, 42.5))
    skill_pdf(second, "乙", (13.5, 22.75))
    signal_pdf(signal)
    return [first, second, signal]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "generated")
    arguments = parser.parse_args()
    for path in generate(arguments.output):
        print(path)
