"""3.0.0: flag.txt の使う語と、linked worktree から元の checkout の語の一覧を読む動作。

文と git リポジトリは合成のもの。一覧は一時フォルダの中だけに作る。
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v220_c import CHECK, DIFF, WORD_KEYS, FolderCase, run, write  # noqa: E402
import markdown_visibility  # noqa: E402
import yomiyasu_check  # noqa: E402
import yomiyasu_lint  # noqa: E402


class FlagReplacementTest(FolderCase):
    def git(self, cwd: Path, *args: str) -> None:
        """利用者の git の設定とフックを使わずに git を動かす。git がなければ、この試験を飛ばす。"""
        if shutil.which("git") is None:
            self.skipTest("git がない")
        # 用意が済んだかは試験の実体の属性で見る（環境に初めから GIT_CONFIG_GLOBAL があっても、GIT_DIR などを外す）
        if not getattr(self, "git_env_ready", False):
            self.git_env_ready = True
            local_names = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True,
                                         text=True, encoding="utf-8", check=True).stdout.splitlines()
            for name in local_names:
                self.env.pop(name, None)
            # git rev-parse --local-env-vars に入らないが、-c protocol.file.allow=always を効かなくする変数も外す
            self.env.pop("GIT_ALLOW_PROTOCOL", None)
            self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.root / "no-global-config"),
                            GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                            GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
        cwd.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-c", "core.hooksPath=" + str(self.root / "no-hooks"), "-c", "protocol.file.allow=always",
                        *args], cwd=cwd, env=self.env, capture_output=True, text=True, encoding="utf-8", check=True)

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
        # パターンだけが当たった語の使う語が、ほかの語の使う語の一部に見えても添えない。
        write(folder / "flag.txt", "公開鍵\tkey\n鍵\tkey\n")
        write(folder / "flag-patterns.txt", "鍵\t照合\n")
        write(doc, "公開鍵を照合します。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("- 公開鍵（語の一覧。L1。使う語: key）", process.stdout)
        self.assertIn("- 鍵（語の一覧。L1）", process.stdout)

    def test_linked_worktree_uses_original_checkout_words(self) -> None:
        repo = self.root / "checkout"
        self.git(repo, "init", "--quiet")
        self.git(repo, "commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "Initial fixture")
        self.git(repo, "worktree", "add", "--quiet", "--detach", str(self.root / "linked-worktree"))
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

    def test_submodule_linked_worktree_uses_submodule_words(self) -> None:
        # submodule の共有の git フォルダは親の .git/modules/ にあるので、core.worktree の checkout の一覧を読む。
        library, parent = self.root / "library", self.root / "parent"
        self.git(library, "init", "--quiet")
        self.git(library, "commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "Initial fixture")
        self.git(parent, "init", "--quiet")
        self.git(parent, "submodule", "add", "--quiet", str(library), "sub")
        self.git(parent / "sub", "worktree", "add", "--quiet", "--detach", str(self.root / "sub-worktree"))
        self.words(parent / "sub" / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(self.root / "sub-worktree" / "doc.md", "指紋を照合します。\n")
        result = self.lint_json(str(doc), cwd=doc.parent)
        self.assertEqual(result["context"]["words"]["path"], str(parent / "sub" / ".yomiyasu-words"))


class FlagRowsTest(FolderCase):
    """flag.txt の行の読み方の端（字下げした行、3列の行、使う語の上限、使う語が使わない語を含む組）。"""

    def project_terms(self, doc: Path) -> list[dict]:
        return [f for f in self.lint_json(str(doc))["findings"] if f["rule"] == "project_term"]

    def test_indented_rows_are_read_as_before(self) -> None:
        # 行頭が TAB の行（字下げした語）は、2.5.0 までと同じく1語として読む。字下げした「使わない語<TAB>使う語」も読む。
        folder = self.words(flag="# 用語\n\t指紋\n\t依存先\tdependency\n承認\n\t\n  枝\t\n\t# 字下げのコメント\n", allow="")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual(words["flag"], ("指紋", "依存先", "承認", "枝"))
        self.assertEqual(words["flag_lines"], 4)
        self.assertEqual(words["flag_replacements"], {"依存先": "dependency"})
        doc = write(self.root / "doc.md", "指紋を照合します。\n依存先を更新します。\n承認を待ちます。\n")
        found = self.project_terms(doc)
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([(f["line"], f["message"]) for f in found], [
            (1, "語の一覧（flag.txt）の語（指紋）" + tail),
            (2, "語の一覧（flag.txt）の語（依存先）" + tail + "使う語: 依存先 → dependency。"),
            (3, "語の一覧（flag.txt）の語（承認）" + tail),
        ])

    def test_rows_with_bom_crlf_and_spaces_around_the_tab(self) -> None:
        # BOM と CRLF つきの flag.txt。左と右の前後の空白を除き、右が空なら使う語なし。# で始まる行は TAB があってもコメント。
        data = "\ufeff# コメント\tx\r\n 指紋 \t fingerprint \r\n承認\t\r\n依存先\t\tdependency\r\n　全角の空白　\r\n#鍵\tkey\r\n"
        folder = self.words(flag=data.encode("utf-8"), allow="")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual(words["flag"], ("指紋", "承認", "依存先", "全角の空白"))
        self.assertEqual(words["flag_lines"], 4)
        self.assertEqual(words["flag_replacements"], {"指紋": "fingerprint", "依存先": "dependency"})
        # lint の JSON の候補に、内部の欄（_replacements など）は出ない。
        doc = write(self.root / "doc.md", "指紋を照合します。\n")
        found = self.project_terms(doc)
        self.assertEqual([sorted(f) for f in found], [["line", "message", "rule", "severity", "snippet"]])

    def test_rows_without_inner_tab_are_one_word(self) -> None:
        # 行の前後にしか TAB のない行は、前後の空白と TAB を除いた字が1語になる（2.5.0 までの読み方。使う語は付かない）。
        rows = ["指紋", "\t指紋", "指紋\t", " \t 指紋 \t ", "　指紋　", "二つの 語", "# 指紋", "\t# 指紋", "", " \t "]
        for row in rows:
            with self.subTest(row=row):
                folder = self.words(flag=row + "\n", allow="")
                words = markdown_visibility.load_words(str(folder))
                word = row.strip()
                expected = () if not word or word.startswith("#") else (word,)
                self.assertEqual(words["flag"], expected)
                self.assertEqual(words["flag_lines"], len(expected))
                self.assertEqual(words["flag_replacements"], {})

    def test_later_row_wins_for_the_same_word(self) -> None:
        # 同じ使わない語に違う使う語を書いた行が2つあると、あとの行の使う語を使う。使う語のない行は、前の行の使う語を消さない。
        folder = self.words(flag="指紋\tfingerprint\n承認\n指紋\tフィンガープリント\n指紋\n", allow="")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual(words["flag"], ("指紋", "承認", "指紋", "指紋"))
        self.assertEqual(words["flag_lines"], 4)
        self.assertEqual(words["flag_replacements"], {"指紋": "フィンガープリント"})

    def test_tab_inside_replacement_is_an_input_error(self) -> None:
        # 3列の行（使わない語<TAB>使う語<TAB>メモ）は、ファイルの名前と行番号を出して止める（lint、diff、check とも終了コード2）。
        folder = self.words(flag="承認\n指紋\tfingerprint\tメモ\n", allow="")
        doc = write(self.root / "doc.md", "指紋を照合します。\n")
        source = write(self.root / "source.md", "指紋を照合します。\n")
        message = "Error opening file {}: 2行目の使う語の中にタブがあります".format(folder / "flag.txt")
        for command in ([yomiyasu_lint.__file__, doc], [DIFF, source, doc],
                        [CHECK, "run", "--source", source, "--final", doc, "--no-record"]):
            with self.subTest(command=Path(command[0]).name):
                process = run(command, self.root, self.env)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(message, process.stderr)
        self.assertFalse((self.root / ".yomiyasu").exists())
        # 桁をそろえるために続けた TAB と、行末の TAB は読む。
        self.words(flag="指紋\t\t fingerprint \t\n")
        found = self.project_terms(doc)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["message"].endswith("使う語: 指紋 → fingerprint。"), found[0]["message"])
        self.assertNotIn("\t", found[0]["message"])

    def test_replacement_length_limit(self) -> None:
        limit = markdown_visibility.FLAG_REPLACEMENT_MAX
        folder = self.words(flag="指紋\t" + "あ" * limit + "\n", allow="")
        self.assertEqual(markdown_visibility.load_words(str(folder))["flag_replacements"], {"指紋": "あ" * limit})
        self.words(flag="承認\n\n指紋\t" + "あ" * (limit + 1) + "\n")
        with self.assertRaises(markdown_visibility.WordsError) as caught:
            markdown_visibility.load_words(str(folder))
        self.assertEqual(str(caught.exception), "Error opening file {}: 3行目の使う語は {} 字までです".format(
            folder / "flag.txt", limit))
        # 使わない語の長さには上限を置かない（文書に出た語だけが出力に出るので、今までどおり）。
        self.words(flag="あ" * (limit + 1) + "\n")
        self.assertEqual(markdown_visibility.load_words(str(folder))["flag"], ("あ" * (limit + 1),))

    def test_text_already_using_the_replacement_is_not_flagged(self) -> None:
        # 使う語が使わない語を含む組（サーバ → サーバー）は、もう使う語で書いてある所を数えない。
        self.words(flag="サーバ\tサーバー\n問い合わせ\tお問い合わせ\nAPI\tWeb API\n", allow="")
        doc = write(self.root / "doc.md", "サーバーに接続します。\nサーバを止めます。\nサーバーとサーバを比べます。\n"
                                          "お問い合わせを受け付けます。\n問い合わせに答えます。\n"
                                          "Web API を呼びます。\nAPI を呼びます。\n")
        found = self.project_terms(doc)
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([(f["line"], f["message"]) for f in found], [
            (2, "語の一覧（flag.txt）の語（サーバ）" + tail + "使う語: サーバ → サーバー。"),
            (3, "語の一覧（flag.txt）の語（サーバ）" + tail + "使う語: サーバ → サーバー。"),
            (5, "語の一覧（flag.txt）の語（問い合わせ）" + tail + "使う語: 問い合わせ → お問い合わせ。"),
            (7, "語の一覧（flag.txt）の語（API）" + tail + "使う語: API → Web API。"),
        ])
        # 使う語のない同じ語は、今までどおり語の一部にも当たる。
        self.words(flag="サーバ\n")
        self.assertEqual([f["line"] for f in self.project_terms(doc)], [1, 2, 3])
        # check の「残した指摘の語」にも、もう使う語で書いてある行は出ない。
        self.words(flag="サーバ\tサーバー\n")
        source = write(self.root / "source.md", doc.read_bytes())
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("- サーバ（語の一覧。L2、L3。使う語: サーバー）", process.stdout)

    def test_word_twice_in_the_replacement(self) -> None:
        # 使う語が使わない語を2回含む組では、2つ目の位置の当たりも使う語の中に収まるとみなす。
        self.words(flag="鍵\t鍵と合鍵\n", allow="")
        doc = write(self.root / "doc.md", "鍵と合鍵を渡します。\n合鍵を渡します。\n")
        self.assertEqual([f["line"] for f in self.project_terms(doc)], [2])

    def test_ascii_replacement_is_matched_at_word_boundaries(self) -> None:
        # 英数字で始まるか終わる使う語は、端が語の境目にある所だけを使う語とみなす（flag.txt の語の端と同じ境目）。
        self.words(flag="user\tend user\nDB\tDB server\nname\tfile name\n", allow="")
        doc = write(self.root / "doc.md", "The end user signs in.\nThe backend user signs in.\nA front-end user signs in.\n"
                                          "DB server を増やします。\nDB servers を増やします。\n"
                                          "profile name を決めます。\nfile name を決めます。\n")
        self.assertEqual([f["line"] for f in self.project_terms(doc)], [2, 3, 5, 6])

    def test_japanese_neighbors_that_form_the_replacement_are_not_counted(self) -> None:
        # 日本語の字の端では語の境目を見分けないので、前後の字と合わせて使う語と同じ並びになる所も数えない
        # （docs/tools.md に書いてある動き。読点などで切れていれば数える）。
        self.words(flag="問い合わせ\tお問い合わせ\nサーバ\tサーバ機\n鍵\t公開鍵\n", allow="")
        doc = write(self.root / "doc.md", "なお問い合わせは窓口で受け付けます。\nなお、問い合わせは窓口で受け付けます。\n"
                                          "サーバ機能を止めます。\nサーバを止めます。\n非公開鍵を置きます。\n鍵を置きます。\n")
        self.assertEqual([f["line"] for f in self.project_terms(doc)], [2, 4, 6])

    def test_same_word_on_both_sides_is_read_as_no_replacement(self) -> None:
        # 使う語が使わない語と同じ行（書き間違い）は、使う語のない行として読む。その語の指摘は今までどおり出る。
        folder = self.words(flag="サーバ\tサーバ\nキー\t キー \n", allow="")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual(words["flag"], ("サーバ", "キー"))
        self.assertEqual(words["flag_lines"], 2)
        self.assertEqual(words["flag_replacements"], {})
        doc = write(self.root / "doc.md", "サーバを止めます。\nキーを回します。\n")
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([(f["line"], f["message"]) for f in self.project_terms(doc)], [
            (1, "語の一覧（flag.txt）の語（サーバ）" + tail),
            (2, "語の一覧（flag.txt）の語（キー）" + tail),
        ])
        # 使う語のない行と同じく、前の行の使う語は消さない。
        self.words(flag="サーバ\tサーバー\nサーバ\tサーバ\n")
        self.assertEqual(markdown_visibility.load_words(str(folder))["flag_replacements"], {"サーバ": "サーバー"})

    def test_check_reads_words_before_the_replacement_tail(self) -> None:
        # 使う語に「）の候補です」があっても、check は語を「使う語: 」より前から取る。
        self.words(flag="指紋\t印）の候補です\n", allow="")
        doc = write(self.root / "doc.md", "指紋を照合します。\n")
        source = write(self.root / "source.md", "指紋を照合します。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("\n- 指紋（語の一覧。L1。使う語: 印）の候補です）\n", process.stdout)
        self.assertIn("（最終稿の直訳語と語の一覧の指摘。1語）", process.stdout)

    def test_check_words_with_the_tail_marker_and_no_replacement(self) -> None:
        # 使う語を添えない指摘は、語やパターンの名前に「。使う語: 」があっても、語をそのまま取る（3.0.0 の前と同じ読み方）。
        self.assertEqual(yomiyasu_check._PROJECT_TERM_PLAIN_TAIL, "）" + yomiyasu_lint._V220_MESSAGE_TAIL)
        folder = self.words(flag="承認\n。使う語: 指紋\n", allow="")
        write(folder / "flag-patterns.txt", "名前。使う語: 別\t照合\n")
        doc = write(self.root / "doc.md", "承認して照合します。\n付きます。使う語: 指紋 と出ます。\n")
        source = write(self.root / "source.md", doc.read_bytes())
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("\n- 承認（語の一覧。L1）\n", process.stdout)
        self.assertIn("\n- 名前。使う語: 別（語の一覧。L1）\n", process.stdout)
        self.assertIn("\n- 。使う語: 指紋（語の一覧。L2）\n", process.stdout)
        self.assertIn("（最終稿の直訳語と語の一覧の指摘。3語）", process.stdout)
        self.assertNotIn("語の取れない指摘", process.stdout)

    def test_check_does_not_read_a_replacement_from_a_pattern_name(self) -> None:
        # 使う語を添えない指摘のパターンの名前が「使う語: 語 → 使う語」の形でも、ほかの行の同じ名前の語に使う語を添えない。
        folder = self.words(flag="指紋\tfp\n", allow="")
        write(folder / "flag-patterns.txt", "指紋）の候補です。使う語: 指紋 → fp\t照合\nx\t照合\n指紋\t確認\n")
        doc = write(self.root / "doc.md", "照合します。\n確認します。\n")
        source = write(self.root / "source.md", doc.read_bytes())
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("\n- 指紋（語の一覧。L2）\n", process.stdout)
        self.assertNotIn("L2。使う語: fp", process.stdout)

    def test_check_section_names_the_replacement_as_a_source(self) -> None:
        # 使う語のある語が残った run だけ、冒頭の行と節の文が使う語に触れる。残らない run の文は今までのまま。
        self.words(flag="指紋\tfingerprint\n承認\n", allow="")
        doc = write(self.root / "doc.md", "指紋を照合します。\n承認を待ちます。\n")
        source = write(self.root / "source.md", "指紋を照合します。\n承認を待ちます。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("残した指摘の語: 指紋（語の一覧。L1。使う語: fingerprint）、承認（語の一覧。L2）。", process.stdout)
        self.assertIn("（最終稿の直訳語と語の一覧の指摘。2語）\nflag.txt の使う語は、替える名前の出典にできます"
                      "（references/calques.md 4章）。\n最終稿に残した次の語は、", process.stdout)
        self.assertIn("\n- 書き直しに使う名前が flag.txt の使う語、原文、依頼、提供資料、文脈のどれにもないか、"
                      "動作やその動作をする人が、原文、依頼、提供資料、文脈のどれにも書いていないか、", process.stdout)
        self.assertNotIn("書き直しに使う名前や動作、", process.stdout)
        # verify の「残した指摘の語」には使う語を添えない。
        process = run([CHECK, "verify", "--final", doc], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("指紋（語の一覧。L1）", process.stdout)
        self.assertNotIn("使う語", process.stdout)
        write(doc, "承認を待ちます。\n")
        process = run([CHECK, "run", "--source", source, "--final", doc, "--no-record"], self.root, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("（最終稿の直訳語と語の一覧の指摘。1語）\n最終稿に残した次の語は、", process.stdout)
        self.assertIn("\n- 書き直しに使う名前や動作、その動作をする人が、原文、依頼、提供資料、文脈のどれにも書いていないか、",
                      process.stdout)
        self.assertNotIn("使う語", process.stdout)


class WorktreeFallbackShapeTest(FolderCase):
    """linked worktree の探し方の端。git を使わずに、.git ファイルと管理フォルダを手で作る（Windows の CI でも動く）。"""

    def worktree(self, common: str = ".git", config: str = "[core]\n\tbare = false\n") -> tuple:
        """元の checkout（main）の git フォルダ <main>/<common> と、その worktrees/w を作る。(元, worktree, 管理フォルダ) を返す。"""
        main, work = self.root / "main", self.root / "w"
        admin = main / common / "worktrees" / "w"
        write(admin / "commondir", "../..\n")
        write(main / common / "config", config)
        write(work / ".git", "gitdir: {}\n".format(admin))
        return main, work, admin

    def test_hand_written_worktree_reads_original_checkout_words(self) -> None:
        main, work, admin = self.worktree()
        folder = self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "docs" / "doc.md", "指紋を照合します。\n")
        source = write(work / "docs" / "source.md", "指紋を照合する。\n")
        for marker in ("gitdir: {}\n".format(admin), "gitdir: ../main/.git/worktrees/w\n"):
            with self.subTest(marker=marker):
                write(work / ".git", marker)
                self.assertEqual(self.lint_json(str(doc), cwd=doc.parent)["context"]["words"]["path"], str(folder))
        # check run は元の checkout の場所を記録に残し、verify --replay はその場所でやり直す。
        process = run([CHECK, "run", "--source", source, "--final", doc], doc.parent, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("語の一覧: {}".format(folder), process.stdout)
        process = run([CHECK, "verify", "--final", doc, "--replay"], doc.parent, self.env)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn("replay=ok", process.stdout)
        # worktree に空の .yomiyasu-words/ を置くと、元の checkout の一覧を読まない（--no-words と同じく一覧なし）。
        (work / ".yomiyasu-words").mkdir()
        self.assertNotIn("words", self.lint_json(str(doc), cwd=doc.parent)["context"])

    def test_git_file_that_cannot_be_followed_reads_no_words(self) -> None:
        # 元の checkout に見えるフォルダに一覧があっても、たどれない .git ファイルでは読まない（誤りにもしない）。
        main, work, admin = self.worktree()
        self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        for marker in ("", "hello\n", "gitdir:\n", "gitdir: ../nowhere/.git/worktrees/x\n", "gitdir: g\n"):
            with self.subTest(marker=marker):
                write(work / ".git", marker)
                self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        write(work / ".git", "gitdir: {}\n".format(admin))
        for data in ("\n", b"\xff\xfe"):
            with self.subTest(commondir=data):
                write(admin / "commondir", data)
                self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        write(admin / "commondir", "../..\n")
        self.assertIn("words", self.lint_json(str(doc), cwd=work)["context"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "名前付きパイプを作れない")
    def test_git_entry_that_is_not_a_regular_file_is_not_opened(self) -> None:
        # .git が名前付きパイプのときは、開かずに一覧なしで終わる（開くと、書き手が現れるまで読み終わらない）。
        work = self.root / "w"
        doc = write(work / "doc.md", "指紋を照合します。\n")
        os.mkfifo(work / ".git")
        self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "名前付きパイプを作れない")
    def test_commondir_that_is_not_a_regular_file_is_not_opened(self) -> None:
        # gitdir の先の commondir が名前付きパイプのときも、開かずに一覧なしで終わる。
        main, work, admin = self.worktree()
        self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        (admin / "commondir").unlink()
        os.mkfifo(admin / "commondir")
        self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "名前付きパイプを作れない")
    def test_config_that_is_not_a_regular_file_is_not_opened(self) -> None:
        # 共有の git フォルダの config が名前付きパイプのときは、開かずに、書いてないものとして扱う（名前が .git ならその親）。
        main, work, _ = self.worktree()
        folder = self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        (main / ".git" / "config").unlink()
        os.mkfifo(main / ".git" / "config")
        self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))

    def test_unreadable_config_counts_as_a_plain_checkout(self) -> None:
        # 共有の git フォルダの config を読めなくても（UTF-8 でない字、BOM、ファイルなし）、名前が .git ならその親の一覧を読む。
        main, work, _ = self.worktree()
        folder = self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        config = main / ".git" / "config"
        for data in (b"[user]\n\tname = " + "大賀".encode("cp932") + b"\n", b"\xef\xbb\xbf[core]\n\tbare = false\n", None):
            with self.subTest(config=data):
                if data is None:
                    config.unlink()
                else:
                    write(config, data)
                self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))

    def test_bare_shape_and_core_worktree(self) -> None:
        # 共有の git フォルダの名前が .git でなく、core.worktree もないとき（bare リポジトリから作った worktree）は探さない。
        main, work, _ = self.worktree(common="repo.git", config="[core]\n\tbare = true\n")
        self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        self.words(main / "repo.git" / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        # core.worktree があれば、その checkout の一覧を読む（相対の値は git フォルダから数える。節とキーの大文字と小文字は見分けない）。
        checkout = self.root / "elsewhere"
        folder = self.words(checkout / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        for config in ("[core]\n\tworktree = ../../elsewhere\n", "[CORE]\n\tWorkTree = \"{}\"\n".format(checkout.as_posix())):
            with self.subTest(config=config):
                write(main / "repo.git" / "config", config)
                self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))
        # git が core.worktree を config.worktree に移したとき（submodule で sparse-checkout を使うとき）も読む。あとの値を使う。
        write(main / "repo.git" / "config", "[core]\n\tworktree = ../../nowhere\n[extensions]\n\tworktreeConfig = true\n")
        write(main / "repo.git" / "config.worktree", "[core]\n\tworktree = ../../elsewhere\n")
        self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))

    def test_git_folder_with_another_name_is_not_searched_even_when_not_bare(self) -> None:
        # --separate-git-dir で置いた git フォルダ（名前が .git でなく、bare でもない）の worktree では、その親の一覧を読まない。
        main, work, _ = self.worktree(common="store.git", config="[core]\n\tbare = false\n")
        self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])

    def test_core_worktree_wins_over_the_parent_of_dot_git(self) -> None:
        # 共有の git フォルダの名前が .git でも、core.worktree があればその先を読む（親の一覧は読まない）。
        main, work, _ = self.worktree(config="[core]\n\tbare = false\n\tworktree = ../../elsewhere\n")
        self.words(main / ".yomiyasu-words", flag="承認\n")
        folder = self.words(self.root / "elsewhere" / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))

    def test_bare_is_read_in_every_form_git_writes(self) -> None:
        # bare = true は、値の書き方（TRUE、yes、on、1）、BOM のあとの [core]、config.worktree に移した形でも読む。
        main, work, _ = self.worktree()
        folder = self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        config = main / ".git" / "config"
        for value in ("TRUE", "yes", "on", "1"):
            with self.subTest(value=value):
                write(config, "[core]\n\tbare = {}\n".format(value))
                self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        with self.subTest(config="BOM"):
            write(config, b"\xef\xbb\xbf[core]\n\tbare = true\n")
            self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        # bare リポジトリ（project/.git）の worktree で sparse-checkout を使うと、git は core.bare を config.worktree に移す。
        with self.subTest(config="config.worktree"):
            write(config, "[core]\n\trepositoryformatversion = 1\n[extensions]\n\tworktreeConfig = true\n")
            self.assertEqual(self.lint_json(str(doc), cwd=work)["context"]["words"]["path"], str(folder))
            write(main / ".git" / "config.worktree", "[core]\n\tbare = true\n")
            self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])

    def test_bare_repository_named_dot_git_is_not_searched(self) -> None:
        # bare リポジトリを project/.git に置いて worktree を並べる置き方でも、bare なら親の一覧を探さない。
        main, work, _ = self.worktree(config="[core]\n\tbare = true\n")
        self.words(main / ".yomiyasu-words", flag="指紋\tfingerprint\n")
        doc = write(work / "doc.md", "指紋を照合します。\n")
        self.assertNotIn("words", self.lint_json(str(doc), cwd=work)["context"])
        write(main / ".git" / "config", "[core]\n\tbare = false\n")
        self.assertIn("words", self.lint_json(str(doc), cwd=work)["context"])


if __name__ == "__main__":
    unittest.main()
