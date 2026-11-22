#!/usr/bin/env python3
"""v3.3.0: diff の、入れ子の文で主語の役が入れ替わった推敲（kind swap、subkind nested）の試験。

「部長が新人が会議で発言することをやめさせた」を「部長が会議で発言することを新人がやめさせた」にすると、やめさせた人が
部長から新人に変わる。どちらの文でも 部長 と 新人 に付く助詞は が のままなので、語ごとの助詞を比べる swap では拾えなかった。
3.3.0 からは「こと」「の」「よう」でまとめた節が1つだけの文で、語ごとに外の文の主語（outer）か中の節の主語（inner）かを決め、
outer から inner になった語と inner から outer になった語がどちらもあれば出す。--fail-on=meaning-risk には swap として数える。
文はすべて合成の文。
"""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


def run(before, after):
    return yomiyasu_diff.diff(before + "\n", after + "\n")


def swaps(result):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == "swap"]


def nested_pairs(*changes):
    """(語, 元の役, 後の役) の並びを detail の pairs の形にする。"""
    return [{"word": word, "old": old, "new": new} for word, old, new in changes]


SWAPPED = (("outer", "inner"), ("inner", "outer"))

# 出す組（入れ子の主語の入れ替え）: (元, 後, 外から中になった語, 中から外になった語)
NESTED = [
    ("部長が新人が会議で発言することをやめさせた。", "部長が会議で発言することを新人がやめさせた。", "部長", "新人"),
    ("課長が佐藤さんが資料を作ることを許した。", "課長が資料を作ることを佐藤さんが許した。", "課長", "佐藤"),
    ("校長が田中が早く帰るよう求めた。", "校長が早く帰るよう田中が求めた。", "校長", "田中"),
    ("店長がアルバイトが休憩するのを許した。", "店長が休憩するのをアルバイトが許した。", "店長", "アルバイト"),
    # 丁寧語から常体にしたうえでの入れ替え
    ("部長が新人が会議で発言することをやめさせました。", "部長が会議で発言することを新人がやめさせた。", "部長", "新人"),
    # 読点のある文
    ("部長が、新人が会議で発言することを、やめさせた。", "部長が会議で発言することを、新人がやめさせた。", "部長", "新人"),
    ("営業部が開発部が仕様を変えることを認めた。", "営業部が仕様を変えることを開発部が認めた。", "営業部", "開発部"),
    # 節の中に「に」の語がある文
    ("監督が選手が試合に出ることを決めた。", "監督が試合に出ることを選手が決めた。", "監督", "選手"),
    ("田中さんが鈴木さんが参加することに反対した。", "田中さんが参加することに鈴木さんが反対した。", "田中", "鈴木"),
    ("委員会が事務局が案を出すのを待っています。", "委員会が案を出すのを事務局が待っている。", "委員会", "事務局"),
    ("部長が新人が会議で発言するように促した。", "部長が会議で発言するように新人が促した。", "部長", "新人"),
    # issue #68 の形
    ("主語１が主語２がＡＡＡすることをやめさせる。", "主語１がＡＡＡすることを主語２がやめさせる。", "主語１", "主語２"),
    # 節の前の2語を入れ替えた形
    ("部長が新人が会議で発言することをやめさせた。", "新人が部長が会議で発言することをやめさせた。", "部長", "新人"),
    # 敬語に変えたうえでの入れ替え
    ("部長が新人が会議で発言することをやめさせた。", "部長が会議で発言することを新人がおやめになった。", "部長", "新人"),
    # 人称の語
    ("彼女が彼が会議で発言することを止めた。", "彼女が会議で発言することを彼が止めた。", "彼女", "彼"),
]

# 語に付く助詞も入れ替わるので、今までの swap（subkind なし）が拾う組。nested は重ねて出さない: (元, 後, detail の pairs)
PLAIN = [
    ("部長は、新人が会議で発言するのを止めた。", "会議で部長が発言するのを新人は止めた。",
     nested_pairs(("部長", "は", "が"), ("新人", "が", "は"))),
    ("部長が新人に会議で発言することをやめさせた。", "部長に会議で発言することを新人がやめさせた。",
     nested_pairs(("部長", "が", "に"), ("新人", "に", "が"))),
    ("母は娘が一人で旅行することを許さなかった。", "母が一人で旅行することを娘は許さなかった。",
     nested_pairs(("母", "は", "が"), ("娘", "が", "は"))),
    # 受け身の文で は と に を入れ替えた形
    ("新人は会議で発言することを部長にやめさせられた。", "部長は会議で発言することを新人にやめさせられた。",
     nested_pairs(("新人", "は", "に"), ("部長", "に", "は"))),
    # 入れ子でない単純な入れ替え
    ("部長が新人を止めた。", "新人が部長を止めた。", nested_pairs(("部長", "が", "を"), ("新人", "を", "が"))),
]

