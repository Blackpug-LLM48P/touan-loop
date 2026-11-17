#!/usr/bin/env python3
"""print.json から、A4 の印刷用プリント（PDF）を作る。

並びは固定：傾向の解説 → 対策 → 問題 → 解答と解説（解答は新しいページから）。
記述問題には字数ぶんのマス目、選択問題には選択肢と記号の欄、計算問題には式を書く欄を付ける。

使い方:
    python3 build_print.py print.json out/print.pdf [--font-dir fonts]

必要なもの: reportlab、IPAゴシック（ipagp.ttf と ipag.ttf）
"""
import argparse
import json
import os
import sys
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer

# ---- 見た目の決まり ----
BODY = "IPAPGothic"  # 本文
MONO = "IPAGothic"   # 等幅（マス目の数字）
FONT_FILES = {BODY: "ipagp.ttf", MONO: "ipag.ttf"}
MARGIN = 20 * mm
CELL = 7 * mm        # マス目1つの大きさ
PER_ROW = 20         # マス目の1行の字数
QUESTION_TYPES = ("short", "essay", "choice", "calc")
CHOICE_LABELS = "アイウエオカ"  # 選択肢の記号。選択肢は2〜6個

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


class PrintError(Exception):
    """プリントを作れない理由を、利用者に見せる文で持つ。"""


# ---- フォント ----

def find_font(filename, font_dir=None):
    """フォントファイルの場所を返す。見つからなければ None。"""
    for d in ([font_dir] if font_dir else []) + FONT_DIRS:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            return path
    return None


def register_fonts(font_dir=None):
    for name, filename in FONT_FILES.items():
        path = find_font(filename, font_dir)
        if path is None:
            raise PrintError(
                f"フォント {filename} が見つかりません。"
                "IPAゴシックを入手して fonts/ に置くか、--font-dir で場所を指定してください。"
            )
        pdfmetrics.registerFont(TTFont(name, path))
    # reportlab の既定フォント（Helvetica）をPDFに入れない
    rl_config.canvas_basefontname = BODY


# ---- 入力の確認 ----

def _is_text(value):
    return isinstance(value, str) and bool(value.strip())


def _check_question(n, q, seen):
    """1問ぶんの問題点を文のリストで返す。"""
    if not isinstance(q, dict):
        return [f"{n}番目の問題が {{ }} の形になっていません"]
    errors = []
    qid = q.get("id")
    if _is_text(qid):
        label = qid
        if qid in seen:
            errors.append(f"問 {qid}: 番号が重なっています")
        seen.add(qid)
    else:
        label = f"{n}番目"
        errors.append(f'{n}番目の問題: 「id」がありません（文字で書く。例 "1"）')
    for key in ("text", "answer", "explanation"):
        if not _is_text(q.get(key)):
            errors.append(f"問 {label}: 「{key}」がありません")
    qtype = q.get("type")
    if qtype not in QUESTION_TYPES:
        errors.append(
            f"問 {label}: 「type」は short・essay・choice・calc のどれかにしてください（今の値: {qtype!r}）"
        )
    elif qtype == "choice":
        choices = q.get("choices")
        if (not isinstance(choices, list) or not 2 <= len(choices) <= len(CHOICE_LABELS)
                or not all(_is_text(c) for c in choices)):
            errors.append(
                f"問 {label}: 選択問題には選択肢（choices）が2〜{len(CHOICE_LABELS)}個必要です"
            )
        elif _is_text(q.get("answer")) and q["answer"] not in CHOICE_LABELS[:len(choices)]:
            errors.append(
                f"問 {label}: 選択問題の答えは記号で書いてください"
                f"（{CHOICE_LABELS[0]}〜{CHOICE_LABELS[len(choices) - 1]}。今の値: {q['answer']!r}）"
            )
    elif qtype == "essay":
        chars = q.get("chars")
        if not isinstance(chars, int) or isinstance(chars, bool) or chars <= 0:
            errors.append(f"問 {label}: 記述問題には字数（chars）が必要です")
        elif _is_text(q.get("answer")) and len(q["answer"]) > chars:
            errors.append(
                f"問 {label}: 模範解答が {len(q['answer'])} 字で、マス目の {chars} 字を超えています"
            )
    return errors


def validate(data):
    """入力の問題点を文のリストで返す。空なら問題なし。

    必須: title, trend, strategy, questions（各問は id, type, text, answer, explanation）
    型ごとに必要: essay は chars、choice は choices（答えは記号）
    任意: subject, scope
    """
    if not isinstance(data, dict):
        return ["全体が { } の形になっていません"]
    errors = []
    if not _is_text(data.get("title")):
        errors.append("「title」がありません")
    for key in ("trend", "strategy"):
        value = data.get(key)
        if not isinstance(value, list) or not value or not all(_is_text(x) for x in value):
            errors.append(f"「{key}」は1つ以上の文のリストにしてください")
    for key in ("subject", "scope"):
        if key in data and not isinstance(data[key], str):
            errors.append(f"「{key}」は文字で書いてください")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("「questions」は1問以上のリストにしてください")
        return errors
    seen = set()
    for n, q in enumerate(questions, 1):
        errors += _check_question(n, q, seen)
    return errors


