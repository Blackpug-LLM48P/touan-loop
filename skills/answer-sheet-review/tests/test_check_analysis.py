"""check_analysis.py のテスト。

リポジトリ直下で:
    python3 -m unittest discover -s skills/answer-sheet-review/tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import check_analysis as ca  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "analysis.json")


def sample():
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def results(data):
    return [r for _, r, _ in ca.score_checks(data)]


class SampleTest(unittest.TestCase):
    def test_sample_has_no_problems(self):
        data = sample()
        self.assertEqual(ca.shape_errors(data), [])
        self.assertEqual(results(data), [ca.MATCH] * 3)
        self.assertEqual(ca.rule_errors(data), [])


class ShapeTest(unittest.TestCase):
    def test_not_an_object(self):
        self.assertEqual(len(ca.shape_errors([])), 1)

    def test_empty_questions(self):
        self.assertEqual(len(ca.shape_errors({"questions": []})), 1)

    def test_unknown_read_status(self):
        data = sample()
        data["questions"][0]["read"]["status"] = "guessed"
        self.assertIn("read.status", ca.shape_errors(data)[0])

    def test_unknown_cause_status_and_tag(self):
        data = sample()
        data["questions"][1]["cause"]["status"] = "sure"
        data["questions"][2]["cause"]["tag"] = "careless"
        errors = ca.shape_errors(data)
        self.assertEqual(len(errors), 2)
        self.assertIn("cause.status", errors[0])
        self.assertIn("cause.tag", errors[1])


class ScoreTest(unittest.TestCase):
    def test_duplicate_question(self):
        data = sample()
        data["questions"][1]["q"] = data["questions"][0]["q"]
        self.assertEqual(results(data)[0], ca.MISMATCH)

    def test_max_sum_differs_from_total(self):
        data = sample()
        data["total"]["max"] = 25
        self.assertEqual(results(data), [ca.MISMATCH, ca.MATCH, ca.MATCH])

    def test_got_out_of_range(self):
        data = sample()
        data["questions"][0]["score"]["got"] = 3
        self.assertEqual(results(data)[1], ca.MISMATCH)

    def test_got_sum_differs_from_total(self):
        data = sample()
        data["total"]["got"] = 11
        checks = ca.score_checks(data)
        self.assertEqual(checks[2][1], ca.MISMATCH)
        self.assertIn("+2", checks[2][2])

    def test_missing_total_is_unknown_not_mismatch(self):
        data = sample()
        del data["total"]
        self.assertEqual(results(data), [ca.UNKNOWN, ca.MATCH, ca.UNKNOWN])

    def test_missing_question_score_is_unknown(self):
        data = sample()
        data["questions"][0]["score"]["got"] = None
        self.assertEqual(results(data), [ca.MATCH, ca.UNKNOWN, ca.UNKNOWN])

    def test_true_is_not_a_number(self):
        data = sample()
        data["questions"][0]["score"]["got"] = True
        self.assertEqual(results(data)[1], ca.UNKNOWN)


class RuleTest(unittest.TestCase):
    def one_error(self, change, part):
        data = sample()
        change(data["questions"])
        errors = ca.rule_errors(data)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(part, errors[0])

    def test_unreadable_cannot_be_confirmed(self):
        for status in ca.SETTLED:
            self.one_error(lambda qs, s=status: qs[5].update(
                cause={"status": s, "tag": "concept", "text": "理由が足りない"}), "確定にできません")

    def test_unreadable_has_no_text(self):
        self.one_error(lambda qs: qs[5]["read"].update(text="しずむ"), "答えの文字が書かれています")

    def test_read_needs_text(self):
        self.one_error(lambda qs: qs[1]["read"].update(text=None), "答えの文字がありません")

    def test_full_marks_has_no_cause(self):
        self.one_error(lambda qs: qs[0].update(
            cause={"status": "hypothesis", "tag": None, "text": None}), "満点")

    def test_lost_points_need_a_cause(self):
        self.one_error(lambda qs: qs[1].update(cause=None), "cause がありません")

    def test_confirmed_needs_text(self):
        self.one_error(lambda qs: qs[1]["cause"].update(text=""), "根拠")

    def test_confirmed_needs_tag(self):
        self.one_error(lambda qs: qs[1]["cause"].update(tag=None), "タグ")

    def test_parent_confirmed_is_accepted(self):
        data = sample()
        q = data["questions"][5]
        q["read"] = {"status": "parent_confirmed", "text": "しずむ"}
        q["cause"] = {"status": "parent_confirmed", "tag": "condition", "text": "本人に聞いた：理由を書き忘れた"}
        self.assertEqual(ca.rule_errors(data), [])


class TagTest(unittest.TestCase):
    def test_counts_settled_causes_only(self):
        data = sample()
        data["questions"][1]["cause"]["status"] = "hypothesis"
        self.assertEqual(ca.tag_counts(data), {"procedure": 1, "keyword": 1})

    def test_repeated_tags(self):
        per_file = [("a", {"condition": 2, "keyword": 1}), ("b", {"condition": 1}), ("c", {"kanji": 1})]
        self.assertEqual(ca.repeated_tags(per_file), ["condition"])


class MainTest(unittest.TestCase):
    def run_main(self, *datas):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, data in enumerate(datas):
                path = os.path.join(d, f"{i}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                paths.append(path)
            before = [read_text(p) for p in paths]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ca.main(paths)
            self.assertEqual(before, [read_text(p) for p in paths])
        return code, out.getvalue()

    def test_sample_exits_0_and_lists_open_items(self):
        code, out = self.run_main(sample())
        self.assertEqual(code, 0)
        self.assertIn("親に確かめてほしい問: 2(3)", out)

    def test_mismatch_exits_1(self):
        data = sample()
        data["total"]["got"] = 10
        code, out = self.run_main(data)
        self.assertEqual(code, 1)
        self.assertIn(ca.MISMATCH, out)

    def test_unknown_alone_does_not_fail(self):
        data = sample()
        del data["total"]
        self.assertEqual(self.run_main(data)[0], 0)

    def test_shape_error_exits_1(self):
        self.assertEqual(self.run_main({"questions": []})[0], 1)

    def test_two_files_show_repeated_tags(self):
        code, out = self.run_main(sample(), sample())
        self.assertEqual(code, 0)
        self.assertIn("2回以上出てきたタグ: keyword、condition、procedure", out)

    def test_missing_file_exits_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ca.main(["/nonexistent/analysis.json"]), 2)


if __name__ == "__main__":
    unittest.main()
