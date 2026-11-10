"""Drive-relative CLI paths must stay usable in persisted word-list records."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import json
import ntpath
import os
from pathlib import Path
import pathlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import markdown_visibility as visibility
import yomiyasu_check as check
import yomiyasu_hook as hook


@contextmanager
def legacy_windows() -> Iterator[None]:
    """Use Python 3.9's actual WindowsPath; fake only the native OS boundary."""
    def native_absolute(path: str) -> str:
        if ntpath.isabs(path):
            return ntpath.normpath(path)
        drive, tail = ntpath.splitdrive(path)
        base = r"D:\drive-work" if drive.upper() == "D:" else r"C:\project"
        return ntpath.normpath(ntpath.join(base, tail if drive else path))

    windows_path = SimpleNamespace(**{**vars(ntpath), "abspath": native_absolute})
    windows_os = SimpleNamespace(**{**vars(os), "path": windows_path, "sep": "\\", "name": "nt"})
    with mock.patch.object(pathlib._windows_flavour, "is_supported", True), \
            mock.patch.object(pathlib.os, "getcwd", return_value=r"C:\project"), \
            mock.patch.object(pathlib.WindowsPath, "is_dir", return_value=True), \
            mock.patch.object(visibility, "Path", pathlib.WindowsPath), \
            mock.patch.object(check, "Path", pathlib.WindowsPath), \
            mock.patch.object(hook, "Path", pathlib.WindowsPath), \
            mock.patch.object(visibility, "os", windows_os), \
            mock.patch.object(check, "os", windows_os), \
            mock.patch.object(hook, "os", windows_os):
        yield


@unittest.skipUnless(sys.version_info[:2] == (3, 9) and os.name != "nt", "Python 3.9 WindowsPath on a non-Windows test host")
class LegacyWindowsPathTest(unittest.TestCase):
    def test_empty_home_keeps_the_literal_tilde_folder(self) -> None:
        for environment in ({"USERPROFILE": ""}, {"HOMEDRIVE": "", "HOMEPATH": ""}):
            with legacy_windows(), mock.patch.dict(os.environ, environment, clear=True):
                for operation in (visibility._words_home, check._home_path, hook._home_path):
                    with self.subTest(environment=environment, operation=operation.__name__):
                        self.assertEqual(operation("~/lists"), "~/lists")
                with self.subTest(environment=environment, operation="find_words_folder"):
                    self.assertEqual(visibility.find_words_folder(r"C:\project", "~/lists"),
                                     r"C:\project\~\lists")

    def test_words_context_is_accepted_by_the_record_validator(self) -> None:
        with legacy_windows():
            folder = visibility.find_words_folder(r"C:\project", "D:lists")
            words = {"path": folder, "allow_lines": 1, "flag_lines": 0,
                     "allow_sha256": "0" * 64, "flag_sha256": None}
            self.assertTrue(check._words_shape(words), words)
            self.assertEqual(folder, r"D:\drive-work\lists")

    def test_state_and_hook_paths_keep_the_other_drives_directory(self) -> None:
        with legacy_windows():
            for operation in (lambda: check.state_dir_for(r"C:\project", "D:state"),
                              lambda: hook._absolute_path("D:state")):
                with self.subTest(operation=operation):
                    self.assertEqual(operation(), r"D:\drive-work\state")


@unittest.skipUnless(os.name == "nt", "requires real Windows drive-relative resolution")
class NativeWindowsDriveTest(unittest.TestCase):
    def test_empty_home_chooses_the_literal_tilde_word_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yomiyasu-home-") as folder:
            root = Path(folder)
            for words in (root / "lists", root / "~" / "lists"):
                words.mkdir(parents=True)
                (words / "allow.txt").write_bytes("入口\n".encode("utf-8"))
            for environment in ({"USERPROFILE": ""}, {"HOMEDRIVE": "", "HOMEPATH": ""}):
                with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True):
                    words = visibility.resolve_words(str(root), "~/lists")
                    self.assertEqual(words["path"], str(root / "~" / "lists"))
                    self.assertEqual(check._home_path("~/lists"), "~/lists")
                    self.assertEqual(hook._home_path("~/lists"), "~/lists")

    def test_run_verify_and_export_with_words_on_another_drive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yomiyasu-drive-") as folder:
            root = Path(folder)
            project, work = root / "project", root / "work"
            project.mkdir()
            work.mkdir()
            words = work / "lists"
            words.mkdir()
            (words / "allow.txt").write_bytes("入口\n".encode("utf-8"))
            original = str(Path.cwd())
            drive = None
            for letter in "ZYXWVUTSRQPONMLKJIHGFED":
                candidate = letter + ":"
                mapped = subprocess.run(["subst", candidate, str(root)], capture_output=True, timeout=10)
                if mapped.returncode == 0:
                    drive = candidate
                    break
            if drive is None:
                self.skipTest("no unused drive letter is available for a temporary SUBST mapping")
            try:
                os.chdir(drive + "\\work")
                os.chdir(project)
                source, final, state = project / "a.md", project / "b.md", project / "state"
                source.write_bytes("設定を更新します。\n".encode("utf-8"))
                final.write_bytes("設定を更新しました。\n".encode("utf-8"))
                tool = [sys.executable, "-B", str(ROOT / "scripts/yomiyasu_check.py")]
                result = subprocess.run(tool + ["run", "--source", str(source), "--final", str(final),
                                               "--state-dir", str(state), "--run-id", "drive-case",
                                               "--words", drive + "lists", "--json"],
                                        capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                for command, expected in (("verify", "executed"), ("export", "exported")):
                    with self.subTest(command=command):
                        result = subprocess.run(tool + [command, "--state-dir", str(state),
                                                       "--run-id", "drive-case", "--final", str(final), "--json"],
                                                capture_output=True, timeout=60)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout)["status"], expected)
            finally:
                os.chdir(original)
                subprocess.run(["subst", drive, "/D"], capture_output=True, check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
