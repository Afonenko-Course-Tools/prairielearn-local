#!/usr/bin/env python3
"""Собрать disposable checkout и опубликовать только успешный готовый выпуск."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print('+ ' + ' '.join(command), flush=True)
    start = time.monotonic()
    with subprocess.Popen(command, cwd=cwd, env=env) as process:
        while True:
            try:
                status = process.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print(f'prepare: сборка выполняется, {int(time.monotonic()-start)} с', flush=True)
        if status:
            raise subprocess.CalledProcessError(status, command)


def normalized_site_url(site_url: str) -> str:
    parsed = urlparse(site_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('--site-url требует абсолютный HTTP(S) URL без query/fragment')
    return site_url.rstrip('/') + '/'


def preview_profiles(checkout: Path, site_url: str) -> None:
    """Штатный Quarto profile существует только в одноразовом checkout."""
    base = normalized_site_url(site_url)
    import yaml

    def metadata_file(path, required=False):
        real_directory(path.parent)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Небезопасный metadata/config path: ' + str(path))
        if required and not path.is_file():
            raise ValueError('Нет metadata/config файла: ' + str(path))

    # Preflight всего набора предшествует даже первой generated записи.
    metadata_file(checkout / '_quarto.yml', required=True)
    metadata_file(checkout / '_quarto-preview.yml')
    config = yaml.safe_load((checkout / '_quarto.yml').read_text())
    children = []
    for name in config.get('subprojects', []):
        if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Неподдерживаемый subproject: ' + repr(name))
        child = checkout / name
        metadata_file(child / '_quarto.yml', required=True)
        metadata_file(child / '_quarto-preview.yml')
        children.append((name, child, yaml.safe_load((child / '_quarto.yml').read_text())))
    canonical = config.get('website', {}).get('site-url', '').rstrip('/')

    def local_url(value):
        if not isinstance(value, str) or not canonical:
            return value
        if value.rstrip('/') == canonical:
            return base
        if value.startswith(canonical + '/'):
            return base + value[len(canonical) + 1:]
        return value

    def local_imports(project):
        # Переносим только явно объявленные QRC imports внутри URL этого курса.
        # Внешние источники и URL в учебной прозе сохраняют авторское значение.
        imports = project.get('reference-catalog', {}).get('imports', {})
        return {name: {'base-url': local_url(value['base-url'])}
                for name, value in imports.items()
                if isinstance(value, dict) and 'base-url' in value
                and local_url(value['base-url']) != value['base-url']}

    def navbar(value):
        if isinstance(value, list):
            return [navbar(item) for item in value]
        if isinstance(value, dict):
            return {key: local_url(item) if key in ('href', 'logo-href') else navbar(item)
                    for key, item in value.items()}
        return value

    def navigation(project, path):
        # Profile arrays конкатенируются Quarto. Поэтому navbar меняется в base
        # metadata только disposable checkout; profile не добавляет второе меню.
        changed = False
        for section in ('website', 'book'):
            settings = project.get(section, {})
            if isinstance(settings, dict) and 'navbar' in settings:
                local = navbar(settings['navbar'])
                if local != settings['navbar']:
                    settings['navbar'] = local
                    changed = True
        if changed:
            metadata_file(path, required=True)
            path.write_text(yaml.safe_dump(project, allow_unicode=True, sort_keys=False))

    root = {'website': {'site-url': base}, 'course-navigation': {'course-url': base}}
    if config.get('project', {}).get('type') == 'book':
        root['book'] = {'site-url': base}
    navigation(config, checkout / '_quarto.yml')
    own_imports = local_imports(config)
    if own_imports:
        root['reference-catalog'] = {'imports': own_imports}
    metadata_file(checkout / '_quarto-preview.yml')
    (checkout / '_quarto-preview.yml').write_text(json.dumps(root) + '\n')
    # Профиль каждого subproject получает собственный publication URL и общий portal.
    for name, child, child_config in children:
        value = {'website': {'site-url': base + name.strip('/') + '/'},
                 'course-navigation': {'course-url': base}}
        if child_config.get('project', {}).get('type') == 'book':
            value['book'] = {'site-url': base + name.strip('/') + '/'}
        navigation(child_config, child / '_quarto.yml')
        imports = local_imports(child_config)
        if imports:
            value['reference-catalog'] = {'imports': imports}
        metadata_file(child / '_quarto-preview.yml')
        (child / '_quarto-preview.yml').write_text(json.dumps(value) + '\n')


def real_directory(path: Path, *, create: bool = False) -> None:
    """Отклонить ссылки во всех компонентах до создания generated каталогов."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Нужен абсолютный нормализованный путь: ' + str(path))
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ValueError('Ссылка в generated пути: ' + str(part))
        if part.exists() and not part.is_dir():
            raise ValueError('Не каталог в generated пути: ' + str(part))
    if create:
        path.mkdir(parents=True, exist_ok=True)


