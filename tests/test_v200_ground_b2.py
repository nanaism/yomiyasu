#!/usr/bin/env python3
"""B2: 資料との照合だけで、時間の単位と小数部が0だけの数をそろえる。"""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff
import yomiyasu_check


class GroundB2Test(unittest.TestCase):
    def numbers(self, final, material, original=None):
        result = yomiyasu_diff.ground(final, [material], original)
        return [item for item in result["items"] if item["kind"] == "number"]

    def test_equivalent_values_in_both_directions(self):
        pairs = [("1.0秒", "1秒"), ("3.00日", "3日"), ("0.00秒", "0秒"),
                 ("14.2s", "14.2秒"), ("200ms", "200ミリ秒"), ("5min", "5分"),
                 ("1.0", "1"), ("1.2.0", "1.2.0")]
        pairs.extend(("14.2" + unit, "14.2秒") for unit in ("sec", "secs"))
        pairs.extend(("200" + unit, "200ミリ秒") for unit in ("msec",))
        pairs.extend(("5" + unit, "5分") for unit in ("mins",))
        pairs.extend((("1.00secs", "1秒"), ("200.0msec", "200ミリ秒")))
        for left, right in pairs:
            for material, final in ((left, right), (right, left)):
                with self.subTest(material=material, final=final):
                    items = self.numbers("値は" + final + "です。", "値: " + material)
                    self.assertEqual([(i["text"], i["classification"]) for i in items],
                                     [(final, "from_materials")])

    def test_different_values_stay_different(self):
        for left, right in (("1.5", "15"), ("3時", "3分"), ("3.10", "3.1"),
                            ("0.50", "0.5"), ("3.10秒", "3.1秒"), ("0.50s", "0.5秒"),
                            ("1.2.0", "1.2"), ("1.0.0", "1"),
                            ("1S", "1秒"), ("1SEC", "1秒"), ("1MS", "1ミリ秒"),
                            ("1MIN", "1分"), ("1000ms", "1秒")):
            for material, final in ((left, right), (right, left)):
                with self.subTest(material=material, final=final):
                    items = self.numbers("値は" + final + "です。", "値: " + material)
                    self.assertEqual(items[0]["classification"], "not_in_sources")
                    self.assertTrue(any(i["classification"] == "not_in_final" for i in items))

    def test_r2b_numbers_do_not_support_units(self):
        cases = (("2026-10-01 02:00:01", "開始は2時です。"),
                 ("02:00:16", "処理には16秒かかりました。"),
                 ("request_id=job_13", "処理には13秒かかりました。"),
                 ("request_id=job-30", "保持期間は30日です。"),
                 ("# 1.2 までは 2", "処理には1.2秒かかりました。"),
                 ("version=1.2.0", "処理には1.2秒かかりました。"),
                 ("EXIT_ROLLBACK_FAILED = 4", "再試行は4回です。"),
                 ("RETRY_INTERVAL_SECONDS = 1.0", "間隔は1秒です。"),
                 ("+RETRY_INTERVAL_SECONDS = 0.5", "間隔は0.5秒です。"),
                 ("backup 212 files", "対象は212件です。"))
        for material, final in cases:
            with self.subTest(material=material):
                items = self.numbers(final, material)
                self.assertEqual(items[0]["classification"], "not_in_sources")

    def test_combined_log_and_restore_source(self):
        # G15 の時刻、ID、設定の取り違えを、ログとスクリプトを丸ごと渡す形で再現する合成例。
        log = "2026-10-01 02:00:01 backup 212 files\n2026-10-01 02:00:16 request_id=job_13\n"
        restore = ("RETRY_INTERVAL_SECONDS = 1.0\nEXIT_ROLLBACK_FAILED = 4\n"
                   "RETENTION_DAYS = 30\ndef restore():\n    return EXIT_ROLLBACK_FAILED\n")
        result = yomiyasu_diff.ground("間隔は1秒、再試行は4回、処理は13秒、保持期間は30日です。", [log, restore])
        self.assertEqual([i["text"] for i in result["items"]
                          if i["kind"] == "number" and i["classification"] == "not_in_sources"],
                         ["1秒", "4回", "13秒", "30日"])

    def test_spelling_and_source_classification_are_preserved(self):
        items = self.numbers("待ちは1.0secsです。", "上限は2秒。", "待ちは1秒です。")
        self.assertEqual((items[0]["text"], items[0]["value"], items[0]["unit"], items[0]["classification"]),
                         ("1.0secs", "1.0", "secs", "in_original"))
        items = self.numbers("間隔は200ミリ秒です。", "interval: 200ms")
        self.assertEqual((items[0]["text"], items[0]["value"], items[0]["unit"]),
                         ("200ミリ秒", "200", "ミリ秒"))

    def test_diff_still_reports_notation_changes(self):
        for before, after in (("待ちは1.0秒です。", "待ちは1秒です。"),
                              ("待ちは14.2sです。", "待ちは14.2秒です。")):
            with self.subTest(before=before):
                result = yomiyasu_diff.diff(before, after)
                self.assertTrue(any(r["kind"] == "number" for r in result["meaning_risks"]))

    def test_spaced_units_and_ranges_keep_their_context(self):
        for material, final in (("1.0 秒", "1秒"), ("1.0 secs", "1秒"),
                                ("200 msec", "200ミリ秒"), ("200 ミリ秒", "200ms"),
                                ("3.00〜5.00日", "3日から5日"), ("3〜5secs", "3秒から5秒")):
            for left, right in ((material, final), (final, material)):
                with self.subTest(material=left, final=right):
                    items = self.numbers("値は" + right + "です。", "値: " + left)
                    self.assertTrue(items)
                    self.assertTrue(all(i["classification"] == "from_materials" for i in items), items)

    def test_rewrite_basis_and_unsupported_count_follow_grounding(self):
        original = "間隔は100ミリ秒です。"
        for spelling in ("200ミリ秒", "200msec"):
            final = "間隔は" + spelling + "です。"
            risks = yomiyasu_diff.diff(original, final)["meaning_risks"]
            for material, basis, count in (("interval: 200ms", "material", 0), ("LIMIT = 200", "none", 1)):
                with self.subTest(spelling=spelling, material=material):
                    result = yomiyasu_diff.ground(final, [material], original)
                    linked = yomiyasu_check._with_basis(yomiyasu_diff, risks, result)
                    self.assertEqual([r.get("basis") for r in linked if r["kind"] == "number"], [basis])
                    self.assertEqual(yomiyasu_check._unsupported_count(result, linked, yomiyasu_diff), count)

    def test_check_cli_exit_codes_and_replay(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT), prefix=".b2-test-") as folder:
            root = Path(folder)
            material, final = root / "material.txt", root / "final.txt"
            material.write_bytes("elapsed=14.2s\ninterval: 200ms\n".encode("utf-8"))
            final.write_bytes("処理には14.2秒かかりました。間隔は200ミリ秒です。\n".encode("utf-8"))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            for key in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID"):
                env.pop(key, None)

            def run(*args):
                return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_check.py")] + list(args),
                                      cwd=str(root), env=env, capture_output=True, encoding="utf-8", timeout=60)

            for flags in ([], ["--fail-on=meaning-risk"]):
                result = run("run", "--material", str(material), "--final", str(final),
                             "--state-dir", str(root / "state"), "--json", *flags)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data["materials"]["meaning_risk_count"], 0)
            replay = run("verify", "--final", str(final), "--state-dir", str(root / "state"), "--replay")
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertIn("replay=ok", replay.stdout)
            material.write_bytes("RETRY_INTERVAL_SECONDS = 1.0\n".encode("utf-8"))
            final.write_bytes("間隔は1秒です。\n".encode("utf-8"))
            for flags, code in (([], 0), (["--fail-on=meaning-risk"], 1)):
                result = run("run", "--material", str(material), "--final", str(final), "--no-record", *flags)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)

    def test_unitless_value_is_not_hidden_by_supported_milliseconds(self):
        original = "設定は100です。間隔は100ミリ秒です。"
        final = "設定は200です。間隔は200ミリ秒です。"
        result = yomiyasu_diff.ground(final, ["interval: 200ms"], original)
        risks = yomiyasu_diff.diff(original, final)["meaning_risks"]
        linked = yomiyasu_check._with_basis(yomiyasu_diff, risks, result)
        self.assertTrue(any(r.get("basis") == "none" for r in linked))
        self.assertEqual(yomiyasu_check._unsupported_count(result, linked, yomiyasu_diff), 1)


if __name__ == "__main__":
    unittest.main()
