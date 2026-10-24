"""v2.4.0: lint と diff をスクリプトとして動かしても、スキルのフォルダに __pycache__ を作らない。

check は冒頭で sys.dont_write_bytecode を真にする（tests/test_v200_check.py の test_k33_no_pycache_in_the_skill_scripts）。
lint と diff も、スクリプトとして動かしたときは markdown_visibility を読み込む前に真にする。確かめるため、この試験だけ
-B を付けずに、一時フォルダに写したスキルのフォルダで動かす（リポジトリの scripts には書かない）。
.pyc の置き場所（PYTHONPYCACHEPREFIX）を決めないときと、一時フォルダの中に向けたときの両方で見る。
diff は絵文字のある文で lint の絵文字の数え方を読み込むので、diff から読む yomiyasu_lint.py の .pyc も見る。
文はすべて合成の文。
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import run_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu"
TOOL_STEMS = ("yomiyasu_check.", "yomiyasu_lint.", "yomiyasu_diff.", "yomiyasu_hook.", "markdown_visibility.")
BEFORE = "設定の保存期間は3日です✅\n手順は次のとおりです。\n"
AFTER = "設定の保存期間は30日です✅\n手順は、次のとおりです。\n"


class NoPycacheTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-pycache-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.skill = self.root / "skill"
        shutil.copytree(str(SKILL), str(self.skill),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".yomiyasu"))
        self.scripts = self.skill / "scripts"
        self.before = self.root / "before.md"
        self.after = self.root / "after.md"
        self.before.write_bytes(BEFORE.encode("utf-8"))
        self.after.write_bytes(AFTER.encode("utf-8"))

    def env(self, prefix=None):
        env = dict(os.environ)
        for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "YOMIYASU_STATE_DIR"):
            env.pop(name, None)
        env["YOMIYASU_STATE_DIR"] = str(self.root / ".yomiyasu")
        if prefix is not None:
            env["PYTHONPYCACHEPREFIX"] = str(prefix)
        return env

    def run_tools(self, env):
        lint = str(self.scripts / "yomiyasu_lint.py")
        diff = str(self.scripts / "yomiyasu_diff.py")
        runs = (
            ([lint, str(self.after)], None, 0),
            ([lint, str(self.after), "--json"], None, 0),
            ([lint, "-"], AFTER, 0),
            ([diff, str(self.before), str(self.after)], None, 0),
            ([diff, str(self.before), str(self.after), "--json"], None, 0),
            ([diff, "--version"], None, 0),
            ([lint, "--version"], None, 0),
        )
        for args, stdin, code in runs:
            # -B を付けない（付けると .pyc を書かないことを確かめられない）
            process = run_text([sys.executable] + args, input=stdin, cwd=str(self.root), env=env,
                               capture_output=True, stdin=None if stdin is not None else subprocess.DEVNULL,
                               timeout=120)
            self.assertEqual(process.returncode, code, " ".join(args) + "\n" + process.stdout + process.stderr)

    def pycache_folders(self):
        return sorted(path.relative_to(self.skill).as_posix() for path in self.skill.rglob("__pycache__"))

    def test_no_pycache_beside_the_scripts(self):
        """.pyc の置き場所を決めないとき（Python の既定）は、スクリプトの隣の __pycache__ に書く。"""
        self.run_tools(self.env())
        self.assertEqual(self.pycache_folders(), [])
        self.assertEqual(sorted(path.name for path in self.skill.rglob("*.pyc")), [])

    def test_no_pyc_under_the_cache_prefix(self):
        """PYTHONPYCACHEPREFIX を決めたときは、その下にスクリプトの .pyc を書かない。"""
        prefix = self.root / "pyc"
        self.run_tools(self.env(prefix))
        self.assertEqual(self.pycache_folders(), [])
        written = sorted(path.name for path in prefix.rglob("*.pyc") if path.name.startswith(TOOL_STEMS))
        self.assertEqual(written, [], "スキルのスクリプトの .pyc ができた")

    def test_importing_keeps_the_callers_setting(self):
        """モジュールとして読み込んだときは、読み込む側の sys.dont_write_bytecode を変えない（一時フォルダの写しで読む）。"""
        probe = ("import sys\n"
                 "sys.path.insert(0, sys.argv[1])\n"
                 "import yomiyasu_lint\n"
                 "print('lint', sys.dont_write_bytecode)\n"
                 "import yomiyasu_diff\n"
                 "print('diff', sys.dont_write_bytecode)\n")
        process = subprocess.run([sys.executable, "-c", probe, str(self.scripts)], cwd=str(self.root),
                                 env=self.env(), capture_output=True, encoding="utf-8", timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.splitlines(), ["lint False", "diff False"])


if __name__ == "__main__":
    unittest.main()