def output_boundaries(course: Path) -> tuple[Path, Path]:
    output = course.parent
    private_root = output.parent / (output.name + '-checks') / course.name
    work_root = output.parent / (output.name + '-work') / course.name
    for directory in (output, course, course / 'releases', private_root, work_root):
        real_directory(directory)
    for controller in (private_root, work_root):
        if controller.resolve().is_relative_to(output.resolve()):
            raise ValueError('Controller каталог попадает в runtime mount: ' + str(controller))
    return private_root, work_root


def publish(result: Path, course: Path) -> None:
    """Опубликовать кандидат; принятый active переключает только native loader."""
    private_root, _ = output_boundaries(course)
    for directory in (result, result / 'native', result / 'site', result / 'reports'):
        real_directory(directory)
    for name in ('native/infoCourse.json', 'native/delivery.json', 'site/index.html',
                 'native-checks.json', 'runtime-profiles.json'):
        if (result / name).is_symlink() or not (result / name).is_file():
            raise ValueError('Не создан обязательный output: ' + name)
    prepared = course / 'prepared'
    if prepared.is_symlink():
        target = Path(os.readlink(prepared))
        if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != 'releases' or '..' in target.parts:
            raise ValueError('Чужая ссылка prepared: ' + str(prepared))
    elif prepared.exists():
        raise ValueError('prepared должен быть ссылкой на generated release')
    releases = course / 'releases'
    releases.mkdir(exist_ok=True)
    release = releases / result.parent.name.removeprefix('.prepare-')
    if release.exists() or release.is_symlink():
        raise ValueError('Immutable release уже существует: ' + str(release))
    pending = course / '.prepared-pending'
    if pending.exists() and not pending.is_symlink():
        raise ValueError('Чужой temporary output: ' + str(pending))
    # Runtime получает только native/site. Private checks, logs и reports остаются
    # на controller вне стабильного родителя, который монтирует Compose.
    private = private_root / release.name
    real_directory(private)
    private.mkdir(mode=0o700, parents=True)
    (result / 'reports').mkdir(exist_ok=True)
    for item in list(result.iterdir()):
        if item.name not in ('native', 'site'):
            destination = private / item.name
            item.rename(destination)
            item.symlink_to(destination)
    result.rename(release)
    pending.unlink(missing_ok=True)
    pending.symlink_to('releases/' + release.name)
    pending.replace(prepared)


