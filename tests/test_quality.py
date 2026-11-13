"""Проверка включения новых файлов и отказа при сбоях CLI."""

import importlib.util
from pathlib import Path
import subprocess  # nosec B404 # fixed test argv only
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "quality", Path(__file__).parents[1] / "scripts/quality.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Нет quality module")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


class QualityTests(unittest.TestCase):
    def test_new_untracked_inputs_are_owned_and_ignored_state_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(  # nosec B603, B607 # fixed git test argv
                ["git", "init", "-q", str(root)], check=True
            )
            (root / ".gitignore").write_text("state/\nnode_modules/\n")
            (root / "state").mkdir()
            (root / "state/private.py").write_text("secret fixture not read\n")
            (root / "node_modules").mkdir()
            (root / "node_modules/vendor.mjs").write_text("invalid fixture\n")
            new_files = {
                "new.py",
                "new.mjs",
                "new.sh",
                "compose.new.yml",
                "new.php",
                ".github/workflows/new.yml",
            }
            for name in new_files:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("invalid fixture\n")
            self.assertEqual(set(quality.owned_files(root)), new_files | {".gitignore"})

    def test_cli_failure_and_missing_tool_are_fatal(self):
        with self.assertRaises(subprocess.CalledProcessError):
            quality.run([sys.executable, "-c", "raise SystemExit(23)"])
        with self.assertRaises(FileNotFoundError):
            quality.run(["local-quality-missing-cli-negative-control"])

    def test_check_invokes_checks_for_new_language_inputs(self):
        files = [
            "new.py",
            "new.mjs",
            "new.sh",
            "new.yml",
            "new.php",
            "Dockerfile.new",
            ".github/workflows/new.yml",
            "ansible/new.yml",
        ]
        with (
            patch.object(quality, "owned_files", return_value=files),
            patch.object(quality, "run") as run,
            patch.object(quality, "compose_check"),
        ):
            quality.quality("check")
        calls = [call.args[0] for call in run.call_args_list]
        for tool, file in [
            ("ruff", "new.py"),
            ("bandit", "new.py"),
            ("shellcheck", "new.sh"),
            ("yamllint", "new.yml"),
            ("php", "new.php"),
            ("hadolint", "Dockerfile.new"),
            ("node", "new.mjs"),
            ("actionlint", ".github/workflows/new.yml"),
            ("ansible-lint", "ansible/new.yml"),
        ]:
            self.assertTrue(
                any(command[0] == tool and file in command for command in calls),
                (tool, file),
            )