# 出さない組（正しい並べ替えと、範囲の外の言い換え）: (元, 後, 理由)
NOT_FOUND = [
    ("部長が新人が会議で発言することをやめさせた。", "新人が会議で発言することを部長がやめさせた。", "issue の正しい並べ替え"),
    ("部長が新人が会議で発言することをやめさせた。", "新人に会議で発言することを部長がやめさせた。", "が を に にした"),
    ("部長が新人が会議で発言することをやめさせた。", "部長は、新人が会議で発言するのをやめさせた。", "は の主題と の"),
    ("部長が新人が会議で発言することをやめさせた。", "部長は新人に会議で発言しないよう求めた。", "言い換え（範囲の外）"),
    ("課長が佐藤さんが資料を作ることを許した。", "佐藤さんが資料を作ることを課長が許しました。", "常体から丁寧語"),
    ("部長が、新人が会議で発言することをやめさせた。", "新人が会議で発言することを、部長がやめさせた。", "読点の位置"),
    ("校長が田中が早く帰るよう求めた。", "田中が早く帰るよう、校長が求めた。", "よう"),
    ("店長がアルバイトが休憩するのを許した。", "アルバイトが休憩するのを店長は許した。", "の を と は"),
    ("営業部が開発部が仕様を変えることを認めた。", "開発部が仕様を変えることを営業部は認めました。", "丁寧語"),
    ("母は娘が一人で旅行することを許さなかった。", "娘が一人で旅行することを、母は許さなかった。", "は の主題を後ろへ"),
    ("田中さんが鈴木さんが参加することに反対した。", "鈴木さんが参加することに田中さんが反対した。", "ことに"),
    ("委員会が事務局が案を出すのを待っています。", "事務局が案を出すのを委員会が待っている。", "の を と常体"),
    ("主語１が主語２がＡＡＡすることをやめさせる。", "主語２がＡＡＡすることを主語１がやめさせる。", "issue #68 の形の正しい並べ替え"),
    ("部長は、新人が会議で発言することを、やめさせた。", "部長は新人が会議で発言することをやめさせた。", "読点を取っただけ"),
    ("監督が選手が試合に出ることを決めた。", "選手が試合に出ることは、監督が決めた。", "ことは"),
    ("部長が新人に会議で発言することをやめさせた。", "新人が会議で発言するのを部長がやめさせた。", "に から が と の"),
    ("部長が新人が会議で発言することをやめさせた。", "部長が会議で新人が発言することをやめさせた。", "語順だけ"),
    ("部長が新人が会議で発言することをやめさせた。", "部長が、新人の会議での発言をやめさせた。", "名詞句にした"),
]

# 見ない形（限界）。役が入れ替わっていても出ない: (元, 後, 理由)
MISSED = [
    ("部長が新人が会議で発言することをやめさせ、記録に残すことにした。",
     "部長が会議で発言することを新人がやめさせ、記録に残すことにした。", "名詞化の語が2つある文"),
    ("部長が新人が会議で発言することをやめさせた。", "新人がやめさせた。", "片方の語が消えた"),
]