# ---- 部品 ----

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


class WorkBox(Flowable):
    """計算問題用の、式と計算を書く欄。"""

    def __init__(self, width=A4[0] - 2 * MARGIN - 9 * mm, height=32 * mm):
        super().__init__()
        self.w, self.h = width, height

    def wrap(self, avail_w, avail_h):
        return self.w, self.h + 2 * mm

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.rect(0, 2 * mm, self.w, self.h)
        c.setFont(BODY, 8)
        c.drawString(1.5 * mm, self.h - 1.5 * mm, "式・計算")


def make_styles():
    base = dict(fontName=BODY, wordWrap="CJK")
    body = ParagraphStyle("body", fontSize=10.5, leading=17, **base)
    return {
        "title": ParagraphStyle("title", fontSize=16, leading=22, spaceAfter=2 * mm, **base),
        "meta": ParagraphStyle("meta", fontSize=9, leading=13, spaceAfter=4 * mm, **base),
        "head": ParagraphStyle("head", fontSize=13, leading=18, spaceBefore=5 * mm,
                               spaceAfter=2 * mm, **base),
        "body": body,
        "item": ParagraphStyle("item", parent=body, leftIndent=5 * mm, firstLineIndent=-5 * mm),
        "question": ParagraphStyle("question", parent=body, spaceBefore=4 * mm, spaceAfter=2 * mm,
                                   leftIndent=9 * mm, firstLineIndent=-9 * mm),
        "indent": ParagraphStyle("indent", parent=body, leftIndent=9 * mm),
    }


def para(text, style):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


# ---- 組み立て ----

def header_block(data, st):
    info = "　".join(x for x in (data.get("subject"), data.get("scope")) if x)
    name_line = "＿＿月＿＿日　／　名前＿＿＿＿＿＿＿＿＿＿"
    return [
        para(data["title"], st["title"]),
        para(f"{info}　／　{name_line}" if info else name_line, st["meta"]),
    ]


def bullet_section(heading, lines, st):
    return [para(heading, st["head"])] + [para(f"・{t}", st["item"]) for t in lines]


def answer_area(q, st):
    """問題の型ごとの、答えを書く所。"""
    if q["type"] == "essay":
        return [MasuGrid(q["chars"])]
    if q["type"] == "choice":
        options = [para(f"{CHOICE_LABELS[i]}　{c}", st["indent"]) for i, c in enumerate(q["choices"])]
        return options + [Spacer(1, 2 * mm), AnswerBox(width=30 * mm)]
    if q["type"] == "calc":
        return [WorkBox(), AnswerBox()]
    return [AnswerBox()]


def answer_text(q):
    """解答欄に載せる答え。選択問題は、記号に選択肢の文を添える。"""
    if q["type"] == "choice":
        return f"{q['answer']}（{q['choices'][CHOICE_LABELS.index(q['answer'])]}）"
    return q["answer"]


def question_section(questions, st):
    story = [para("3　問題", st["head"])]
    for q in questions:
        story.append(para(f"【{q['id']}】 {q['text']}", st["question"]))
        story += answer_area(q, st)
        story.append(Spacer(1, 2 * mm))
    return story


def answer_section(questions, st):
    story = [para("4　解答と解説", st["head"])]
    for q in questions:
        story.append(para(f"【{q['id']}】 答え：{answer_text(q)}", st["question"]))
        story.append(para(q["explanation"], st["indent"]))
    return story


def build_story(data):
    """並びの決まりはここだけで決める。"""
    st = make_styles()
    return (
        header_block(data, st)
        + bullet_section("1　傾向の解説", data["trend"], st)
        + bullet_section("2　対策", data["strategy"], st)
        + question_section(data["questions"], st)
        + [PageBreak()]
        + answer_section(data["questions"], st)
    )


def _page_number(canvas, doc):
    canvas.setFont(BODY, 8)
    canvas.drawCentredString(A4[0] / 2, 10 * mm, str(doc.page))


def build_pdf(data, out_path, font_dir=None):
    """確認 → フォント → PDF。問題があれば PrintError。"""
    errors = validate(data)
    if errors:
        raise PrintError("入力に問題があります:\n- " + "\n- ".join(errors))
    register_fonts(font_dir)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN, title=data["title"])
    doc.build(build_story(data), onFirstPage=_page_number, onLaterPages=_page_number)


def main(argv=None):
    ap = argparse.ArgumentParser(description="print.json から A4 の印刷用プリントを作る")
    ap.add_argument("input", help="print.json")
    ap.add_argument("output", help="出力する PDF")
    ap.add_argument("--font-dir", help="ipagp.ttf と ipag.ttf のあるフォルダ")
    args = ap.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        build_pdf(data, args.output, args.font_dir)
    except PrintError as e:
        sys.exit(str(e))
    except FileNotFoundError:
        sys.exit(f"ファイルが見つかりません: {args.input}")
    except json.JSONDecodeError as e:
        sys.exit(f"JSON として読めません: {args.input}（{e.lineno}行目）")
    print(f"作成しました: {args.output}（問題 {len(data['questions'])} 問）")


if __name__ == "__main__":
    main()
