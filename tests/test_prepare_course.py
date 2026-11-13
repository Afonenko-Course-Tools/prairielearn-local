"""Публикация сохраняет старый выпуск при отказе и изолирует controller bytes."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-course.py"
spec = importlib.util.spec_from_file_location("prepare_course", SCRIPT)
assert spec is not None and spec.loader is not None
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.course = self.root / "builds/java"
        self.course.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def result(self, release, marker):
        result = self.root / "builds-work/java" / release / "result"
        for name in (
            "native/infoCourse.json",
            "native/delivery.json",
            "site/index.html",
            "native-checks.json",
            "runtime-profiles.json",
        ):
            path = result / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(marker)
        seed = result / "native/questions/q/.pl-seed/start.sh"
        seed.parent.mkdir(parents=True)
        seed.write_text("#!/bin/sh\n")
        seed.chmod(0o755)
        return result

    def test_prepare_publishes_candidate_without_activating_first_release(self):
        prepare.publish(self.result(".prepare-one", "old"), self.course)
        self.assertEqual((self.course / "prepared").readlink(), Path("releases/one"))
        for name in (
            "active",
            "current",
            "site",
            "checks.json",
            "runtime-profiles.json",
        ):
            self.assertFalse((self.course / name).exists())
            self.assertFalse((self.course / name).is_symlink())
        self.assertEqual(
            (self.course / "prepared/native/questions/q/.pl-seed/start.sh")
            .stat()
            .st_mode
            & 0o777,
            0o755,
        )

    def test_prepare_preserves_legacy_accepted_release_and_numeric_values(self):
        prepare.publish(self.result(".prepare-one", "old"), self.course)
        (self.course / "active").symlink_to("releases/one")
        for name, target in {
            "current": "active/native",
            "site": "active/site",
            "checks.json": "active/native-checks.json",
            "runtime-profiles.json": "active/runtime-profiles.json",
        }.items():
            (self.course / name).symlink_to(target)
        (self.course / "loaded.json").write_text(
            '{"courseId": 12, "courseInstanceId": 23}'
        )
        prepare.publish(self.result(".prepare-two", "new"), self.course)
        self.assertEqual((self.course / "prepared").readlink(), Path("releases/two"))
        self.assertEqual((self.course / "active").readlink(), Path("releases/one"))
        self.assertEqual((self.course / "current/infoCourse.json").read_text(), "old")
        self.assertEqual((self.course / "site/index.html").read_text(), "old")
        self.assertEqual((self.course / "checks.json").read_text(), "old")
        self.assertEqual(
            (self.course / "loaded.json").read_text(),
            '{"courseId": 12, "courseInstanceId": 23}',
        )
        self.assertEqual((self.course / "current").readlink(), Path("active/native"))

    def test_incomplete_new_output_preserves_previous_release(self):
        prepare.publish(self.result(".prepare-one", "old"), self.course)
        original = (self.course / "prepared").readlink()
        result = self.result(".prepare-two", "broken")
        (result / "native/delivery.json").unlink()
        with self.assertRaises(ValueError):
            prepare.publish(result, self.course)
        self.assertEqual((self.course / "prepared").readlink(), original)
        self.assertEqual((self.course / "prepared/site/index.html").read_text(), "old")

    def test_release_name_cannot_overwrite_immutable_accepted_bytes(self):
        prepare.publish(self.result(".prepare-one", "accepted"), self.course)
        result = self.result(".prepare-one", "replacement")
        with self.assertRaisesRegex(ValueError, "Immutable release"):
            prepare.publish(result, self.course)
        self.assertEqual(
            (self.course / "prepared/site/index.html").read_text(), "accepted"
        )
        self.assertEqual((result / "native-checks.json").read_text(), "replacement")

    def test_prepare_and_up_mutations_share_nonblocking_regular_lock(self):
        with prepare.mutation_lock(self.course):
            with self.assertRaises(BlockingIOError):
                with prepare.mutation_lock(self.course):
                    self.fail("lock разрешил конкурирующую мутацию")
        lock = self.course / ".prepare.lock"
        lock.unlink()
        outside = self.root / "outside-lock"
        outside.write_text("unchanged")
        lock.symlink_to(outside)
        with self.assertRaises(OSError):
            with prepare.mutation_lock(self.course):
                self.fail("lock разрешил ссылку")
        self.assertEqual(outside.read_text(), "unchanged")

    def test_receive_publishes_prepared_without_replacing_accepted_site(self):
        from unittest.mock import patch

        prepare.publish(self.result(".prepare-one", "accepted"), self.course)
        (self.course / "active").symlink_to("releases/one")
        (self.course / "site").symlink_to("active/site")
        incoming = self.result(".prepare-incoming", "received")
        platform = self.root / "platform"
        platform.mkdir()
        args = [
            "prepare-course.py",
            "--course",
            "java",
            "--platform",
            str(platform),
            "--prepared",
            str(incoming),
            "--output-root",
            str(self.root / "builds"),
        ]
        with (
            patch.object(prepare.sys, "argv", args),
            patch.object(prepare, "run") as inventory,
        ):
            prepare.main()
        self.assertEqual(inventory.call_args.args[0][2:4], ["inventory", "--scope"])
        self.assertEqual(
            (self.course / "prepared/site/index.html").read_text(), "received"
        )
        self.assertEqual((self.course / "site/index.html").read_text(), "accepted")
        self.assertEqual((self.course / "active").readlink(), Path("releases/one"))

    def test_private_bytes_live_outside_runtime_mount(self):
        prepare.publish(self.result(".prepare-one", "private"), self.course)
        checks = self.course / "prepared/native-checks.json"
        self.assertTrue(checks.is_symlink())
        self.assertFalse(checks.resolve().is_relative_to(self.root / "builds"))
        self.assertEqual(checks.read_text(), "private")
        reports = self.course / "prepared/reports"
        self.assertTrue(reports.is_symlink())
        self.assertFalse(reports.resolve().is_relative_to(self.root / "builds"))
        self.assertFalse(
            any(
                p.is_file() and not p.is_symlink() and p.name == "native-checks.json"
                for p in (self.root / "builds").rglob("*")
            )
        )

    def test_releases_symlink_is_rejected_before_any_publication(self):
        result = self.result(".prepare-one", "private")
        outside = self.root / "outside"
        outside.mkdir()
        (self.course / "releases").symlink_to(outside)
        with self.assertRaises(ValueError):
            prepare.publish(result, self.course)
        self.assertFalse((self.course / "active").exists())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue((result / "native-checks.json").is_file())

    def test_private_symlink_into_runtime_is_rejected_before_mutation(self):
        result = self.result(".prepare-one", "private")
        public_private = self.root / "builds/private"
        public_private.mkdir()
        (self.root / "builds-checks").symlink_to(public_private)
        with self.assertRaises(ValueError):
            prepare.publish(result, self.course)
        self.assertEqual(list(public_private.iterdir()), [])
        self.assertTrue((result / "native-checks.json").is_file())

    def test_work_parent_symlink_is_rejected_before_mutation(self):
        result = self.result(".prepare-one", "private")
        outside = self.root / "outside-work"
        (self.root / "builds-work").rename(outside)
        (self.root / "builds-work").symlink_to(outside)
        with self.assertRaises(ValueError):
            prepare.publish(result, self.course)
        self.assertTrue((result / "native-checks.json").is_file())
        self.assertFalse((self.course / "active").exists())

    def test_failed_export_retains_source_and_resume_uses_export_only(self):
        from unittest.mock import patch

        source = self.root / "original"
        source.mkdir()
        (source / "Taskfile.yml").write_text("version: '3'\n")
        source_config = "subprojects: []\nwebsite:\n  site-url: https://example.org/course/\n  navbar:\n    left:\n      - href: https://example.org/course/theory/\n"
        (source / "_quarto.yml").write_text(source_config)
        (source / "index.qmd").write_text("source retained")
        package = source / "_extensions/org/example/_extension.yml"
        package.parent.mkdir(parents=True)
        package.write_text("title: installed package\n")
        for dependency in (".platform", ".ci/performance"):
            path = source / dependency / "source.txt"
            path.parent.mkdir(parents=True)
            path.write_text("external tool source")
        base_args = [
            "prepare-course.py",
            "--course",
            "java",
            "--platform",
            str(source),
            "--output-root",
            str(self.root / "builds"),
        ]

        def fail_export(command, *, cwd, env):
            result = cwd.parent / "result"
            (result / "site").mkdir(parents=True)
            (result / "site/index.html").write_text("student bytes")
            raise prepare.subprocess.CalledProcessError(1, command)

        with (
            patch.object(
                prepare.sys,
                "argv",
                base_args
                + ["--source", str(source), "--site-url", "http://localhost/"],
            ),
            patch.object(prepare.shutil, "which", return_value="/bin/true"),
            patch.object(prepare, "run", side_effect=fail_export),
        ):
            with self.assertRaises(prepare.subprocess.CalledProcessError):
                prepare.main()
        (work,) = (self.root / "builds-work/java").glob(".prepare-*")
        self.assertEqual((work / "source/index.qmd").read_text(), "source retained")
        self.assertFalse((work / "source/.platform").exists())
        self.assertFalse((work / "source/.ci").exists())
        self.assertEqual((source / "_quarto.yml").read_text(), source_config)
        self.assertEqual((work / "result/site/index.html").read_text(), "student bytes")
        frozen_metadata = (work / "source/_quarto.yml").read_bytes()
        frozen_profile = (work / "source/_quarto-preview.yml").read_bytes()
        self.assertEqual(
            (work / "source/_extensions/org/example/_extension.yml").read_text(),
            "title: installed package\n",
        )
        for extra in (["--site-url", "http://localhost:8099/"],):
            with (
                self.subTest(extra=extra),
                patch.object(
                    prepare.sys,
                    "argv",
                    base_args + ["--resume-export", str(work)] + extra,
                ),
                patch.object(prepare.shutil, "which", return_value="/bin/true"),
                patch.object(prepare, "run") as export,
            ):
                with self.assertRaisesRegex(ValueError, "свежий prepare"):
                    prepare.main()
                export.assert_not_called()
            self.assertEqual(
                (work / "source/_quarto.yml").read_bytes(), frozen_metadata
            )
            self.assertEqual(
                (work / "source/_quarto-preview.yml").read_bytes(), frozen_profile
            )
            self.assertEqual(
                (work / "result/site/index.html").read_text(), "student bytes"
            )
        commands = []

        def export_only(command, *, cwd, env):
            commands.append(command)
            result = cwd.parent / "result"
            for name in (
                "native/infoCourse.json",
                "native/delivery.json",
                "native-checks.json",
                "runtime-profiles.json",
            ):
                path = result / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")

        # Source package changes after render cannot affect frozen exporter retry.
        package.write_text("title: changed after render\n")
        # Legacy provenance from a previously frozen failed prepare remains read-only.
        import json

        context = work / ".prepare-context.json"
        self.assertEqual(
            json.loads(context.read_text()), {"site_url": "http://localhost/"}
        )
        context.write_text(
            json.dumps(
                {
                    "site_url": "http://localhost/",
                    "providers_root": str(self.root / "no-longer-existing-source"),
                }
            )
        )
        legacy_context = context.read_bytes()
        frozen_package = work / "source/_extensions/org/example/_extension.yml"
        self.assertEqual(frozen_package.read_text(), "title: installed package\n")
        with (
            patch.object(
                prepare.sys,
                "argv",
                base_args
                + ["--resume-export", str(work), "--site-url", "http://localhost"],
            ),
            patch.object(prepare.shutil, "which", return_value="/bin/true"),
            patch.object(prepare, "preview_profiles") as profiles,
            patch.object(prepare, "run", side_effect=export_only),
        ):
            prepare.main()
            profiles.assert_not_called()
        self.assertEqual([command[1] for command in commands], ["export"])
        self.assertEqual(context.read_bytes(), legacy_context)
        self.assertEqual(
            (self.course / "prepared/site/index.html").read_text(), "student bytes"
        )
        self.assertFalse((self.course / "active").exists())
        self.assertFalse((self.course / "current").exists())
        self.assertFalse((work / "source").exists())

    def test_resume_rejects_old_work_without_origin_provenance(self):
        work = self.root / "saved"
        work.mkdir()
        with self.assertRaisesRegex(ValueError, "свежий prepare"):
            prepare.resume_context(work, "http://localhost/")
        outside = self.root / "context.json"
        outside.write_text('{"site_url":"http://localhost/"}')
        (work / ".prepare-context.json").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "свежий prepare"):
            prepare.resume_context(work, "http://localhost/")

    def test_sibling_generated_roots_cannot_mutate_canonical_source(self):
        from unittest.mock import patch

        for suffix in ("work", "checks"):
            with self.subTest(suffix=suffix):
                output = self.root / ("overlap-" + suffix)
                source = self.root / (output.name + "-" + suffix)
                source.mkdir()
                (source / "Taskfile.yml").write_text("version: '3'\n")
                before = sorted(str(p.relative_to(source)) for p in source.rglob("*"))
                args = [
                    "prepare-course.py",
                    "--course",
                    "java",
                    "--platform",
                    str(source),
                    "--source",
                    str(source),
                    "--site-url",
                    "http://localhost/",
                    "--output-root",
                    str(output),
                ]
                with (
                    patch.object(prepare.sys, "argv", args),
                    patch.object(prepare.shutil, "which", return_value="/bin/true"),
                    patch.object(prepare.shutil, "copytree") as copy,
                ):
                    with self.assertRaises(SystemExit):
                        prepare.main()
                    copy.assert_not_called()
                self.assertEqual(
                    sorted(str(p.relative_to(source)) for p in source.rglob("*")),
                    before,
                )
                self.assertFalse(output.exists())

    def test_preview_profile_transports_only_this_courses_qrc_origins(self):
        import json
        import os
        import shutil
        import subprocess

        checkout = self.root / "profile-course"
        child = checkout / "tasks"
        child.mkdir(parents=True)
        canonical = "https://example.org/course/"
        external = "https://example.net/other/"
        root_config = {
            "project": {"type": "website"},
            "website": {
                "site-url": canonical,
                "navbar": {
                    "left": [{"text": "Root nav", "href": canonical + "tasks/"}]
                },
            },
            "subprojects": ["tasks"],
        }
        child_config = {
            "project": {"type": "book"},
            "book": {
                "site-url": canonical + "tasks/",
                "title": "Keep title",
                "chapters": ["index.qmd"],
                "sidebar": {"collapse-level": 2},
                "navbar": {
                    "title": "Keep navbar",
                    "logo-href": canonical + "index.html",
                    "left": [
                        {"text": "Theory label", "href": canonical + "theory/"},
                        {"text": "External label", "href": external},
                        {
                            "text": "Same host external",
                            "href": "https://example.org/unrelated/",
                        },
                    ],
                    "right": [
                        {"icon": "github", "href": "https://github.com/example/repo"},
                        {
                            "text": "Menu",
                            "menu": [
                                {"text": "Practice", "href": canonical + "practice/"}
                            ],
                        },
                    ],
                },
            },
            "reference-catalog": {
                "imports": {
                    "theory": {
                        "source": "catalog.json",
                        "namespace": "theory",
                        "base-url": canonical,
                    },
                    "practice": {
                        "source": "catalog.json",
                        "namespace": "practice",
                        "base-url": canonical + "practice/",
                    },
                    "external": {
                        "source": "other.json",
                        "namespace": "external",
                        "base-url": external,
                    },
                }
            },
        }
        (checkout / "_quarto.yml").write_text(json.dumps(root_config))
        (child / "_quarto.yml").write_text(json.dumps(child_config))
        author = "course-core-projection: author\ncourse:\n  view: full\n"
        (child / "_quarto-full.yml").write_text(author)
        (child / "index.qmd").write_text("# Test\n")
        original = (child / "_quarto.yml").read_bytes()
        prepare.preview_profiles(checkout, "http://127.0.0.1:8088/")
        profile = json.loads((child / "_quarto-preview.yml").read_text())
        self.assertEqual(
            profile["reference-catalog"]["imports"],
            {
                "theory": {"base-url": "http://127.0.0.1:8088/"},
                "practice": {"base-url": "http://127.0.0.1:8088/practice/"},
            },
        )
        import yaml

        disposable = yaml.safe_load((child / "_quarto.yml").read_text())
        navbar = disposable["book"]["navbar"]
        self.assertEqual(navbar["title"], "Keep navbar")
        self.assertEqual(navbar["logo-href"], "http://127.0.0.1:8088/index.html")
        self.assertEqual(
            navbar["left"][0],
            {"text": "Theory label", "href": "http://127.0.0.1:8088/theory/"},
        )
        self.assertEqual(navbar["left"][1]["href"], external)
        self.assertEqual(navbar["left"][2]["href"], "https://example.org/unrelated/")
        self.assertEqual(navbar["right"][0]["href"], "https://github.com/example/repo")
        self.assertEqual(
            navbar["right"][1]["menu"][0]["href"], "http://127.0.0.1:8088/practice/"
        )
        self.assertEqual(profile["book"], {"site-url": "http://127.0.0.1:8088/tasks/"})
        self.assertEqual(disposable["book"]["sidebar"], child_config["book"]["sidebar"])
        root_profile = json.loads((checkout / "_quarto-preview.yml").read_text())
        self.assertNotIn("navbar", root_profile["website"])
        root_metadata = yaml.safe_load((checkout / "_quarto.yml").read_text())
        self.assertEqual(
            root_metadata["website"]["navbar"]["left"][0]["href"],
            "http://127.0.0.1:8088/tasks/",
        )
        self.assertEqual(
            disposable["reference-catalog"], json.loads(original)["reference-catalog"]
        )
        self.assertEqual((child / "_quarto-full.yml").read_text(), author)
        if shutil.which("quarto"):
            result = subprocess.run(
                ["quarto", "inspect", str(child), "--profile", "full,preview"],
                env=dict(os.environ, XDG_CACHE_HOME=str(self.root / "cache")),
                check=True,
                capture_output=True,
                text=True,
            )
            config = json.loads(result.stdout)["config"]
            imports = config["reference-catalog"]["imports"]
            self.assertEqual(imports["theory"]["base-url"], "http://127.0.0.1:8088/")
            self.assertEqual(imports["theory"]["namespace"], "theory")
            self.assertEqual(imports["external"]["base-url"], external)
            self.assertEqual(config["course-core-projection"], "author")
            self.assertEqual(
                config["website"]["site-url"], "http://127.0.0.1:8088/tasks/"
            )
            self.assertEqual(config["book"]["site-url"], "http://127.0.0.1:8088/tasks/")
            self.assertEqual(
                config["course-navigation"]["course-url"], "http://127.0.0.1:8088/"
            )
            effective_navbar = config["website"]["navbar"]
            self.assertEqual(len(effective_navbar["left"]), 3)
            self.assertEqual(effective_navbar["title"], "Keep navbar")
            self.assertEqual(
                effective_navbar["logo-href"], "http://127.0.0.1:8088/index.html"
            )
            self.assertEqual(
                effective_navbar["left"][0]["href"], "http://127.0.0.1:8088/theory/"
            )
            self.assertEqual(effective_navbar["left"][1]["href"], external)

    def test_course_export_receives_local_functional_profile(self):
        import os
        import shutil
        import subprocess

        task = shutil.which("go-task")
        if task is None:
            self.skipTest("go-task отсутствует")
        binary = self.root / "bin"
        binary.mkdir()
        python = binary / "python3"
        python.write_text(
            '#!/bin/sh\nprintf "%s" "${QUARTO_PROFILE-unset}" > "$PROFILE_LOG"\n'
        )
        python.chmod(0o755)
        platform = self.root / "platform"
        platform.mkdir()
        (platform / "runtime-profiles.json").write_text("{}")
        courses = {
            name: Path(os.environ[name])
            for name in ("JAVA_ROOT", "SP_ROOT")
            if os.environ.get(name)
        }
        if len(courses) != 2:
            self.skipTest("Проверка course export требует явные JAVA_ROOT и SP_ROOT")
        for course, checkout in courses.items():
            for local in ("0", "1"):
                with self.subTest(course=course, local=local):
                    output = self.root / (course + local)
                    log = self.root / "profile.log"
                    env = dict(
                        os.environ,
                        PATH=str(binary) + os.pathsep + os.environ["PATH"],
                        PROFILE_LOG=str(log),
                        COURSE_PREVIEW_PROFILE=local,
                        QUARTO_PROFILE="custom",
                    )
                    subprocess.run(
                        [
                            task,
                            "--dir",
                            str(checkout),
                            "export",
                            "BUILD_DIR=" + str(output),
                            "PLATFORM_ROOT=" + str(platform),
                        ],
                        env=env,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        log.read_text(), "preview" if local == "1" else "custom"
                    )

    def test_normal_prepare_preserves_source_symlinks_for_downstream_guards(self):
        import stat
        from unittest.mock import patch

        source = self.root / "symlink-source"
        (source / "materials").mkdir(parents=True)
        (source / "Taskfile.yml").write_text("version: '3'\n")
        (source / "_quarto.yml").write_text("subprojects: []\n")
        outside = self.root / "outside-source"
        outside.mkdir()
        (outside / "linked.txt").write_text("SYNTHETIC_OUTSIDE_BYTES")
        file_link = source / "materials/linked.txt"
        file_link.symlink_to(outside / "linked.txt")
        (source / "materials/linked-dir").symlink_to(outside, target_is_directory=True)
        args = [
            "prepare-course.py",
            "--course",
            "java",
            "--platform",
            str(source),
            "--source",
            str(source),
            "--site-url",
            "http://localhost/",
            "--output-root",
            str(self.root / "builds"),
        ]
        observed = []

        def source_guard(command, *, cwd, env):
            for relative in ("materials/linked.txt", "materials/linked-dir"):
                candidate = cwd / relative
                observed.append(stat.S_ISLNK(candidate.lstat().st_mode))
            # Downstream lstat guards can reject links instead of accepting
            # copied outside bytes as ordinary source material.
            raise prepare.subprocess.CalledProcessError(1, command)

        with (
            patch.object(prepare.sys, "argv", args),
            patch.object(prepare.shutil, "which", return_value="/bin/true"),
            patch.object(prepare, "run", side_effect=source_guard),
        ):
            with self.assertRaises(prepare.subprocess.CalledProcessError):
                prepare.main()
        self.assertEqual(observed, [True, True])
        (work,) = (self.root / "builds-work/java").glob(".prepare-*")
        retained = work / "source/materials/linked.txt"
        self.assertTrue(retained.is_symlink())
        self.assertEqual(retained.readlink(), outside / "linked.txt")
        self.assertTrue(file_link.is_symlink())
        self.assertEqual(
            (outside / "linked.txt").read_text(), "SYNTHETIC_OUTSIDE_BYTES"
        )
        self.assertFalse((self.course / "active").exists())

    def test_normal_prepare_rejects_metadata_symlinks_without_outside_writes(self):
        from unittest.mock import patch

        for relative in (
            "_quarto-preview.yml",
            "_quarto.yml",
            "tasks/_quarto-preview.yml",
            "tasks/_quarto.yml",
        ):
            with self.subTest(relative=relative):
                case = self.root / relative.replace("/", "-").replace(".", "_")
                source = case / "source"
                (source / "tasks").mkdir(parents=True)
                (source / "Taskfile.yml").write_text("version: '3'\n")
                metadata = (
                    "project: {type: website}\n"
                    "website:\n  site-url: https://example.org/course/\n"
                    "  navbar:\n    left: [{href: https://example.org/course/tasks/}]\n"
                )
                (source / "_quarto.yml").write_text(metadata + "subprojects: [tasks]\n")
                (source / "tasks/_quarto.yml").write_text(metadata)
                outside = case / "outside.yml"
                outside.write_text(
                    metadata
                    + ("subprojects: [tasks]\n" if relative == "_quarto.yml" else "")
                )
                original = outside.read_bytes()
                target = source / relative
                target.unlink(missing_ok=True)
                target.symlink_to(outside)
                args = [
                    "prepare-course.py",
                    "--course",
                    "java",
                    "--platform",
                    str(source),
                    "--source",
                    str(source),
                    "--site-url",
                    "http://localhost/",
                    "--output-root",
                    str(case / "builds"),
                ]
                with (
                    patch.object(prepare.sys, "argv", args),
                    patch.object(prepare.shutil, "which", return_value="/bin/true"),
                    patch.object(prepare, "run") as build,
                ):
                    with self.assertRaises(ValueError):
                        prepare.main()
                    build.assert_not_called()
                self.assertEqual(outside.read_bytes(), original)
                self.assertTrue(target.is_symlink())
                (work,) = (case / "builds-work/java").glob(".prepare-*")
                retained = work / "source"
                self.assertTrue((retained / relative).is_symlink())
                if relative.startswith("tasks/"):
                    self.assertFalse((retained / "_quarto-preview.yml").exists())
                    self.assertEqual(
                        (retained / "_quarto.yml").read_text(),
                        metadata + "subprojects: [tasks]\n",
                    )
