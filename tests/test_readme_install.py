"""README の Codex 向けの入れ方（.agents/skills に置く手順）のコマンドを、そのまま sh で動かして確かめる。

README.md の「6. Codex で使うリポジトリに置く」と README.en.md の同じ手順のコマンドが同じ文字列であることと、
初めて入れるとき、利用者が書き換えたフォルダを入れ直すとき（前のフォルダを消さずに .agents/skills の外へ移す）、
続けて入れ直すとき（何も変えない）、取り出しに失敗したとき（前のフォルダに触れない）の動きを見る。

GitHub には接続しない。git の insteadOf で、README の URL をこのチェックアウトの skills/yomiyasu から作った
一時リポジトリに向け、GIT_ALLOW_PROTOCOL で file だけを許す（insteadOf が効かなくても外へ出ない）。HOME と TMPDIR は
試験の一時フォルダの中に向け、git の設定は GIT_CONFIG_GLOBAL の一時ファイルだけを読むので、利用者の設定と共有の /tmp には
触れない。macOS の mktemp -d は TMPDIR を見ずに利用者ごとの一時フォルダ（/var/folders の下）に作ることがあるので、
README のコマンドの前に、引数が -d だけの mktemp を TMPDIR の下に作り、作った場所を記録する sh の関数を置く
（README のコマンドは変えない）。こうして、取り出し用の一時フォルダがコマンドの終わりに消えることも、macOS と Linux で
同じように見る。
Windows と、sh か git がない環境、GIT_CONFIG_GLOBAL を読まない git（2.32 より前）では飛ばす。
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import run_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/nanaism/yomiyasu"
JA_MARKER = "### 6. Codex で使うリポジトリに置く"
EN_MARKER = "Codex reads skills from"
# README のコマンドの前に置く sh の関数。引数が -d だけの mktemp を TMPDIR の下に作り、作った場所を $HOME/mktemp.log に書く
MKTEMP_SHIM = (
    "mktemp() {\n"
    "  if [ \"$#\" = 1 ] && [ \"$1\" = -d ]; then\n"
    "    _test_made=$(command mktemp -d \"$TMPDIR/tmp.XXXXXXXX\") || return 1\n"
    "    echo \"$_test_made\" >> \"$HOME/mktemp.log\"\n"
    "    echo \"$_test_made\"\n"
    "  else\n"
    "    command mktemp \"$@\"\n"
    "  fi\n"
    "}\n"
)


def _block(text, marker):
    """marker の文を含む段落のあとで最初に出る ```bash のブロック。"""
    start = text.index(marker)
    match = re.compile(r"^```bash\n(.*?)^```$", re.M | re.S).search(text, start)
    return match.group(1)


def _git_version():
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    found = re.search(r"(\d+)\.(\d+)", out)
    return (int(found.group(1)), int(found.group(2))) if found else None


def _tree(path):
    """path の下のファイルの (相対パス, 中身) の組。"""
    result = {}
    for item in sorted(Path(path).rglob("*")):
        if item.is_file():
            result[item.relative_to(path).as_posix()] = item.read_bytes()
    return result


def _append(path, text):
    with open(str(path), "ab") as stream:
        stream.write(text.encode("utf-8"))


@unittest.skipIf(os.name == "nt", "README のコマンドは POSIX の sh 向け")
@unittest.skipIf(shutil.which("sh") is None or (_git_version() or (0, 0)) < (2, 32), "sh か git 2.32 以上がない")
class ReadmeCodexInstall(unittest.TestCase):
    def setUp(self):
        self.ja = _block((ROOT / "README.md").read_text(encoding="utf-8"), JA_MARKER)
        self.en = _block((ROOT / "README.en.md").read_text(encoding="utf-8"), EN_MARKER)
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-readme-")
        self.addCleanup(folder.cleanup)
        self.tmp = Path(os.path.realpath(folder.name))
        (self.tmp / "home").mkdir()
        (self.tmp / "t").mkdir()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        self.empty = self.tmp / "empty.gitconfig"
        self.empty.write_bytes(b"")

        src = self.tmp / "src"
        shutil.copytree(str(ROOT / "skills" / "yomiyasu"), str(src / "skills" / "yomiyasu"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".yomiyasu"))
        self.expected = _tree(src / "skills" / "yomiyasu")
        git = ["git", "-C", str(src), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
               "-c", "commit.gpgsign=false"]
        for command in (["git", "init", "-q", str(src)], git + ["add", "-A"], git + ["commit", "-q", "-m", "skill"]):
            done = subprocess.run(command, env=self.env(self.empty), capture_output=True, encoding="utf-8",
                                  timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        self.good = self.tmp / "good.gitconfig"
        self.good.write_bytes('[url "{}"]\n\tinsteadOf = {}\n'.format(src.as_uri(), URL).encode("utf-8"))
        self.bad = self.tmp / "bad.gitconfig"
        self.bad.write_bytes('[url "{}"]\n\tinsteadOf = {}\n'.format((self.tmp / "missing").as_uri(), URL)
                             .encode("utf-8"))

    def env(self, config):
        """利用者の git の設定と環境の GIT_ の変数を読まない環境。HOME と TMPDIR は一時フォルダの中。"""
        env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1", GIT_ALLOW_PROTOCOL="file",
                   GIT_TERMINAL_PROMPT="0", HOME=str(self.tmp / "home"), TMPDIR=str(self.tmp / "t"), LC_ALL="C")
        return env

    def run_block(self, config):
        # 2.3.0 までの手順は共有の /tmp/yomiyasu を消して作り直すので、その形のときは動かさずに落とす
        self.assertNotIn("/tmp/", self.ja, "README のコマンドが共有の /tmp を使っています。動かさずに止めます")
        made_before = self.made()
        process = run_text(["sh"], input=MKTEMP_SHIM + self.ja, cwd=str(self.proj), env=self.env(config),
                           capture_output=True, timeout=120)
        # 取り出し用の一時フォルダは TMPDIR の下に1つだけ作られ、うまくいったときも失敗したときも消える
        made = self.made()[len(made_before):]
        self.assertEqual(len(made), 1, process.stdout + process.stderr)
        self.assertEqual(Path(made[0]).parent, self.tmp / "t")
        self.assertEqual(list((self.tmp / "t").iterdir()), [], process.stdout + process.stderr)
        return process

    def made(self):
        """README のコマンドが mktemp -d で作ったフォルダ（作った順）。"""
        log = self.tmp / "home" / "mktemp.log"
        return log.read_bytes().decode("utf-8").splitlines() if log.is_file() else []

    def backups(self):
        return sorted(p.name for p in (self.proj / ".agents").iterdir() if p.name.startswith("yomiyasu.bak-"))

    def test_same_commands_in_both_readmes(self):
        self.assertEqual(self.ja, self.en)
        self.assertIn(URL, self.ja)
        self.assertIn("$(mktemp -d)", self.ja)  # MKTEMP_SHIM が置き換える呼び方
        self.assertNotIn("/tmp/", self.ja)
        self.assertNotRegex(self.ja, r"(?m)^\s*#")  # 対話の zsh は「#」の行をコマンドとして読む

    def test_fresh_update_rerun_and_failed_clone(self):
        installed = self.proj / ".agents" / "skills" / "yomiyasu"

        # 初めて入れる
        first = self.run_block(self.good)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("Installed .agents/skills/yomiyasu", first.stdout)
        self.assertEqual(_tree(installed), self.expected)
        self.assertEqual(self.backups(), [])
        self.assertEqual(sorted(p.name for p in (self.proj / ".agents").iterdir()), ["skills"])

        # 利用者が書き換えたフォルダを入れ直す: 前のフォルダは .agents/skills の外に、書き換えたまま移る
        _append(installed / "SKILL.md", "local edit\n")
        (installed / "references" / "my-notes.md").write_bytes("my notes\n".encode("utf-8"))
        second = self.run_block(self.good)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(_tree(installed), self.expected)
        [backup] = self.backups()
        self.assertIn("Moved the previous folder to .agents/" + backup, second.stdout)
        kept = self.proj / ".agents" / backup
        self.assertTrue((kept / "SKILL.md").read_bytes().endswith(b"local edit\n"))
        self.assertEqual((kept / "references" / "my-notes.md").read_bytes(), b"my notes\n")
        self.assertEqual(sorted(p.name for p in (self.proj / ".agents" / "skills").iterdir()), ["yomiyasu"])
        self.assertEqual(len(list((self.proj / ".agents" / "skills").rglob("SKILL.md"))), 1)

        # 続けて入れ直す: 中身が同じなので何も変えない
        for _ in range(2):
            again = self.run_block(self.good)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertIn("Already up to date", again.stdout)
            self.assertEqual(_tree(installed), self.expected)
        self.assertEqual(self.backups(), [backup])

        # 取り出しに失敗する: 前のフォルダ（書き換えたもの）に触れず、移しもしない
        _append(installed / "SKILL.md", "second edit\n")
        before = _tree(installed)
        failed = self.run_block(self.bad)
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn("Installed", failed.stdout)
        self.assertEqual(_tree(installed), before)
        self.assertTrue((installed / "SKILL.md").read_bytes().endswith(b"second edit\n"))
        self.assertEqual(self.backups(), [backup])


if __name__ == "__main__":
    unittest.main()