class NestedSwapTest(unittest.TestCase):
    def test_nested_found(self):
        for before, after, outer, inner in NESTED:
            with self.subTest(before=before, after=after):
                found = swaps(run(before, after))
                self.assertEqual(len(found), 1, found)
                risk = found[0]
                self.assertEqual((risk["kind"], risk["subkind"]), ("swap", "nested"))
                self.assertEqual((risk["old"], risk["new"], risk["old_line"], risk["new_line"]), (before, after, 1, 1))
                self.assertEqual(risk["detail"], {"pairs": nested_pairs((outer,) + SWAPPED[0], (inner,) + SWAPPED[1])})
                self.assertIsNone(risk["basis"])

    def test_plain_swap_is_not_doubled(self):
        """語に付く助詞も入れ替わる組は、今までの swap が1件だけ出す。"""
        for before, after, pairs in PLAIN:
            with self.subTest(before=before, after=after):
                found = swaps(run(before, after))
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in found], [(None, {"pairs": pairs})])

    def test_not_found(self):
        for before, after, reason in NOT_FOUND:
            with self.subTest(reason=reason, before=before, after=after):
                self.assertEqual(swaps(run(before, after)), [])

    def test_known_misses(self):
        for before, after, reason in MISSED:
            with self.subTest(reason=reason, before=before, after=after):
                self.assertEqual(swaps(run(before, after)), [])

    def test_one_way_change_is_quiet(self):
        """役が変わった語が1つだけの組は出さない（主語を足した、もう一人を消した）。"""
        for before, after in (
            ("全件が保存先に届いたことを確かめました。", "私が全件が保存先に届いたことを確かめました。"),
            ("部長が新人が発言することを止めた。", "部長が発言することを止めた。"),
        ):
            with self.subTest(before=before, after=after):
                old, new = yomiyasu_diff._nest_roles(before), yomiyasu_diff._nest_roles(after)
                changed = [word for word in old if word in new and old[word] != new[word]]
                self.assertEqual(len(changed), 1, (old, new))
                self.assertEqual(swaps(run(before, after)), [])

    def test_message(self):
        result = run(*NESTED[0][:2])
        self.assertEqual(yomiyasu_diff._risk_line(result["meaning_risks"][0]),
                         "主語の役が入れ替わった（1行目）: 部長 外の文の主語→中の節の主語、新人 中の節の主語→外の文の主語")

    def test_fail_on_counts_nested(self):
        """kind は swap のままなので、FAIL_ON_KINDS と _RISK_ORDER を変えずに --fail-on に数える。"""
        self.assertIn("swap", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertNotIn("nested", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["swap"], 2)
        result = run(*NESTED[0][:2])
        self.assertEqual(result["meaning_risk_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(yomiyasu_diff.fail_on_count(result["meaning_risks"]), 1)

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


class NestedSwapCliTest(unittest.TestCase):
    def cli(self, before, after, *args):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "a.md").write_bytes((before + "\n").encode("utf-8"))
            Path(folder, "b.md").write_bytes((after + "\n").encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                                      *args, "a.md", "b.md"], capture_output=True,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), cwd=folder)
        return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")

    def test_exit_code_and_text(self):
        code, out, err = self.cli(*NESTED[0][:2])
        self.assertEqual(code, 1, err)
        self.assertIn("- 主語の役が入れ替わった（1行目）: 部長 外の文の主語→中の節の主語、新人 中の節の主語→外の文の主語\n", out)
        self.assertIn("終了コード1: --fail-on=meaning-risk の条件に当たりました（意味が変わる恐れ 1件）。", out)
        code, out, err = self.cli(*NOT_FOUND[0][:2])
        self.assertEqual(code, 0, err)

    def test_json_format_is_unchanged(self):
        """JSON の版と、上の段と意味が変わる恐れのキーは、nested が出ても出なくても同じ。"""
        code, out, err = self.cli(*NESTED[0][:2], "--json")
        self.assertEqual(code, 1, err)
        found = json.loads(out)
        code, out, err = self.cli(*NOT_FOUND[0][:2], "--json")
        self.assertEqual(code, 0, err)
        quiet = json.loads(out)
        self.assertEqual((found["format"], found["format_version"]), ("yomiyasu-diff", 2))
        self.assertEqual(yomiyasu_diff.DIFF_FORMAT_VERSION, 2)
        self.assertEqual(list(found), list(quiet))
        self.assertEqual(found["fail_on_meaning_risk_count"], 1)
        risk, = found["meaning_risks"]
        self.assertEqual(list(risk), ["kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"])
        self.assertEqual((risk["kind"], risk["subkind"]), ("swap", "nested"))
        self.assertEqual(risk["detail"], {"pairs": nested_pairs(("部長",) + SWAPPED[0], ("新人",) + SWAPPED[1])})


if __name__ == "__main__":
    unittest.main()
