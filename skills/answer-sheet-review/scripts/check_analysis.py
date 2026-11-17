#!/usr/bin/env python3
"""analysis.json を確かめる。読むだけで、ファイルは書きかえない。

使い方:
    python3 check_analysis.py data/2026-11-rika/analysis.json
    python3 check_analysis.py data/2026-07-rika/analysis.json data/2026-11-rika/analysis.json

確かめること:
    1. 形（必須の項目、status と tag の値）
    2. 点数の照合 3つ（結果は「一致／合わない／確かめられない」）
       - 問の重なりがないか、配点の合計が満点と同じか
       - 各問で 0 ≦ got ≦ max か
       - 各問の got の合計が、答案の点数と同じか
    3. 記録の決まり（読めなかった問の原因を確定にしていないか、など）
    ファイルを2つ以上渡すと、原因のタグを回ごとに数えて並べる。

確かめないこと:
    読み取りや採点、原因が正しいかどうか。それは親が答案と見くらべる。

終了コード: 問題なし 0／「合わない」か決まりに外れた所がある 1／ファイルが読めない 2
"""
import argparse
import json
import sys

READ_STATUS = ("read", "unreadable", "parent_confirmed")
CAUSE_STATUS = ("confirmed", "parent_confirmed", "hypothesis", "unknown")
SETTLED = ("confirmed", "parent_confirmed")  # 出題の根拠にしてよい原因
TAGS = ("keyword", "question_form", "condition", "blank", "kanji", "procedure", "concept")

MATCH, MISMATCH, UNKNOWN = "一致", "合わない", "確かめられない"


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_text(v):
    return isinstance(v, str) and bool(v.strip())


def _score(q):
    """(max, got)。数でないものは None。"""
    s = q.get("score") if isinstance(q, dict) else None
    if not isinstance(s, dict):
        return None, None
    return (s.get("max") if _is_number(s.get("max")) else None,
            s.get("got") if _is_number(s.get("got")) else None)


def shape_errors(data):
    """形の問題点を文のリストで返す。"""
    if not isinstance(data, dict):
        return ["全体が { } の形になっていません"]
    errors = []
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        return ["「questions」は1問以上のリストにしてください"]
    for n, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            errors.append(f"{n}番目の問が {{ }} の形になっていません")
            continue
        label = q.get("q") if _is_text(q.get("q")) else f"{n}番目"
        if not _is_text(q.get("q")):
            errors.append(f'{n}番目の問: 「q」（問の番号）がありません')
        read = q.get("read")
        if not isinstance(read, dict) or read.get("status") not in READ_STATUS:
            errors.append(f"問 {label}: 「read.status」は {'・'.join(READ_STATUS)} のどれかにしてください")
        if not isinstance(q.get("score"), dict):
            errors.append(f"問 {label}: 「score」がありません")
        cause = q.get("cause")
        if cause is not None:
            if not isinstance(cause, dict) or cause.get("status") not in CAUSE_STATUS:
                errors.append(f"問 {label}: 「cause.status」は {'・'.join(CAUSE_STATUS)} のどれかにしてください")
            elif cause.get("tag") is not None and cause.get("tag") not in TAGS:
                errors.append(f"問 {label}: 「cause.tag」の値が決まりにありません（今の値: {cause.get('tag')!r}）")
    return errors


def score_checks(data):
    """点数の照合。[(名前, 結果, 説明)] を返す。"""
    questions = [q for q in data.get("questions", []) if isinstance(q, dict)]
    scores = [_score(q) for q in questions]
    total = data.get("total") if isinstance(data.get("total"), dict) else {}
    total_max = total.get("max") if _is_number(total.get("max")) else None
    total_got = total.get("got") if _is_number(total.get("got")) else None
    results = []

    # 1. 重なりと抜け
    ids = [q.get("q") for q in questions if _is_text(q.get("q"))]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        results.append(("問の重なり・抜け", MISMATCH, f"番号が重なっています: {'、'.join(dup)}"))
    elif total_max is None or any(m is None for m, _ in scores):
        results.append(("問の重なり・抜け", UNKNOWN,
                        "重なりはありません。満点か配点に書かれていないものがあり、抜けは確かめられません"))
    else:
        sum_max = sum(m for m, _ in scores)
        if sum_max == total_max:
            results.append(("問の重なり・抜け", MATCH, f"重なりなし。配点の合計 {sum_max:g} ＝ 満点 {total_max:g}"))
        else:
            results.append(("問の重なり・抜け", MISMATCH,
                            f"配点の合計 {sum_max:g} と満点 {total_max:g} が合いません（問の抜けか、配点の読み違い）"))

    # 2. 各問の範囲
    bad, missing = [], []
    for q, (m, g) in zip(questions, scores):
        label = q.get("q") if _is_text(q.get("q")) else "?"
        if m is None or g is None:
            missing.append(label)
        elif not 0 <= g <= m:
            bad.append(f"{label}（{g:g}／{m:g}）")
    if bad:
        results.append(("各問の点数の範囲", MISMATCH, f"0 ≦ got ≦ max に入っていません: {'、'.join(bad)}"))
    elif missing:
        results.append(("各問の点数の範囲", UNKNOWN, f"点数が書かれていない問があります: {'、'.join(missing)}"))
    else:
        results.append(("各問の点数の範囲", MATCH, f"{len(questions)}問すべて 0 ≦ got ≦ max"))

    # 3. 合計
    if total_got is None or any(g is None for _, g in scores):
        results.append(("得点の合計", UNKNOWN, "答案の点数か、各問の点数に書かれていないものがあります"))
    else:
        sum_got = sum(g for _, g in scores)
        if sum_got == total_got:
            results.append(("得点の合計", MATCH, f"各問の合計 {sum_got:g} ＝ 答案の点数 {total_got:g}"))
        else:
            results.append(("得点の合計", MISMATCH,
                            f"各問の合計 {sum_got:g} と答案の点数 {total_got:g} が合いません（差 {total_got - sum_got:+g}）"))
    return results


