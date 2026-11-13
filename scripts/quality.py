#!/usr/bin/env python3
"""Проверки собственных файлов Local; контейнеры и пользовательский state не запускаются."""

import argparse
import json
import os
from pathlib import Path
import subprocess  # nosec B404 # explicit argv only, no shell
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def owned_files(root: Path) -> list[str]:
    """Git учитывает новые файлы, исключает ignored state/packages и submodules."""
    result = subprocess.run(  # nosec B603, B607 # fixed installed git argv
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        name
        for name in set(result.stdout.split("\0"))
        if name and (root / name).is_file() and not (root / name).is_symlink()
    )


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)  # nosec B603 # trusted quality CLI argv, no shell


def quality(mode: str) -> None:
    files = owned_files(ROOT)
    python = [name for name in files if name.endswith(".py")]
    shell = [name for name in files if name.endswith((".sh", ".bash"))]
    yaml = [name for name in files if name.endswith((".yml", ".yaml"))]
    javascript = [name for name in files if name.endswith((".js", ".mjs", ".cjs"))]
    prettier = [
        name
        for name in files
        if name.endswith(
            (
                ".mjs",
                ".js",
                ".cjs",
                ".ts",
                ".mts",
                ".cts",
                ".json",
                ".yml",
                ".yaml",
                ".md",
            )
        )
        and name != "package-lock.json"
    ]
    # npm scripts используют локальные зависимости; остальные CLI предоставляет PATH.
    env = dict(
        os.environ,
        PATH=str(ROOT / "node_modules/.bin") + os.pathsep + os.environ["PATH"],
    )
    if mode == "format":
        run(["ruff", "format", *python])
        run(["shfmt", "-w", "-i", "2", *shell])
        run(["prettier", "--write", *prettier], env=env)
        run(["prettier", "--write", "--parser", "yaml", ".yamllint"], env=env)
        return
    run(["ruff", "check", "--select", "E4,E7,E9,F,B", *python])
    run(["ruff", "format", "--check", *python])
    run(["pyright", "--warnings", *python])
    with tempfile.TemporaryDirectory(prefix="local-typecheck-") as temporary:
        config = Path(temporary) / "tsconfig.json"
        config.write_text(
            json.dumps(
                {
                    "extends": str(ROOT / "jsconfig.json"),
                    "include": [],
                    "files": [
                        str(ROOT / name)
                        for name in files
                        if name.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"))
                    ],
                    "compilerOptions": {
                        "typeRoots": [str(ROOT / "node_modules/@types")]
                    },
                }
            )
        )
        run(["tsc", "-p", str(config)], env=env)
    run(["bandit", "-q", *python])
    run(["shellcheck", *shell])
    run(["shfmt", "-d", "-i", "2", *shell])
    run(["prettier", "--check", *prettier], env=env)
    run(["prettier", "--check", "--parser", "yaml", ".yamllint"], env=env)
    run(["yamllint", "--strict", *yaml])
    workflows = [name for name in yaml if name.startswith(".github/workflows/")]
    if workflows:
        run(["actionlint", *workflows])
    with tempfile.TemporaryDirectory(prefix="local-quality-") as temporary:
        isolated = Path(temporary)
        ansible_env = dict(
            os.environ,
            ANSIBLE_HOME=str(isolated / "ansible"),
            ANSIBLE_LOCAL_TEMP=str(isolated / "ansible-tmp"),
            XDG_CACHE_HOME=str(isolated / "cache"),
        )
        playbooks = [name for name in yaml if name.startswith("ansible/")]
        if playbooks:
            run(["ansible-lint", "--offline", "--strict", *playbooks], env=ansible_env)
        compose_check(files, isolated)
    for name in files:
        if name.endswith(".php"):
            run(["php", "-l", name])
        if Path(name).name == "Dockerfile" or Path(name).name.startswith("Dockerfile."):
            run(["hadolint", name])
    for name in javascript:
        run(["node", "--check", name])
    run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-v",
        ]
    )
    node_tests = [
        name for name in javascript if name.startswith("tests/") and ".test." in name
    ]
    if node_tests:
        run(["node", "--test", *node_tests])


def compose_check(files: list[str], isolated: Path) -> None:
    """Только config; не читаем .env, DB, ключи, socket и пользовательские каталоги."""
    platform = Path(
        os.environ.get("PLATFORM_ROOT", str(ROOT / "deps/platform"))
    ).resolve()
    if not (platform / "compose/runtime.yml").is_file():
        raise ValueError(
            "Инициализируйте deps/platform или задайте PLATFORM_ROOT для Compose config"
        )
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "HOME", "DOCKER_CONFIG")
    }
    env.update(
        {
            "PLATFORM_ROOT": str(platform),
            "PREVIEW_PLATFORM_ROOT": str(platform),
            "COMPOSE_PROJECT_NAME": "local-quality",
            "PWD": str(ROOT),
            "STATE_DIR": str(isolated / "state"),
            "HOST_JOBS_DIR": str(isolated / "jobs"),
            "PREVIEW_JOBS_DIR": str(isolated / "preview-jobs"),
            "PREVIEW_PORT": "28088",
            "PREVIEW_OUTPUT_ROOT": str(isolated / "output"),
            "PREVIEW_STATE_DIR": str(isolated / "preview"),
            "PL_CONFIG_FILE": str(isolated / "native-config.json"),
            "BRIDGE_CONFIG_DIR": str(isolated / "bridge"),
            "GATEWAY_CONFIG_DIR": str(isolated / "gateway"),
            "WORKSPACE_DOCKER_SOCKET": str(isolated / "unused.sock"),
            "SITE_ROOT": str(isolated / "site"),
        }
    )
    for name in files:
        if Path(name).name.startswith("compose") and name.endswith((".yml", ".yaml")):
            command = [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "--project-name",
                "local-quality",
            ]
            if name != "compose.yml" and name != "compose.preview.yml":
                command += ["-f", "compose.yml"]
            run([*command, "-f", name, "config", "--quiet"], env=env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "format"), default="check", nargs="?")
    try:
        quality(parser.parse_args().mode)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Проверки Local остановлены: {error}", file=sys.stderr)
        raise SystemExit(1) from error
