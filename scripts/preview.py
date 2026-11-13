#!/usr/bin/env python3
"""Отдельный loopback preview готового сайта и native dev-курса."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess  # nosec B404 # explicit argv process API; no shell
import sys
import time
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"java": 8088, "system-practice": 8089}


def real_directory(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Нужен абсолютный нормализованный путь: " + str(path))
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise ValueError("Небезопасный каталог preview: " + str(part))


def plain_file(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Небезопасный файл preview: " + str(path))


def write_json(path: Path, value: dict) -> None:
    plain_file(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + path.name + "-", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def prepare_lock(course: Path):
    real_directory(course)
    if not course.is_dir():
        raise ValueError("Нет подготовленного курса; сначала выполните prepare")
    descriptor = os.open(
        course / ".prepare.lock",
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("prepare lock должен быть обычным файлом")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "Курс занят prepare или native load; повторите позже"
            ) from error
        yield
    finally:
        os.close(descriptor)


def release_link(course: Path, name: str) -> str | None:
    path = course / name
    if not path.is_symlink():
        if path.exists():
            raise ValueError(f"{name} должен быть ссылкой на generated release")
        return None
    target = Path(os.readlink(path))
    if (
        target.is_absolute()
        or len(target.parts) != 2
        or target.parts[0] != "releases"
        or target.parts[1] in (".", "..")
    ):
        raise ValueError("Чужая ссылка " + str(path))
    # Проверяем и ссылки в родителях, не только итоговый resolve.
    real_directory(course / target)
    if not (course / target).is_dir():
        raise ValueError("Не найден release: " + str(path))
    return target.parts[1]


def validate_release(course: Path, release: str) -> None:
    root = course / "releases" / release
    for directory in (root / "native", root / "site"):
        real_directory(directory)
    for name in ("native/infoCourse.json", "site/index.html"):
        path = root / name
        plain_file(path)
        if not path.is_file():
            raise ValueError("Не найден готовый вход: " + str(path))


def validate_aliases(course: Path) -> None:
    site = course / "site"
    if (site.is_symlink() and os.readlink(site) != "active/site") or (
        not site.is_symlink() and site.exists()
    ):
        raise ValueError("Чужой output site: " + str(site))
    current = course / "current"
    if current.is_symlink():
        target = Path(os.readlink(current))
        if target != Path("active/native"):
            if (
                target.is_absolute()
                or len(target.parts) != 3
                or target.parts[0] != "releases"
                or target.parts[2] != "native"
                or target.parts[1] in (".", "..")
            ):
                raise ValueError("Чужой output current: " + str(current))
            real_directory(course / target)
    elif current.exists():
        raise ValueError("current должен быть ссылкой на native release")


def replace_link(course: Path, name: str, target: str) -> None:
    # Случайное имя исключает следование заранее созданному pending symlink.
    pending = course / ("." + name + "-" + secrets.token_hex(8))
    try:
        pending.symlink_to(target)
        pending.replace(course / name)
        sync_directory(course)
    finally:
        pending.unlink(missing_ok=True)


def load_status(course: Path) -> dict | None:
    path = course / "load-status.json"
    plain_file(path)
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("outcome") not in (
        "loading",
        "succeeded",
        "failed",
    ):
        raise ValueError("Некорректный load-status.json")
    return value


def native_job_state(path: Path, course_name: str) -> dict | None:
    real_directory(path.parent)
    plain_file(path)
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("coursePath") != f"/course/{course_name}/current"
        or value.get("phase") not in ("intent", "running", "terminal")
    ):
        raise ValueError("Некорректное состояние native job: " + str(path))
    job_id = value.get("jobSequenceId")
    if job_id is not None and (
        not isinstance(job_id, str) or not re.fullmatch(r"[1-9][0-9]*", job_id)
    ):
        raise ValueError("Некорректный native job ID: " + str(path))
    if value["phase"] in ("running", "terminal") and job_id is None:
        raise ValueError("Потерян native job ID: " + str(path))
    return value


def native_terminal(job: dict | None) -> bool:
    return bool(
        job
        and job.get("phase") == "terminal"
        and job.get("nativeStatus") in ("Success", "Error", "Stopped")
    )


def saved_job_path(status: dict, state_dir: Path, course_name: str) -> Path:
    value = status.get("jobStateFile")
    if not isinstance(value, str):
        raise ValueError("Неизвестен state прежнего native job; требуется диагностика")
    path = Path(value)
    pattern = rf"preview-load-{re.escape(course_name)}(?:-[0-9a-f]{{32}})?\.json"
    if path.parent != state_dir / "jobs" or not re.fullmatch(pattern, path.name):
        raise ValueError(
            "Незавершённый native job относится к другому или неизвестному state/project; требуется диагностика прежней попытки"
        )
    real_directory(path.parent)
    return path


def pending_load(status: dict | None, job: dict | None) -> bool:
    successful_unaccepted = bool(
        job is not None
        and native_terminal(job)
        and job.get("nativeStatus") == "Success"
        and not job.get("validationError")
    )
    return bool(
        status
        and status["outcome"] != "succeeded"
        and (
            status.get("nativeJobTerminal") is not True
            or successful_unaccepted
            or (status["outcome"] == "loading" and job is not None)
        )
    )


def show_status(course: Path, state_dir: Path | None = None) -> dict | None:
    real_directory(course)
    prepared = release_link(course, "prepared")
    accepted = release_link(course, "active")
    validate_aliases(course)
    state = load_status(course)
    print(f"Preview: prepared={prepared or '—'}, accepted={accepted or '—'}")
    if state:
        print(
            f"Native load: {state['outcome']}; candidate={state.get('candidateRelease')}; accepted={state.get('acceptedRelease')}"
        )
        if state["outcome"] != "succeeded":
            print(
                "Native DB может быть частично обновлена; прежний student site сохранён."
            )
            job = (
                native_job_state(
                    saved_job_path(state, state_dir, course.name), course.name
                )
                if state_dir and state.get("jobStateFile")
                else None
            )
            if job:
                print(
                    f"Native job: ID={job.get('jobSequenceId', 'неизвестен')}; phase={job['phase']}; nativeStatus={job.get('nativeStatus', 'неизвестен')}"
                )
            if pending_load(state, job):
                job_id = (job or {}).get(
                    "jobSequenceId", state.get("jobSequenceId", "неизвестен")
                )
                print(
                    f"Native попытка ещё не принята; up/load продолжит только прежний job. ID: {job_id}; state: {state.get('jobStateFile', 'неизвестен')}"
                )
            else:
                print(
                    "Native job завершён; следующий up/load может запустить новую попытку."
                )
    return state


def run(
    command: list[str], *, env: dict[str, str], capture: bool = False
) -> subprocess.CompletedProcess[str]:
    start = time.monotonic()
    with subprocess.Popen(  # nosec B603 # trusted CLI argv assembled by Local; shell=False
        command, env=env, text=True, stdout=subprocess.PIPE if capture else None
    ) as process:
        while True:
            try:
                stdout, _ = process.communicate(timeout=10)
                break
            except subprocess.TimeoutExpired:
                print(
                    f"Preview: процесс выполняется, {int(time.monotonic() - start)} с",
                    flush=True,
                )
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout
            )
        return subprocess.CompletedProcess(command, process.returncode, stdout)


def prepare_config(state: Path, course: str, port: int) -> None:
    """Ключи принадлежат этому preview и сохраняются при повторном up."""
    real_directory(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_dir = state / "pl"
    real_directory(config_dir)
    config_dir.mkdir(exist_ok=True, mode=0o700)
    path = config_dir / "config.json"
    plain_file(path)
    config: dict[str, object]
    if path.exists():
        config = json.loads(path.read_text())
        if (
            not isinstance(config, dict)
            or config.get("devMode") is not True
            or config.get("hasShib") is not False
        ):
            raise ValueError(
                "State содержит другой runtime; нужен отдельный preview state"
            )
    else:
        config = {
            "secretKey": secrets.token_hex(32),
            "databaseEncryptionKey": secrets.token_hex(32),
        }
    config.update(
        {
            "devMode": True,
            "hasShib": False,
            "hostname": "127.0.0.1",
            "serverCanonicalHost": f"http://127.0.0.1:{port}",
            "cookieDomain": None,
            "courseDirs": [f"/course/{course}/current"],
            "coursesRoot": "/course",
            "trustProxy": 1,
            "externalGradingUseAws": False,
            "externalGradingPullImagesFromDockerHub": False,
            "workersCount": 1,
            "fileStoreStorageTypeDefault": "FileSystem",
            "workspaceEnable": False,
        }
    )
    write_json(path, config)
    real_directory(state / "jobs")
    (state / "jobs").mkdir(exist_ok=True)
    plain_file(state / "nginx.conf")
    (state / "nginx.conf").write_text(
        (ROOT / "config/nginx.preview.conf")
        .read_text()
        .replace("PREVIEW_COURSE", course)
    )


def wait_http(origin: str, timeout: int, *, site: bool = True) -> None:
    start = time.monotonic()
    next_message = 0
    while time.monotonic() - start < timeout:
        try:
            for route in (
                ("/pl/webhooks/ping", "/index.html") if site else ("/pl/webhooks/ping",)
            ):
                with urlopen(origin + route, timeout=5) as response:  # nosec B310 # caller constructs loopback HTTP origin; no file URLs
                    if response.status != 200:
                        raise ValueError("Неожиданный HTTP status readiness")
            return
        except (URLError, TimeoutError, ConnectionError):
            if time.monotonic() >= next_message:
                print(
                    f"Preview readiness: ожидание PL и сайта, {int(time.monotonic() - start)} с",
                    flush=True,
                )
                next_message = time.monotonic() + 10
            time.sleep(1)
    raise ValueError("Preview readiness: истекло время ожидания PL и student-сайта")


def activate(
    course: Path,
    *,
    compose: list[str],
    env: dict[str, str],
    course_name: str,
    state: Path,
    port: int,
    origin: str,
    timeout: int,
    start: bool,
    project: str,
) -> dict:
    """Один native job под prepare-lock, затем одна atomic замена accepted release."""
    with prepare_lock(course):
        accepted = release_link(course, "active")
        prior = load_status(course)
        jobs = state / "jobs"
        real_directory(jobs)
        job_path = None
        job = None
        if prior and prior["outcome"] != "succeeded":
            job_path = saved_job_path(prior, state, course_name)
            job = native_job_state(job_path, course_name)
        elif prior is None:
            # Старый fixed state без Local candidate не разрешает обход незавершённого job.
            legacy = native_job_state(
                jobs / f"preview-load-{course_name}.json", course_name
            )
            if legacy is not None and not native_terminal(legacy):
                raise ValueError(
                    "Найден прежний native job без Local release; требуется диагностика"
                )
        # Terminal Success ещё не означает, что Local успел принять этот release.
        # После сбоя commit повторно читаем receipt того же job, без нового POST.
        resume = pending_load(prior, job)
        if resume:
            if prior is None or job_path is None:
                raise ValueError("Потерян state незавершённого native job")
            if prior.get("runtimeProject") != project:
                raise ValueError(
                    "Незавершённый native job относится к другому или неизвестному state/project; требуется диагностика прежней попытки"
                )
            candidate = prior.get("candidateRelease")
            if not isinstance(candidate, str) or not re.fullmatch(
                r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", candidate
            ):
                raise ValueError(
                    "Неизвестен release незавершённого native job; требуется диагностика"
                )
            if not job or not job.get("jobSequenceId"):
                raise ValueError(
                    f"Native job ID неизвестен; повторный POST запрещён, нужна диагностика: {job_path}"
                )
            if (
                not (course / "current").is_symlink()
                or os.readlink(course / "current") != f"releases/{candidate}/native"
            ):
                raise ValueError(
                    "current не соответствует незавершённому native job; переключение запрещено"
                )
        else:
            if job is not None and not native_terminal(job):
                raise ValueError(
                    f"Предыдущий native job ещё не подтверждён как terminal; переключение запрещено: {job_path}"
                )
            candidate = release_link(course, "prepared") or accepted
            # Каждый новый attempt имеет собственный файл: запоздавший старый adapter
            # физически не может переписать запись следующего native job.
            job_path = jobs / f"preview-load-{course_name}-{secrets.token_hex(16)}.json"
            plain_file(job_path)
            if job_path.exists():
                raise ValueError("Job state нового attempt уже существует")
        if job_path is None:
            raise ValueError("Не задан state native job")
        if candidate is None:
            raise ValueError("Нет подготовленного release; сначала выполните prepare")
        if accepted is not None:
            validate_release(course, accepted)
        validate_release(course, candidate)
        validate_aliases(course)
        if start:
            prepare_config(state, course_name, port)
        else:
            jobs.mkdir(parents=True, exist_ok=True)
        status = {
            "outcome": "loading",
            "candidateRelease": candidate,
            "acceptedRelease": accepted,
            "nativeMayBePartial": True,
            "nativeJobTerminal": native_terminal(job) if resume else True,
            "jobStateFile": str(job_path),
            "runtimeProject": project,
        }
        if resume and job is not None:
            status["jobSequenceId"] = job["jobSequenceId"]
        write_json(course / "load-status.json", status)
        try:
            # Стабильный путь хранится в native DB; target может указывать на candidate.
            if not resume:
                replace_link(course, "current", f"releases/{candidate}/native")
            if not (course / "site").is_symlink():
                (course / "site").symlink_to("active/site")
            if start:
                print(
                    "Preview: запуск отдельного native dev runtime и student-сайта",
                    flush=True,
                )
                run(
                    compose + ["up", "-d", "--wait", "--wait-timeout", str(timeout)],
                    env=env,
                )
            wait_http(origin, timeout, site=False)
            print(
                "Preview: штатный native loadFromDisk, ожидание server job", flush=True
            )
            # До exec фиксируем неопределённость: потерянный HTTP response не разрешает новый POST.
            status["nativeJobTerminal"] = False
            write_json(course / "load-status.json", status)
            command = compose + [
                "exec",
                "-T",
                "-w",
                "/PrairieLearn/apps/prairielearn",
                "pl",
                "node",
                "tools/dev-load-course.mjs",
                "--path",
                f"/course/{course_name}/current",
                "--timeout",
                str(timeout),
                "--job-state",
                f"/jobs/{job_path.name}",
            ]
            if resume:
                command.append("--resume")
            result = run(command, env=env, capture=True)
            print(result.stdout, end="")
            job = native_job_state(job_path, course_name)
            if (
                job is None
                or not native_terminal(job)
                or job.get("nativeStatus") != "Success"
            ):
                raise ValueError(
                    "Native job не подтвердил terminal Success; accepted release не переключён"
                )
            try:
                loaded = json.loads(result.stdout.strip().splitlines()[-1])
                if (
                    not isinstance(loaded, dict)
                    or "courseId" not in loaded
                    or not isinstance(loaded.get("instances"), list)
                ):
                    raise ValueError("Не найден результат native server job")
                if loaded.get("jobSequenceId") != job["jobSequenceId"]:
                    raise ValueError(
                        "Результат не соответствует сохранённому native job ID"
                    )
                for instance in loaded["instances"]:
                    if (
                        not isinstance(instance, dict)
                        or not {"id", "short_name"} <= instance.keys()
                    ):
                        raise ValueError("Неполный результат native server job")
            except (IndexError, json.JSONDecodeError) as error:
                raise ValueError("Не найден результат native server job") from error
            # site всегда следует active: Nginx видит выпуск только после успеха job.
            replace_link(course, "active", f"releases/{candidate}")
            status.update(
                outcome="succeeded", acceptedRelease=candidate, nativeMayBePartial=False
            )
            status.update(nativeJobTerminal=True, jobSequenceId=job["jobSequenceId"])
            write_json(course / "load-status.json", status)
        except BaseException:
            # Ошибка записи диагностики не должна скрывать первичную ошибку native job.
            try:
                job = native_job_state(job_path, course_name)
                status.update(
                    outcome="failed", acceptedRelease=release_link(course, "active")
                )
                if job is not None:
                    status["nativeJobTerminal"] = native_terminal(job)
                    if job.get("jobSequenceId"):
                        status["jobSequenceId"] = job["jobSequenceId"]
                write_json(course / "load-status.json", status)
            except (ValueError, OSError) as diagnostic_error:
                print(
                    f"Не удалось сохранить native load status: {diagnostic_error}",
                    file=sys.stderr,
                )
            print(
                "Native load не завершён: DB может быть частично обновлена; student site остаётся на accepted release.",
                file=sys.stderr,
            )
            raise
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "ready", "status", "load", "down"])
    parser.add_argument("--course", choices=PORTS, default="java")
    parser.add_argument("--output-root", type=Path, default=ROOT / "state/builds")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--platform", type=Path, default=ROOT / "deps/platform")
    parser.add_argument("--port", type=int)
    parser.add_argument("--project")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    course = args.course
    port = args.port or PORTS[course]
    if not 1024 <= port <= 65535 or not 1 <= args.timeout <= 3600:
        parser.error("Недопустимый port или timeout")
    project = args.project or f"pl-preview-{course}"
    if not re.fullmatch(r"pl-preview-[a-z0-9][a-z0-9-]*", project):
        parser.error("Project должен начинаться с pl-preview-")
    output = args.output_root.absolute()
    state = (args.state_dir or ROOT / f"state/preview-{course}").absolute()
    platform = args.platform.absolute()
    origin = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        PREVIEW_OUTPUT_ROOT=str(output),
        PREVIEW_STATE_DIR=str(state),
        PREVIEW_JOBS_DIR=str(state / "jobs"),
        PREVIEW_PLATFORM_ROOT=str(platform),
        PREVIEW_PORT=str(port),
    )
    # PL_IMAGE принадлежит production; preview override остаётся независимым.
    env["PL_IMAGE"] = os.environ.get("PL_PREVIEW_IMAGE", "")
    # Не читать production .env; preview имеет собственный project и volumes.
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(ROOT / "compose.preview.yml"),
    ]
    if args.command == "down":
        run(compose + ["down"], env=env)
        return
    if args.command == "status":
        run(compose + ["ps"], env=env)
        show_status(output / course, state)
        return
    if args.command == "ready":
        status = show_status(output / course, state)
        if status and status["outcome"] != "succeeded":
            raise ValueError("Native load не завершён успешно; повторите up/load")
        accepted = release_link(output / course, "active")
        if accepted is None:
            raise ValueError("Нет accepted release; сначала выполните up/load")
        validate_release(output / course, accepted)
        wait_http(origin, args.timeout)
        return
    if not (platform / "tools/dev-load-course.mjs").is_file():
        raise ValueError("Не найден tools/dev-load-course.mjs в Platform")
    loaded = activate(
        output / course,
        compose=compose,
        env=env,
        course_name=course,
        state=state,
        port=port,
        origin=origin,
        timeout=args.timeout,
        start=args.command == "up",
        project=project,
    )
    # Штатный syncFromDisk сам очищает element/extensions cache в процессе PL.
    wait_http(origin, args.timeout)
    print(f"Сайт: {origin}/")
    print(f"Курс: {origin}/pl/course/{loaded['courseId']}/course_admin/instances")
    for instance in loaded["instances"]:
        print(
            f"Работы ({instance['short_name']}): {origin}/pl/course_instance/{instance['id']}/assessments"
        )
    print(
        "Вход: штатный PrairieLearn dev-вход; смена роли доступна в native панели пользователя."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Preview остановлен: {error}", file=sys.stderr)
        raise SystemExit(1) from error
