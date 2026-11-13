import io
from pathlib import Path
import subprocess  # nosec B404 # explicit argv process API; no shell
import tarfile
import tempfile
import unittest

import yaml


PLAY = yaml.safe_load((Path(__file__).parents[1] / "ansible/deploy.yml").read_text())[0]


class DeployBoundaryTest(unittest.TestCase):
    def test_stages_before_single_sync_and_checks_revision_before_switch(self):
        tasks = PLAY["tasks"]
        guarded = next(task for task in tasks if "block" in task)
        block = guarded["block"]

        def index(module):
            return next(i for i, task in enumerate(block) if module in task)

        uri = [task for task in block if "ansible.builtin.uri" in task]
        self.assertEqual(len(uri), 2)
        self.assertEqual(uri[0]["ansible.builtin.uri"]["method"], "POST")
        self.assertNotIn("until", uri[0])
        self.assertNotIn("retries", uri[0])
        self.assertEqual(uri[1]["ansible.builtin.uri"].get("method", "GET"), "GET")
        self.assertLess(
            index("ansible.builtin.unarchive"), index("ansible.builtin.uri")
        )
        revision = next(
            i
            for i, task in enumerate(block)
            if "--expected-commit"
            in task.get("ansible.builtin.command", {}).get("argv", [])
        )
        switch = next(
            i
            for i, task in enumerate(block)
            if task.get("ansible.builtin.command", {}).get("argv", [None])[0] == "mv"
        )
        self.assertLess(revision, switch)
        self.assertTrue(
            block[revision]["ansible.builtin.command"]["stdin"].endswith(
                "'/../scripts/check-native-revision.mjs') }}"
            )
        )
        self.assertIn("expected_native_commit", str(tasks[0]))
        # No mkdir -p: an old release (including the active release) must fail, not be rewritten.
        reserve = next(
            task["ansible.builtin.command"]["argv"]
            for task in block
            if task.get("ansible.builtin.command", {}).get("argv", [None])[0] == "mkdir"
        )
        self.assertNotIn("-p", reserve)
        lock = tasks[tasks.index(guarded) - 1]["ansible.builtin.command"]["argv"]
        self.assertEqual(lock[0], "mkdir")
        self.assertNotIn("-p", lock)
        self.assertEqual(
            guarded["always"][0]["ansible.builtin.command"]["argv"][0], "rmdir"
        )

    def validate_archive(self, entries):
        task = next(
            task for task in PLAY["tasks"] if task.get("delegate_to") == "localhost"
        )
        validator = task["ansible.builtin.command"]["argv"][2]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "site.tar"
            with tarfile.open(archive, "w") as tar:
                for name, kind in entries:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.size = 1 if kind == tarfile.REGTYPE else 0
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        entry.linkname = "/outside"
                    tar.addfile(entry, io.BytesIO(b"x") if entry.size else None)
            return subprocess.run(  # nosec B603, B607 # installed openssl/CLI from operator PATH; fixed argv, shell=False
                ["python3", "-c", validator, str(archive)], capture_output=True
            ).returncode

    def test_archive_validation_accepts_ready_site(self):
        self.assertEqual(
            self.validate_archive(
                [
                    ("./index.html", tarfile.REGTYPE),
                    ("assets", tarfile.DIRTYPE),
                    ("assets/a.js", tarfile.REGTYPE),
                ]
            ),
            0,
        )

    def test_archive_validation_rejects_incomplete_or_escaping_tree_before_sync(self):
        for entries in [
            [],
            [("assets/a.js", tarfile.REGTYPE)],
            [("index.html", tarfile.SYMTYPE)],
            [("index.html", tarfile.REGTYPE), ("../outside", tarfile.REGTYPE)],
            [("index.html", tarfile.REGTYPE), ("/outside", tarfile.REGTYPE)],
            [("index.html", tarfile.REGTYPE), ("assets", tarfile.SYMTYPE)],
            [("index.html", tarfile.REGTYPE), ("assets", tarfile.LNKTYPE)],
            [("index.html", tarfile.REGTYPE), ("device", tarfile.CHRTYPE)],
        ]:
            with self.subTest(entries=entries):
                self.assertNotEqual(self.validate_archive(entries), 0)


if __name__ == "__main__":
    unittest.main()
