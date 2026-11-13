import importlib.util
import json
from pathlib import Path
import subprocess  # nosec B404 # explicit argv process API; no shell
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "preview", Path(__file__).parents[1] / "scripts/preview.py"
)
assert SPEC is not None and SPEC.loader is not None  # nosec B101 # test-only importlib loader invariant
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class PreviewConfigTest(unittest.TestCase):
    def test_preview_image_override_is_independent_of_production_environment(self):
        for image in ("", "example.invalid/reviewed-preview:fixture"):
            with (
                self.subTest(image=image),
                patch.dict(
                    preview.os.environ,
                    {"PL_IMAGE": "production-only", "PL_PREVIEW_IMAGE": image},
                ),
                patch.object(preview.sys, "argv", ["preview.py", "down"]),
                patch.object(preview, "run") as run,
            ):
                preview.main()
                self.assertEqual(run.call_args.kwargs["env"]["PL_IMAGE"], image)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index("--env-file") + 1], "/dev/null")
                self.assertEqual(
                    run.call_args.kwargs["env"]["PREVIEW_PLATFORM_ROOT"],
                    str(preview.ROOT / "deps/platform"),
                )

    def test_repeat_up_preserves_keys_and_stable_course_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            preview.prepare_config(state, "java", 8088)
            first = json.loads((state / "pl/config.json").read_text())
            preview.prepare_config(state, "java", 18088)
            second = json.loads((state / "pl/config.json").read_text())
            self.assertEqual(first["secretKey"], second["secretKey"])
            self.assertEqual(
                first["databaseEncryptionKey"], second["databaseEncryptionKey"]
            )
            self.assertEqual(second["courseDirs"], ["/course/java/current"])
            self.assertEqual(second["serverCanonicalHost"], "http://127.0.0.1:18088")

    def test_production_state_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / "pl").mkdir()
            config = state / "pl/config.json"
            original = '{"devMode":false,"hasShib":true}'
            config.write_text(original)
            with self.assertRaisesRegex(ValueError, "отдельный preview state"):
                preview.prepare_config(state, "java", 8088)
            self.assertEqual(config.read_text(), original)

    def test_config_symlink_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / "pl").mkdir()
            external = state / "external.json"
            external.write_text("{}")
            (state / "pl/config.json").symlink_to(external)
            with self.assertRaisesRegex(ValueError, "Небезопасный файл"):
                preview.prepare_config(state, "java", 8088)
            self.assertEqual(external.read_text(), "{}")


class PreviewActivationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.course = self.root / "builds/java"
        self.course.mkdir(parents=True)
        self.loaded = {
            "courseId": 27,
            "jobSequenceId": "91",
            "instances": [{"id": 41, "short_name": "test"}],
        }

    def release(self, name):
        release = self.course / "releases" / name
        (release / "native").mkdir(parents=True)
        (release / "site").mkdir()
        (release / "native/infoCourse.json").write_text(name)
        (release / "site/index.html").write_text(name)
        return release

    def accepted(self, name="old"):
        self.release(name)
        (self.course / "active").symlink_to("releases/" + name)
        (self.course / "current").symlink_to("active/native")
        (self.course / "site").symlink_to("active/site")

    def candidate(self, name="new"):
        self.release(name)
        (self.course / "prepared").unlink(missing_ok=True)
        (self.course / "prepared").symlink_to("releases/" + name)

    def activate(self, runner=None, *, start=False):
        def success(command, **kwargs):
            if "exec" in command:
                self.job("terminal", native_status="Success")
            return subprocess.CompletedProcess(
                command, 0, json.dumps(self.loaded) + "\n"
            )

        with (
            patch.object(preview, "run", side_effect=runner or success) as run,
            patch.object(preview, "wait_http") as wait,
        ):
            result = preview.activate(
                self.course,
                compose=["docker", "compose"],
                env={},
                course_name="java",
                state=self.root / "state",
                port=8088,
                origin="http://127.0.0.1:8088",
                timeout=30,
                start=start,
                project="pl-preview-test",
            )
        return result, run, wait

    def job(self, phase, *, job_id: str | None = "91", native_status=None):
        path = self.job_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"coursePath": "/course/java/current", "phase": phase}
        if job_id is not None:
            record["jobSequenceId"] = job_id
        if native_status:
            record["nativeStatus"] = native_status
        preview.write_json(path, record)
        return path

    def job_path(self):
        status = preview.load_status(self.course)
        return (
            Path(status["jobStateFile"])
            if status and status.get("jobStateFile")
            else self.root / "state/jobs/preview-load-java.json"
        )

    def assert_status(self, outcome, accepted, *, terminal):
        status = preview.load_status(self.course)
        self.assertEqual(status["outcome"], outcome)
        self.assertEqual(status["candidateRelease"], "new")
        self.assertEqual(status["acceptedRelease"], accepted)
        self.assertEqual(status["nativeJobTerminal"], terminal)
        self.assertEqual(status["nativeMayBePartial"], outcome != "succeeded")
        return status

    def test_accepted_site_switches_only_after_exactly_one_successful_native_job(self):
        self.accepted()
        self.candidate()

        def load(command, **kwargs):
            self.assertEqual((self.course / "site/index.html").read_text(), "old")
            self.assertEqual(
                (self.course / "current/infoCourse.json").read_text(), "new"
            )
            self.assertEqual((self.course / "active").readlink(), Path("releases/old"))
            status = preview.load_status(self.course)
            self.assertEqual(status["outcome"], "loading")
            self.assertEqual(status["acceptedRelease"], "old")
            # prepare cannot replace candidate while native sync is running.
            with self.assertRaisesRegex(ValueError, "Курс занят"):
                with preview.prepare_lock(self.course):
                    self.fail("second lock acquired")
            self.job("terminal", native_status="Success")
            return subprocess.CompletedProcess(
                command, 0, "native log\n" + json.dumps(self.loaded) + "\n"
            )

        loaded, run, wait = self.activate(load)
        self.assertEqual(loaded, self.loaded)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--path") + 1], "/course/java/current")
        wait.assert_called_once_with("http://127.0.0.1:8088", 30, site=False)
        self.assertEqual((self.course / "active").readlink(), Path("releases/new"))
        self.assertEqual((self.course / "site/index.html").read_text(), "new")
        self.assert_status("succeeded", "new", terminal=True)

    def test_failed_native_job_keeps_site_and_candidate_disk_without_database_rollback(
        self,
    ):
        self.accepted()
        self.candidate()
        calls = []

        def fail(command, **kwargs):
            calls.append(command)
            self.job("terminal", native_status="Error")
            raise subprocess.CalledProcessError(1, command, output="native job failed")

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(fail)
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.course / "active").readlink(), Path("releases/old"))
        self.assertEqual((self.course / "site/index.html").read_text(), "old")
        self.assertEqual((self.course / "current/infoCourse.json").read_text(), "new")
        self.assert_status("failed", "old", terminal=True)
        # A retry runs the same native path; numeric IDs are passed through unchanged.
        loaded, run, _ = self.activate()
        self.assertEqual(loaded["courseId"], 27)
        self.assertEqual(loaded["instances"][0]["id"], 41)
        self.assertIn("/course/java/current", run.call_args.args[0])

    def test_first_up_loads_before_site_readiness_and_accepts_after_job(self):
        self.candidate()
        loaded, run, wait = self.activate(start=True)
        self.assertEqual(loaded, self.loaded)
        self.assertEqual(run.call_count, 2)
        self.assertIn("up", run.call_args_list[0].args[0])
        self.assertIn("exec", run.call_args_list[1].args[0])
        wait.assert_called_once_with("http://127.0.0.1:8088", 30, site=False)
        self.assertEqual((self.course / "site/index.html").read_text(), "new")

    def test_legacy_active_can_load_without_prepare_and_migrates_current_only(self):
        self.accepted()
        loaded, _, _ = self.activate()
        self.assertEqual(loaded, self.loaded)
        self.assertEqual(
            (self.course / "current").readlink(), Path("releases/old/native")
        )
        self.assertEqual((self.course / "site").readlink(), Path("active/site"))
        self.assertEqual((self.course / "active").readlink(), Path("releases/old"))

    def test_rejects_unowned_or_escaping_links_before_native_job(self):
        self.accepted()
        self.candidate()
        for name, target in [
            ("prepared", "../outside"),
            ("active", "/outside-native-fixture"),
            ("current", "../outside/native"),
            ("site", "prepared/site"),
        ]:
            with self.subTest(name=name):
                path = self.course / name
                original = path.readlink()
                path.unlink()
                path.symlink_to(target)
                with patch.object(preview, "run") as run, self.assertRaises(ValueError):
                    self.activate(run)
                run.assert_not_called()
                path.unlink()
                path.symlink_to(original)
        self.assertFalse((self.course / "load-status.json").exists())

    def test_rejects_symlinked_release_native_and_status_file(self):
        self.candidate()
        native = self.course / "releases/new/native"
        native.rename(self.root / "external-native")
        native.symlink_to(self.root / "external-native")
        with self.assertRaises(ValueError):
            self.activate()
        native.unlink()
        (self.root / "external-native").rename(native)
        external = self.root / "external-status"
        external.write_text("keep")
        (self.course / "load-status.json").symlink_to(external)
        with self.assertRaises(ValueError):
            self.activate()
        self.assertEqual(external.read_text(), "keep")

    def test_loader_success_without_valid_job_result_does_not_accept_candidate(self):
        self.accepted()
        self.candidate()

        def invalid_result(command, **kwargs):
            self.job("terminal", native_status="Success")
            return subprocess.CompletedProcess(command, 0, '{"courseId": 27}\n')

        with self.assertRaisesRegex(ValueError, "результат native server job"):
            self.activate(invalid_result)
        self.assertEqual((self.course / "site/index.html").read_text(), "old")
        self.assertTrue(preview.load_status(self.course)["nativeMayBePartial"])

    def test_first_up_failure_does_not_publish_site_or_active(self):
        self.candidate()

        def fail(command, **kwargs):
            if "exec" in command:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, "")

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(fail, start=True)
        self.assertFalse((self.course / "active").exists())
        self.assertFalse((self.course / "site/index.html").exists())
        self.assertIsNone(preview.load_status(self.course)["acceptedRelease"])

    def test_failed_status_is_visible_and_ready_refuses_without_mutating_state(self):
        self.accepted()
        self.candidate()
        preview.write_json(
            self.course / "load-status.json",
            {
                "outcome": "failed",
                "candidateRelease": "new",
                "acceptedRelease": "old",
                "nativeMayBePartial": True,
            },
        )
        before = (self.course / "load-status.json").read_bytes()
        argv = ["preview", "ready", "--output-root", str(self.course.parent)]
        with (
            patch("sys.argv", argv),
            patch.object(preview, "wait_http") as wait,
            self.assertRaisesRegex(ValueError, "повторите up/load"),
        ):
            preview.main()
        wait.assert_not_called()
        self.assertEqual((self.course / "load-status.json").read_bytes(), before)

    def test_timeout_resumes_same_job_and_candidate_before_new_prepared_release(self):
        self.accepted()
        self.candidate()

        def timeout(command, **kwargs):
            self.job("running")
            raise subprocess.CalledProcessError(
                1, command, output="timeout does not cancel job"
            )

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(timeout)
        self.assert_status("failed", "old", terminal=False)
        self.candidate("newer")

        def resume(command, **kwargs):
            self.assertIn("--resume", command)
            self.assertEqual(
                preview.native_job_state(self.job_path(), "java")["jobSequenceId"], "91"
            )
            self.assertEqual(
                (self.course / "current/infoCourse.json").read_text(), "new"
            )
            self.assertEqual((self.course / "site/index.html").read_text(), "old")
            self.job("terminal", native_status="Success")
            return subprocess.CompletedProcess(
                command, 0, json.dumps(self.loaded) + "\n"
            )

        _, run, _ = self.activate(resume)
        run.assert_called_once()
        self.assertEqual((self.course / "site/index.html").read_text(), "new")
        self.assertEqual((self.course / "prepared").readlink(), Path("releases/newer"))
        old_job_path = self.job_path()

        # A different prepared release only starts on the following explicit invocation.
        def next_job(command, **kwargs):
            self.assertNotIn("--resume", command)
            self.assertNotEqual(self.job_path(), old_job_path)
            self.assertTrue(old_job_path.is_file())
            self.assertFalse(self.job_path().exists())
            self.assertEqual(
                (self.course / "current/infoCourse.json").read_text(), "newer"
            )
            self.job("terminal", native_status="Success")
            return subprocess.CompletedProcess(
                command, 0, json.dumps(self.loaded) + "\n"
            )

        self.activate(next_job)
        self.assertEqual((self.course / "site/index.html").read_text(), "newer")

    def test_timeout_resume_accepts_generated_release_starting_with_underscore(self):
        self.accepted()
        self.candidate("_fqux0aa")

        def timeout(command, **kwargs):
            self.job("running")
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(timeout)
        self.candidate("newer")
        _, run, _ = self.activate()
        self.assertIn("--resume", run.call_args.args[0])
        self.assertEqual((self.course / "active").readlink(), Path("releases/_fqux0aa"))

    def test_lost_response_without_job_id_blocks_repost_and_candidate_switch(self):
        self.accepted()
        self.candidate()

        def lost_response(command, **kwargs):
            self.job("intent", job_id=None)
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(lost_response)
        self.candidate("newer")
        run = mock.Mock()
        with self.assertRaisesRegex(ValueError, "ID неизвестен.*POST запрещён"):
            self.activate(run)
        run.assert_not_called()
        self.assertEqual((self.course / "current/infoCourse.json").read_text(), "new")
        self.assertEqual((self.course / "site/index.html").read_text(), "old")

    def test_interruption_before_job_record_is_unknown_and_cannot_repost(self):
        self.accepted()
        self.candidate()

        def interrupted(command, **kwargs):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.activate(interrupted)
        self.assert_status("failed", "old", terminal=False)
        run = mock.Mock()
        with self.assertRaisesRegex(ValueError, "ID неизвестен"):
            self.activate(run)
        run.assert_not_called()

    def test_status_write_error_preserves_primary_error_and_pending_job(self):
        self.accepted()
        self.candidate()
        write = preview.write_json

        def failing_status(path, value):
            if value.get("outcome") == "failed":
                raise OSError("status disk unavailable")
            write(path, value)

        def timeout(command, **kwargs):
            self.job("running")
            raise subprocess.CalledProcessError(77, command)

        with (
            patch.object(preview, "write_json", side_effect=failing_status),
            self.assertRaises(subprocess.CalledProcessError) as error,
        ):
            self.activate(timeout)
        self.assertEqual(error.exception.returncode, 77)
        self.assertEqual(preview.load_status(self.course)["outcome"], "loading")
        self.assertFalse(preview.load_status(self.course)["nativeJobTerminal"])
        _, run, _ = self.activate()
        self.assertIn("--resume", run.call_args.args[0])

    def test_successful_job_commit_failure_resumes_receipt_before_new_prepared(self):
        self.accepted()
        self.candidate()
        replace = preview.replace_link

        def broken_commit(course, name, target):
            if name == "active":
                raise OSError("active disk unavailable")
            replace(course, name, target)

        with (
            patch.object(preview, "replace_link", side_effect=broken_commit),
            self.assertRaisesRegex(OSError, "active disk unavailable"),
        ):
            self.activate()
        self.assert_status("failed", "old", terminal=True)
        self.candidate("newer")
        _, run, _ = self.activate()
        self.assertIn("--resume", run.call_args.args[0])
        self.assertEqual((self.course / "current/infoCourse.json").read_text(), "new")
        self.assertEqual((self.course / "site/index.html").read_text(), "new")

    def test_success_status_write_failure_reconciles_same_job_after_active_commit(self):
        self.accepted()
        self.candidate()
        write = preview.write_json

        def broken_success(path, value):
            if value.get("outcome") == "succeeded":
                raise OSError("accepted status disk unavailable")
            write(path, value)

        with (
            patch.object(preview, "write_json", side_effect=broken_success),
            self.assertRaisesRegex(OSError, "accepted status disk unavailable"),
        ):
            self.activate()
        self.assertEqual((self.course / "site/index.html").read_text(), "new")
        self.candidate("newer")
        _, run, _ = self.activate()
        self.assertIn("--resume", run.call_args.args[0])
        self.assertEqual((self.course / "site/index.html").read_text(), "new")

    def test_status_reads_actual_job_id_without_mutating_after_controller_loss(self):
        self.accepted()
        self.candidate()
        path = self.job("running")
        preview.write_json(
            self.course / "load-status.json",
            {
                "outcome": "loading",
                "candidateRelease": "new",
                "acceptedRelease": "old",
                "nativeJobTerminal": False,
                "nativeMayBePartial": True,
                "jobStateFile": str(path),
            },
        )
        status_before = (self.course / "load-status.json").read_bytes()
        job_before = path.read_bytes()
        with patch("builtins.print") as output:
            preview.show_status(self.course, self.root / "state")
        self.assertTrue(
            any(
                "ID=91" in str(call) and "phase=running" in str(call)
                for call in output.call_args_list
            )
        )
        self.assertEqual((self.course / "load-status.json").read_bytes(), status_before)
        self.assertEqual(path.read_bytes(), job_before)

    def test_late_old_adapter_writes_cannot_overwrite_new_attempt_state(self):
        self.accepted()
        self.candidate()
        self.activate()
        old_path = self.job_path()
        old_job = json.loads(old_path.read_text())
        self.candidate("newer")
        self.loaded["jobSequenceId"] = "92"

        def new_job(command, **kwargs):
            self.assertNotEqual(self.job_path(), old_path)
            self.assertTrue(old_path.is_file())
            self.job("terminal", job_id="92", native_status="Success")
            # A disconnected old adapter is restricted to its original filename.
            old_job.update(phase="running")
            old_job.pop("nativeStatus")
            preview.write_json(old_path, old_job)
            return subprocess.CompletedProcess(
                command, 0, json.dumps(self.loaded) + "\n"
            )

        self.activate(new_job)
        self.assertEqual(preview.load_status(self.course)["jobSequenceId"], "92")
        self.assertEqual(json.loads(old_path.read_text())["jobSequenceId"], "91")
        self.assertEqual(
            preview.native_job_state(self.job_path(), "java")["nativeStatus"], "Success"
        )
        self.assertEqual((self.course / "site/index.html").read_text(), "newer")

    def test_legacy_fixed_job_state_resumes_existing_success_without_new_job(self):
        self.accepted()
        self.candidate()

        def timeout(command, **kwargs):
            self.job("terminal", native_status="Success")
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(timeout)
        status = preview.load_status(self.course)
        fixed = self.root / "state/jobs/preview-load-java.json"
        self.job_path().rename(fixed)
        status["jobStateFile"] = str(fixed)
        preview.write_json(self.course / "load-status.json", status)
        self.candidate("newer")
        _, run, _ = self.activate()
        self.assertIn("--resume", run.call_args.args[0])
        self.assertIn("/jobs/preview-load-java.json", run.call_args.args[0])
        self.assertEqual(self.job_path(), fixed)
        self.assertEqual((self.course / "active").readlink(), Path("releases/new"))

    def test_saved_job_path_rejects_other_course_escape_and_foreign_filename(self):
        state = self.root / "state"
        for filename in (
            "preview-load-system-practice.json",
            "foreign.json",
            "../preview-load-java.json",
            "preview-load-java-xyz.json",
        ):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                preview.saved_job_path(
                    {"jobStateFile": str(state / "jobs" / filename)}, state, "java"
                )

    def test_pending_job_cannot_resume_through_different_runtime(self):
        self.accepted()
        self.candidate()

        def timeout(command, **kwargs):
            self.job("running")
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(timeout)
        with self.assertRaisesRegex(ValueError, "state/project"):
            preview.activate(
                self.course,
                compose=["docker"],
                env={},
                course_name="java",
                state=self.root / "different",
                port=8088,
                origin="http://localhost",
                timeout=30,
                start=False,
                project="pl-preview-other",
            )

    def test_terminal_error_allows_new_prepared_candidate_on_next_invocation(self):
        self.accepted()
        self.candidate()

        def fail(command, **kwargs):
            self.job("terminal", native_status="Error")
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.activate(fail)
        self.candidate("newer")
        _, run, _ = self.activate()
        self.assertNotIn("--resume", run.call_args.args[0])
        self.assertEqual((self.course / "site/index.html").read_text(), "newer")

    def test_lock_symlink_is_rejected_without_touching_target(self):
        external = self.root / "external-lock"
        external.write_text("keep")
        (self.course / ".prepare.lock").symlink_to(external)
        with self.assertRaises(OSError):
            with preview.prepare_lock(self.course):
                self.fail("lock acquired")
        self.assertEqual(external.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