def rule_errors(data):
    """記録の決まりに外れた所を文のリストで返す。"""
    errors = []
    for q in data.get("questions", []):
        if not isinstance(q, dict):
            continue
        label = q.get("q") if _is_text(q.get("q")) else "?"
        read = q.get("read") if isinstance(q.get("read"), dict) else {}
        cause = q.get("cause")
        m, g = _score(q)
        full = m is not None and g is not None and g == m
        if read.get("status") == "unreadable" and _is_text(read.get("text")):
            errors.append(f"問 {label}: 読めなかった問に、答えの文字が書かれています")
        if read.get("status") in ("read", "parent_confirmed") and not _is_text(read.get("text")):
            errors.append(f"問 {label}: 読めた問に、答えの文字がありません（空欄なら「空欄」と書く）")
        if full and cause is not None:
            errors.append(f"問 {label}: 満点の問は cause を null にします")
        if not isinstance(cause, dict):
            if cause is None and m is not None and g is not None and g < m:
                errors.append(f"問 {label}: 失点があるのに cause がありません（分からなければ status を unknown に）")
            continue
        status = cause.get("status")
        if read.get("status") == "unreadable" and status in SETTLED:
            errors.append(f"問 {label}: 答えが読めなかった問の原因は、確定にできません")
        if status in SETTLED and not _is_text(cause.get("text")):
            errors.append(f"問 {label}: 確定した原因には、根拠（cause.text）が必要です")
        if status in SETTLED and cause.get("tag") is None:
            errors.append(f"問 {label}: 確定した原因には、タグ（cause.tag）が必要です")
    return errors


def tag_counts(data):
    """確定した原因（confirmed・parent_confirmed）のタグごとの問数。"""
    counts = {}
    for q in data.get("questions", []):
        cause = q.get("cause") if isinstance(q, dict) else None
        if isinstance(cause, dict) and cause.get("status") in SETTLED and cause.get("tag") in TAGS:
            counts[cause["tag"]] = counts.get(cause["tag"], 0) + 1
    return counts


def repeated_tags(per_file):
    """2回以上の回に出てきたタグ。per_file は [(名前, tag_counts)]。"""
    seen = {}
    for _, counts in per_file:
        for tag in counts:
            seen[tag] = seen.get(tag, 0) + 1
    return [t for t in TAGS if seen.get(t, 0) >= 2]


def report(path, data):
    """1ファイルぶんを表示し、問題があれば True を返す。"""
    print(f"■ {path}")
    shape = shape_errors(data)
    if shape:
        print("  形に問題があります（照合はしていません）:")
        for e in shape:
            print(f"  - {e}")
        return True
    failed = False
    print("  点数の照合:")
    for name, result, detail in score_checks(data):
        failed |= result == MISMATCH
        print(f"  - {name}: {result}（{detail}）")
    rules = rule_errors(data)
    if rules:
        failed = True
        print("  記録の決まりに外れた所:")
        for e in rules:
            print(f"  - {e}")
    else:
        print("  記録の決まり: 外れた所なし")
    open_items = [q["q"] for q in data["questions"]
                  if q["read"]["status"] == "unreadable"
                  or (isinstance(q.get("cause"), dict) and q["cause"]["status"] in ("hypothesis", "unknown"))]
    print(f"  親に確かめてほしい問: {'、'.join(open_items) if open_items else 'なし'}")
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description="analysis.json を確かめる（読むだけ）")
    ap.add_argument("files", nargs="+", help="analysis.json（古い回から順に、いくつでも）")
    args = ap.parse_args(argv)

    loaded = []
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as f:
                loaded.append((path, json.load(f)))
        except FileNotFoundError:
            print(f"ファイルが見つかりません: {path}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as e:
            print(f"JSON として読めません: {path}（{e.lineno}行目）", file=sys.stderr)
            return 2

    failed = False
    for path, data in loaded:
        failed |= report(path, data)
        print()

    usable = [(p, tag_counts(d)) for p, d in loaded if not shape_errors(d)]
    if len(usable) >= 2:
        print("■ 原因のタグ（確定したものだけ。問の数）")
        for path, counts in usable:
            line = "、".join(f"{t} {counts[t]}" for t in TAGS if t in counts) or "なし"
            print(f"  {path}: {line}")
        again = repeated_tags(usable)
        print(f"  2回以上出てきたタグ: {'、'.join(again) if again else 'なし'}")
        print("  ※ タグの付け方は回ごとにぶれます。傾向として言う前に、親が答案で確かめてください。")
        print()

    print("ここで確かめたのは、形・点数の足し算・記録の決まりだけです。読み取りと原因が正しいかは確かめていません。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