@contextmanager
def mutation_lock(course: Path):
    """prepare и preview/up используют один неблокирующий controller lock."""
    descriptor = os.open(course / '.prepare.lock',
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError('Prepare lock должен быть обычным файлом')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def resume_context(work: Path, site_url: str | None) -> None:
    """Retry только export: frozen checkout/packages и уже готовый student site."""
    path = work / '.prepare-context.json'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Нет origin provenance для resume-export; нужен свежий prepare')
    context = json.loads(path.read_text())
    # Старые workdirs уже содержат выбранные bytes: provenance читается,
    # но packages не переустанавливаются и прежний source API не восстанавливается.
    if (not isinstance(context, dict)
            or set(context) not in ({'site_url'}, {'site_url', 'providers_root'})
            or not isinstance(context['site_url'], str)
            or ('providers_root' in context and context['providers_root'] is not None
                and not isinstance(context['providers_root'], str))):
        raise ValueError('Некорректный origin provenance; нужен свежий prepare')
    if normalized_site_url(context['site_url']) != context['site_url']:
        raise ValueError('Некорректный origin provenance; нужен свежий prepare')
    if site_url is not None and normalized_site_url(site_url) != context['site_url']:
        raise ValueError('resume-export не меняет --site-url; нужен свежий prepare')


def build_environment(work: Path) -> dict[str, str]:
    env = dict(os.environ, COURSE_PREVIEW_PROFILE='1', PYTHONDONTWRITEBYTECODE='1')
    cache = work / '.cache'
    real_directory(cache, create=True)
    env['XDG_CACHE_HOME'] = str(cache)
    env['CI_LOG_DIR'] = str(work / 'result' / 'logs')
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course', required=True, choices=['java', 'system-practice'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--resume-export', type=Path)
    parser.add_argument('--platform', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--site-url')
    args = parser.parse_args()
    source = args.source.resolve(strict=True) if args.source else None
    if args.prepared is not None and args.resume_export is not None:
        parser.error('--prepared и --resume-export несовместимы')
    if args.prepared is None and args.resume_export is None and (source is None or not args.site_url):
        parser.error('Для сборки нужны --source и --site-url')
    platform = args.platform.resolve(strict=True)
    if source is not None and not (source / 'Taskfile.yml').is_file():
        parser.error('Checkout курса должен предоставлять Taskfile.yml check/render/export/build/verify')
    for binary in (() if args.prepared else ('go-task', 'quarto', 'python3', 'pyright', 'shellcheck', 'tsc')):
        if not shutil.which(binary):
            parser.error('Не найдена системная команда: ' + binary)
    output = args.output_root.absolute()
    real_directory(output)
    if output.resolve() != output or (source is not None and output.is_relative_to(source)):
        parser.error('Output root должен быть настоящим каталогом вне checkout курса')
    course = output / args.course
    private_root, work_root = output_boundaries(course)
    if source is not None:
        for generated in (output, course, private_root, work_root):
            physical = generated.resolve()
            if physical.is_relative_to(source) or source.is_relative_to(physical):
                parser.error('Generated путь пересекается с canonical source: ' + str(generated))
    real_directory(course, create=True)
    with mutation_lock(course):
        _, work_root = output_boundaries(course)
        real_directory(work_root, create=True)
        if args.resume_export is not None:
            work = args.resume_export.absolute()
            real_directory(work)
            if work.parent != work_root or not work.name.startswith('.prepare-'):
                parser.error('--resume-export должен указывать на сохранённую prepare-группу этого курса')
        else:
            work = Path(tempfile.mkdtemp(prefix='.prepare-', dir=work_root))
        checkout = work / 'source'
        completed = False
        try:
            if args.resume_export is not None:
                real_directory(checkout)
                if not (checkout / 'Taskfile.yml').is_file() or not (work / 'result/site/index.html').is_file():
                    raise ValueError('Нет сохранённого checkout/готового student site для resume-export')
                resume_context(work, args.site_url)
                print('resume-export: frozen checkout/packages/student site; повторяется только export с текущим Platform', flush=True)
                run(['go-task', 'export', 'PLATFORM_ROOT=' + str(platform),
                     'BUILD_DIR=' + str(work / 'result')], cwd=checkout, env=build_environment(work))
                publish(work / 'result', course)
                completed = True
                print(f'resume-export: кандидат {course}/prepared; для загрузки нужен up', flush=True)
                return
            if args.prepared is not None:
                shutil.copytree(args.prepared.resolve(strict=True), work / 'result')
                result = work / 'result'
                run(['python3', str(platform / 'tools/check-course.py'), 'inventory',
                     '--scope', 'delivery', '--manifest', str(result / 'native-checks.json'),
                     '--delivery', str(result / 'native/delivery.json'),
                     '--runtime-registry', str(result / 'runtime-profiles.json'),
                     '--output', str(result / 'reports/package.json')], cwd=work, env=dict(os.environ))
                publish(result, course)
                print(f'receive: кандидат {course}/prepared; для загрузки нужен up', flush=True)
                completed = True
                return
            print('prepare: используются установленные packages checkout курса', flush=True)
            print(f'prepare: одноразовый checkout {checkout}', flush=True)
            shutil.copytree(source, checkout, symlinks=True, ignore=shutil.ignore_patterns(
                '.git', '.platform', '.ci', 'node_modules', '.quarto', '.qrc', '_site*', '_output',
                '_generated', '_downloads', '_freeze', '__pycache__', '.gradle'))
            preview_profiles(checkout, args.site_url)
            (work / '.prepare-context.json').write_text(json.dumps({
                'site_url': normalized_site_url(args.site_url),
            }) + '\n')
            env = build_environment(work)
            run(['go-task', 'build', 'PLATFORM_ROOT=' + str(platform),
                 'BUILD_DIR=' + str(work / 'result')], cwd=checkout, env=env)
            publish(work / 'result', course)
            print(f'prepare: кандидат {course}/prepared; для загрузки нужен up', flush=True)
            completed = True
        finally:
            if completed:
                shutil.rmtree(checkout, ignore_errors=True)
            else:
                print(f'prepare: исходники и диагностика сохранены: {work}', flush=True)
            # При отказе outputs/logs остаются для диагностики; прежний active сохранён.
            if not any(work.iterdir()):
                work.rmdir()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('prepare: отказ до переключения готовой выдачи: ' + str(error)) from error
