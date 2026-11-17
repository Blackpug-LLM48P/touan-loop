#!/usr/bin/env python3
"""print.json から、A4 の印刷用プリント（PDF）を作る。

並びは固定：傾向の解説 → 対策 → 問題 → 解答と解説（解答は新しいページから）。
記述問題には字数ぶんのマス目を付ける。

使い方:
    python3 build_print.py print.json out/print.pdf [--font-dir fonts]

必要なもの: reportlab、IPAゴシック（ipagp.ttf と ipag.ttf）
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer

BODY = "IPAPGothic"  # 本文（ipagp.ttf）
MONO = "IPAGothic"   # 等幅（ipag.ttf）
MARGIN = 20 * mm
CELL = 7 * mm        # マス目1つの大きさ
PER_ROW = 20         # マス目の1行の字数

FONT_DIRS = [
    "fonts",
    "/usr/share/fonts/opentype/ipafont-gothic",
    "/usr/share/fonts/truetype/ipafont-gothic",
    os.path.expanduser("~/Library/Fonts"),
    "/Library/Fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    r"C:\Windows\Fonts",
]


def register_fonts(font_dir):
    dirs = ([font_dir] if font_dir else []) + FONT_DIRS
    for name, filename in ((BODY, "ipagp.ttf"), (MONO, "ipag.ttf")):
        for d in dirs:
            path = os.path.join(d, filename)
            if os.path.isfile(path):
                pdfmetrics.registerFont(TTFont(name, path))
                break
        else:
            sys.exit(
                f"フォント {filename} が見つかりません。"
                "IPAゴシックを入手して fonts/ に置くか、--font-dir で場所を指定してください。"
            )


class MasuGrid(Flowable):
    """記述問題用のマス目。5字ごとに小さな目印を付ける。"""

    def __init__(self, chars):
        super().__init__()
        self.chars = chars
        self.rows = (chars + PER_ROW - 1) // PER_ROW

    def wrap(self, avail_w, avail_h):
        return PER_ROW * CELL, self.rows * CELL + 4 * mm

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        top = self.rows * CELL
        for i in range(self.chars):
            row, col = divmod(i, PER_ROW)
            x, y = col * CELL, top - (row + 1) * CELL
            c.rect(x, y, CELL, CELL)
            if (i + 1) % 5 == 0:
                c.setFont(MONO, 5)
                c.drawRightString(x + CELL - 0.6 * mm, y + 0.7 * mm, str(i + 1))
        c.setFont(BODY, 8)
        c.drawString(0, top + 1 * mm, f"（{self.chars}字以内）")


class AnswerBox(Flowable):
    """短答用の答え欄。"""

    def __init__(self, width=80 * mm, height=11 * mm):
        super().__init__()
        self.w, self.h = width, height

    def wrap(self, avail_w, avail_h):
        return self.w, self.h + 2 * mm

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.rect(0, 0, self.w, self.h)
        c.setFont(BODY, 8)
        c.drawString(1.5 * mm, self.h - 3.5 * mm, "答え")


def validate(data):
    """作る前に入力を確かめる。問題があれば一覧にして止まる。

    必須: title, trend, strategy, questions（各問は id, type, text, answer, explanation）
    任意: subject, scope
    """
    errors = []
    if not isinstance(data, dict):
        sys.exit("入力に問題があります:\n- 全体が { } の形になっていません")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errors.append("「title」がありません")
    for key in ("trend", "strategy"):
        v = data.get(key)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
            errors.append(f"「{key}」は1つ以上の文のリストにしてください")
    for key in ("subject", "scope"):
        if key in data and not isinstance(data[key], str):
            errors.append(f"「{key}」は文字で書いてください")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("「questions」は1問以上のリストにしてください")
        questions = []
    seen = set()
    for n, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            errors.append(f"{n}番目の問題が {{ }} の形になっていません")
            continue
        qid = q.get("id")
        if not isinstance(qid, str) or not qid.strip():
            errors.append(f"{n}番目の問題: 「id」がありません（文字で書く。例 \"1\"）")
            label = f"{n}番目"
        else:
            label = qid
            if qid in seen:
                errors.append(f"問 {qid}: 番号が重なっています")
            seen.add(qid)
        for key in ("text", "answer", "explanation"):
            if not isinstance(q.get(key), str) or not q[key].strip():
                errors.append(f"問 {label}: 「{key}」がありません")
        qtype = q.get("type")
        if qtype not in ("short", "essay"):
            errors.append(f"問 {label}: 「type」は short か essay にしてください（今の値: {qtype!r}）")
        elif qtype == "essay":
            chars = q.get("chars")
            if not isinstance(chars, int) or isinstance(chars, bool) or chars <= 0:
                errors.append(f"問 {label}: 記述問題には字数（chars）が必要です")
            elif isinstance(q.get("answer"), str) and len(q["answer"]) > chars:
                errors.append(
                    f"問 {label}: 模範解答が {len(q['answer'])} 字で、マス目の {chars} 字を超えています"
                )
    if errors:
        sys.exit("入力に問題があります:\n- " + "\n- ".join(errors))


def para(text, style):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def build(data, out_path):
    base = dict(fontName=BODY, wordWrap="CJK")
    title = ParagraphStyle("title", fontSize=16, leading=22, spaceAfter=2 * mm, **base)
    meta = ParagraphStyle("meta", fontSize=9, leading=13, spaceAfter=4 * mm, **base)
    head = ParagraphStyle("head", fontSize=13, leading=18, spaceBefore=5 * mm, spaceAfter=2 * mm, **base)
    body = ParagraphStyle("body", fontSize=10.5, leading=17, **base)
    item = ParagraphStyle("item", parent=body, leftIndent=5 * mm, firstLineIndent=-5 * mm)
    qtext = ParagraphStyle("qtext", parent=body, spaceBefore=4 * mm, spaceAfter=2 * mm,
                           leftIndent=9 * mm, firstLineIndent=-9 * mm)
    indent = ParagraphStyle("indent", parent=body, leftIndent=9 * mm)

    story = [para(data["title"], title)]
    info = "　".join(x for x in (data.get("subject"), data.get("scope")) if x)
    head_line = "＿＿月＿＿日　／　名前＿＿＿＿＿＿＿＿＿＿"
    story.append(para(f"{info}　／　{head_line}" if info else head_line, meta))

    story.append(para("1　傾向の解説", head))
    story += [para(f"・{t}", item) for t in data["trend"]]
    story.append(para("2　対策", head))
    story += [para(f"・{t}", item) for t in data["strategy"]]

    story.append(para("3　問題", head))
    for q in data["questions"]:
        story.append(para(f"【{q['id']}】 {q['text']}", qtext))
        if q.get("type") == "essay":
            story.append(MasuGrid(q["chars"]))
        else:
            story.append(AnswerBox())
        story.append(Spacer(1, 2 * mm))

    story.append(PageBreak())
    story.append(para("4　解答と解説", head))
    for q in data["questions"]:
        story.append(para(f"【{q['id']}】 答え：{q['answer']}", qtext))
        story.append(para(q["explanation"], indent))

    def footer(canvas, doc):
        canvas.setFont(BODY, 8)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, str(doc.page))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN, title=data["title"])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    ap = argparse.ArgumentParser(description="print.json から A4 の印刷用プリントを作る")
    ap.add_argument("input", help="print.json")
    ap.add_argument("output", help="出力する PDF")
    ap.add_argument("--font-dir", help="ipagp.ttf と ipag.ttf のあるフォルダ")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    validate(data)
    register_fonts(args.font_dir)
    build(data, args.output)
    print(f"作成しました: {args.output}（問題 {len(data['questions'])} 問）")


if __name__ == "__main__":
    main()
