"""build_print.py のテスト。

リポジトリ直下で:
    python3 -m unittest discover -s skills/test-prep-print/tests -v

IPAゴシックが要るテスト（組み立てとPDF生成）は、フォントが見つからない環境では
飛ばす（失敗にはしない）。入力の確認とマス目の行数のテストは、フォントなしで動く。
各テストは自分でフォントを用意するので、実行の順番によらない。
"""
import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import build_print as bp  # noqa: E402

FONT_DIR = os.path.join(ROOT, "fonts")
HAVE_FONTS = all(bp.find_font(f, FONT_DIR) for f in bp.FONT_FILES.values())
NEED_FONTS = unittest.skipUnless(HAVE_FONTS, "IPAゴシックが見つからないので飛ばす")


def plain(flowable):
    """Paragraph の文字。reportlab が全角の空白を半角にするので、そろえて比べる。"""
    return flowable.getPlainText().replace("\u3000", " ")


def sample():
    with open(os.path.join(ROOT, "examples", "print.json"), encoding="utf-8") as f:
        return json.load(f)


class ValidateTest(unittest.TestCase):
    def errors_after(self, change):
        data = sample()
        change(data)
        return bp.validate(data)

    def assert_one_error(self, change, part):
        errors = self.errors_after(change)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(part, errors[0])

    def test_sample_is_valid(self):
        self.assertEqual(bp.validate(sample()), [])

    def test_subject_and_scope_are_optional(self):
        def change(d):
            del d["subject"], d["scope"]
        self.assertEqual(self.errors_after(change), [])

    def test_missing_id(self):
        self.assert_one_error(lambda d: d["questions"][0].pop("id"), "「id」がありません")

    def test_id_must_be_text(self):
        self.assert_one_error(lambda d: d["questions"][0].update(id=1), "「id」がありません")

    def test_missing_type(self):
        self.assert_one_error(lambda d: d["questions"][0].pop("type"), "「type」")

    def test_unknown_type(self):
        self.assert_one_error(lambda d: d["questions"][0].update(type="choice"), "「type」")

    def test_duplicate_id(self):
        self.assert_one_error(lambda d: d["questions"][1].update(id="1"), "番号が重なっています")

    def test_answer_longer_than_grid(self):
        self.assert_one_error(lambda d: d["questions"][3].update(chars=10), "超えています")

    def test_essay_needs_chars(self):
        self.assert_one_error(lambda d: d["questions"][3].pop("chars"), "字数")

    def test_chars_must_be_positive_int(self):
        for bad in (0, -5, "25", True, 2.5):
            with self.subTest(chars=bad):
                self.assert_one_error(lambda d: d["questions"][3].update(chars=bad), "字数")

    def test_missing_answer(self):
        self.assert_one_error(lambda d: d["questions"][2].pop("answer"), "「answer」")

    def test_blank_text_counts_as_missing(self):
        self.assert_one_error(lambda d: d["questions"][2].update(text="  "), "「text」")

    def test_empty_trend(self):
        self.assert_one_error(lambda d: d.update(trend=[]), "「trend」")

    def test_empty_questions(self):
        self.assert_one_error(lambda d: d.update(questions=[]), "「questions」")

    def test_not_an_object(self):
        self.assertEqual(len(bp.validate([])), 1)

    def test_all_problems_are_reported_together(self):
        def change(d):
            d["title"] = ""
            d["questions"][0].pop("type")
            d["questions"][3]["chars"] = 10
        self.assertEqual(len(self.errors_after(change)), 3)


class GridTest(unittest.TestCase):
    def test_grid_rows(self):
        for chars, rows in ((1, 1), (20, 1), (21, 2), (40, 2), (41, 3)):
            with self.subTest(chars=chars):
                self.assertEqual(bp.MasuGrid(chars).rows, rows)


@NEED_FONTS
class StoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bp.register_fonts(FONT_DIR)

    def test_order_is_fixed(self):
        story = bp.build_story(sample())
        heads = [plain(f) for f in story
                 if isinstance(f, bp.Paragraph) and f.style.name == "head"]
        self.assertEqual(heads, ["1 傾向の解説", "2 対策", "3 問題", "4 解答と解説"])

    def test_answers_start_on_new_page(self):
        story = bp.build_story(sample())
        breaks = [i for i, f in enumerate(story) if isinstance(f, bp.PageBreak)]
        self.assertEqual(len(breaks), 1)
        self.assertEqual(plain(story[breaks[0] + 1]), "4 解答と解説")

    def test_each_question_gets_its_answer_area(self):
        data = sample()
        story = bp.build_story(data)
        grids = [f.chars for f in story if isinstance(f, bp.MasuGrid)]
        boxes = [f for f in story if isinstance(f, bp.AnswerBox)]
        self.assertEqual(grids, [q["chars"] for q in data["questions"] if q["type"] == "essay"])
        self.assertEqual(len(boxes), sum(q["type"] == "short" for q in data["questions"]))


class BuildTest(unittest.TestCase):
    def test_invalid_input_makes_no_file(self):
        data = sample()
        data["questions"][3]["chars"] = 10
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.pdf")
            with self.assertRaises(bp.PrintError):
                bp.build_pdf(data, out, FONT_DIR)
            self.assertFalse(os.path.exists(out))

    def test_missing_font_is_reported(self):
        saved = bp.FONT_DIRS
        bp.FONT_DIRS = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(bp.PrintError) as cm:
                    bp.build_pdf(sample(), os.path.join(tmp, "x.pdf"), os.path.join(tmp, "none"))
            self.assertIn("フォント", str(cm.exception))
        finally:
            bp.FONT_DIRS = saved

    @NEED_FONTS
    def test_builds_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sub", "print.pdf")
            bp.build_pdf(copy.deepcopy(sample()), out, FONT_DIR)
            with open(out, "rb") as f:
                raw = f.read()
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertNotIn(b"Helvetica", raw)
        self.assertNotIn(b"Noto", raw)


if __name__ == "__main__":
    unittest.main()
