"""3.0.0: flag.txt の使う語と、linked worktree から元の checkout の語の一覧を読む動作。

文と git リポジトリは合成のもの。一覧は一時フォルダの中だけに作る。
"""
from pathlib import Path
import json
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v220_c import CHECK, WORD_KEYS, FolderCase, run, write  # noqa: E402
import yomiyasu_lint  # noqa: E402


class FlagReplacementTest(FolderCase):
    def test_replacements_preserve_plain_and_pattern_findings(self) -> None:
        folder = self.words(flag="指紋\tfingerprint\n承認\n", allow="")
        write(folder / "flag-patterns.txt", "指紋\t照合\n")
        doc = write(self.root / "doc.md", "指紋を照合します。\n承認を待ちます。\nfingerprint を照合します。\n")
        found = [f for f in self.lint_json(str(doc))["findings"] if f["rule"] == "project_term"]
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([f["message"] for f in found], [
            "語の一覧（flag.txt、flag-patterns.txt）の語（指紋）" + tail + "使う語: 指紋 → fingerprint。",
            "語の一覧（flag.txt）の語（承認）" + tail,
            "語の一覧（flag-patterns.txt）の語（指紋）" + tail,
        ])
        # allow.txt で同じ行の一部だけ外しても、残した語の使う語を出す。
        write(folder / "flag-patterns.txt", "branch\t枝\n")
        doc = write(doc, "指紋と承認と枝を確認します。\n")
        for allowed, message in (
            ("承認\n", "語の一覧（flag.txt、flag-patterns.txt）の語（指紋、branch）" + tail + "使う語: 指紋 → fingerprint。"),
            ("指紋\n", "語の一覧（flag.txt、flag-patterns.txt）の語（承認、branch）" + tail),
        ):
            with self.subTest(allow=allowed):
                write(folder / "allow.txt", allowed)
                found = [f for f in self.lint_json(str(doc))["findings"] if f["rule"] == "project_term"]
                self.assertEqual([f["message"] for f in found], [message])

    def test_check_shows_replacement_without_changing_record_keys(self) -> None:
        folder = self.words(flag="指紋\tfingerprint\n")
        write(folder / "flag-patterns.txt", "branch\t枝\n")
        doc = write(self.root / "doc.md", "指紋を照合します。\n枝を見ます。\n")
        source = write(self.root / "source.md", "指紋を照合します。\n枝を確認します。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("- 指紋（語の一覧。L1。使う語: fingerprint）", process.stdout)
        self.assertIn("- branch（語の一覧。L2）", process.stdout)
        record_path, = (self.root / ".yomiyasu" / "runs").glob("*/attempt-1.json")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(list(record["options"]["words"]), WORD_KEYS + ["flag_patterns_lines", "flag_patterns_sha256"])
        process = run([CHECK, "verify", "--final", doc, "--replay"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("replay=ok", process.stdout)
        # flag.txt の語と同じ名前のパターンだけが当たるときは、使う語を添えない。
        write(folder / "flag-patterns.txt", "指紋\t照合\n")
        write(doc, "照合します。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("- 指紋（語の一覧。L1）", process.stdout)
        self.assertNotIn("使う語:", process.stdout)

    def test_linked_worktree_uses_original_checkout_words(self) -> None:
        local_names = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True,
                                     text=True, encoding="utf-8", check=True).stdout.splitlines()
        for name in local_names:
            self.env.pop(name, None)
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env["GIT_CONFIG_GLOBAL"] = str(self.root / "no-global-config")
        repo = self.root / "checkout"
        repo.mkdir()
        commands = (
            ["init", "--quiet"],
            ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet",
             "--allow-empty", "--no-gpg-sign", "-m", "Initial fixture"],
            ["worktree", "add", "--quiet", "--detach", str(self.root / "linked-worktree")],
        )
        for command in commands:
            subprocess.run(["git", "-c", "core.hooksPath=" + str(self.root / "no-hooks")] + command,
                           cwd=repo, env=self.env, capture_output=True, text=True, encoding="utf-8", check=True)
        self.words(repo / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        nested = self.root / "linked-worktree" / "docs"
        doc = write(nested / "doc.md", "指紋を照合します。\n")
        result = self.lint_json(str(doc), cwd=nested)
        found = [f for f in result["findings"] if f["rule"] == "project_term"]
        self.assertEqual(len(found), 1)
        self.assertIn("指紋 → fingerprint", found[0]["message"])
        self.assertEqual(result["context"]["words"]["path"], str(repo / ".yomiyasu-words"))
        # worktree 自身に一覧があれば、そちらを使う（元の checkout とは混ぜない）。
        self.words(nested.parent / ".yomiyasu-words", flag="承認\n")
        result = self.lint_json(str(doc), cwd=nested)
        self.assertEqual([f for f in result["findings"] if f["rule"] == "project_term"], [])
        self.assertEqual(result["context"]["words"]["path"], str(nested.parent / ".yomiyasu-words"))


if __name__ == "__main__":
    unittest.main()
