#!/usr/bin/env python3
"""Подготовка обычных локальных конфигураций; Docker и системное доверие не меняет."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def write_once(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(data)


def json_once(path, value, mode=0o600):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('Конфигурация изменилась: ' + str(path) + '; существующее состояние не перезаписано')
    else:
        write_once(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n', mode)


def token(path):
    write_once(path, secrets.token_hex(32) + '\n')
    value = path.read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Некорректный существующий service key: ' + path.name)
    return value


def host(value):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '..' in value:
        raise ValueError('Ожидается DNS hostname без схемы и порта')
    return value


def cookie_domain(hostname):
    if hostname == 'localhost':
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return '.' + hostname
    return None


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise ValueError('Ожидается непривилегированный TCP port')
    return number


def tls(state, pl_host, moodle_host):
    directory = state / 'tls'
    directory.mkdir(exist_ok=True)
    directory.chmod(0o755)
    names = ['ca.key', 'ca.crt', 'server.key', 'server.crt']
    existing = [(directory / name).exists() for name in names]
    if all(existing):
        for name in (pl_host, moodle_host):
            subprocess.run(['openssl', 'verify', '-CAfile', str(directory / 'ca.crt'), '-verify_hostname', name, str(directory / 'server.crt')],
                           check=True, capture_output=True)
        return
    if any(existing):
        raise ValueError('Неполный TLS state: существующие ключи не заменены')
    old_umask = os.umask(0o077)
    try:
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes', '-days', '3650',
                        '-subj', '/CN=PrairieLearn local CA', '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                        '-keyout', str(directory / 'ca.key'), '-out', str(directory / 'ca.crt')], check=True, capture_output=True)
        subprocess.run(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes',
                        '-subj', '/CN=' + pl_host, '-keyout', str(directory / 'server.key'),
                        '-out', str(directory / 'server.csr')], check=True, capture_output=True)
        extension = directory / 'server.ext'
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:' + pl_host + ',DNS:' + moodle_host + '\n')
        subprocess.run(['openssl', 'x509', '-req', '-in', str(directory / 'server.csr'), '-CA', str(directory / 'ca.crt'),
                        '-CAkey', str(directory / 'ca.key'), '-CAcreateserial', '-days', '825', '-sha256',
                        '-extfile', str(extension), '-out', str(directory / 'server.crt')], check=True, capture_output=True)
    finally:
        os.umask(old_umask)
    for name in ('ca.crt', 'server.crt'):
        (directory / name).chmod(0o644)


def prepare(state, values, jobs):
    host_jobs = Path(values.get('HOST_JOBS_DIR', ''))
    if not host_jobs.is_absolute():
        raise ValueError('Compose должен передать абсолютный HOST_JOBS_DIR')
    pl_host = host(values.get('PL_HOST', 'pl.infra.localhost'))
    moodle_host = host(values.get('MOODLE_HOST', 'moodle.infra.localhost'))
    pl_port = port(values.get('PL_HTTPS_PORT', '19444'))
    moodle_port = port(values.get('MOODLE_HTTPS_PORT', '19443'))
    if pl_host == moodle_host or pl_port == moodle_port:
        raise ValueError('Для PL и Moodle нужны отдельные hostname и порты')
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o711)
    (state / 'pl').mkdir(exist_ok=True, mode=0o700)
    (state / 'pl').chmod(0o700)
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / 'workspaces').mkdir(exist_ok=True)
    token(state / 'database-key')
    token(state / 'session-key')
    write_once(state / 'moodle-db-password', secrets.token_urlsafe(32) + '\n')
    accounts = state / 'moodle-accounts.json'
    if not accounts.exists():
        json_once(accounts, {role: {'username': 'local' + role, 'password': 'Aa1!' + secrets.token_urlsafe(24)}
                              for role in ('admin', 'student', 'teacher')})
    tls(state, pl_host, moodle_host)
    config_path = state / 'pl/config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text())
        if not isinstance(config, dict):
            raise ValueError('Ожидается объект native PL config')
        addresses = {'hostname': pl_host, 'serverCanonicalHost': f'https://{pl_host}:{pl_port}',
                     'cookieDomain': cookie_domain(pl_host)}
        if any(config.get(name) != value for name, value in addresses.items()):
            config.update(addresses)
            temporary = config_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
            temporary.chmod(0o600)
            temporary.replace(config_path)
    else:
        json_once(config_path, {
            'devMode': False, 'hostname': pl_host, 'serverCanonicalHost': f'https://{pl_host}:{pl_port}',
            'cookieDomain': cookie_domain(pl_host), 'hasShib': False, 'coursesRoot': '/course', 'trustProxy': 1,
            'databaseEncryptionKey': token(state / 'database-key'), 'secretKey': token(state / 'session-key'),
            'externalGradingUseAws': False, 'externalGradingPullImagesFromDockerHub': False,
            'workersCount': 1, 'fileStoreStorageTypeDefault': 'FileSystem',
            'workspaceEnable': False, 'workspaceHomeDirRoot': '/jobs/workspaces',
        })
    for source, destination in [('nginx.conf', 'nginx.conf'), ('nginx.auth.conf', 'nginx-auth.conf')]:
        rendered = ((ROOT / 'config' / source).read_text()
                    .replace('PL_PUBLIC_HOST', pl_host).replace('MOODLE_PUBLIC_HOST', moodle_host)
                    .replace('PL_PUBLIC_PORT', str(pl_port)).replace('MOODLE_PUBLIC_PORT', str(moodle_port)))
        (state / destination).write_text(rendered)
    print('Инфраструктурные конфигурации готовы; ключи и аккаунты сохранены, системное доверие не менялось.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('/state'))
    parser.add_argument('--jobs', type=Path, default=Path('/jobs'))
    args = parser.parse_args()
    try:
        # Все значения уже раскрыты штатным Docker Compose, .env здесь не читается.
        prepare(args.state, os.environ, args.jobs)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Инициализация остановлена: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
