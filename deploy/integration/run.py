"""Build, exercise and clean only the synthetic portfolio_phase4a Compose project."""
import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(__file__).resolve().parent
PROJECT = 'portfolio_phase4a'
NETWORK = PROJECT + '_network'
SERVICES = ('db', 'redis', 'web', 'nginx')
PODMAN = ['/usr/bin/podman', '--cgroup-manager=cgroupfs']
COMPOSE = [
    'podman-compose', '--podman-path', '/usr/bin/podman',
    '--podman-args=--cgroup-manager=cgroupfs', '--in-pod=false',
    '--env-file', '/dev/null', '-p', PROJECT, '-f', str(DIRECTORY / 'compose.yml'),
]
REDACTIONS = [
    'phase4a-synthetic-password',
    'phase4a-synthetic-django-secret-never-use-in-production',
]


def sanitized(value):
    for secret in REDACTIONS:
        value = value.replace(secret, '[synthetic credential redacted]')
    return value


def execute(args, *, check=True):
    print('$ ' + sanitized(shlex.join(args)), flush=True)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if check and result.returncode:
        raise RuntimeError(sanitized(result.stdout + result.stderr))
    return result


def inspect(service):
    data = json.loads(execute([*PODMAN, 'inspect', f'{PROJECT}_{service}']).stdout)[0]
    assert data['Config']['Labels']['io.podman.compose.project'] == PROJECT
    return data


def assert_owned_resources():
    for service in SERVICES:
        if execute([*PODMAN, 'container', 'exists', f'{PROJECT}_{service}'], check=False).returncode == 0:
            inspect(service)
    for suffix in ('postgres', 'static', 'media'):
        result = execute([*PODMAN, 'volume', 'inspect', f'{PROJECT}_{suffix}'], check=False)
        if result.returncode == 0:
            assert json.loads(result.stdout)[0]['Labels']['io.podman.compose.project'] == PROJECT


def wait_for(*services):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        ready = []
        for service in services:
            # Podman 3.4 cannot supply Compose's healthy dependency wait.
            result = execute([*PODMAN, 'healthcheck', 'run', f'{PROJECT}_{service}'], check=False)
            data = inspect(service)
            if not data['State']['Running']:
                logs = execute([*PODMAN, 'logs', '--tail', '40', f'{PROJECT}_{service}'], check=False)
                raise RuntimeError(sanitized(logs.stdout + logs.stderr))
            health = data['State'].get('Health') or data['State'].get('Healthcheck') or {}
            ready.append(result.returncode == 0 and health.get('Status') == 'healthy')
        if all(ready):
            print('PASS configured health checks: ' + ', '.join(services), flush=True)
            return
        time.sleep(3)
    raise RuntimeError('Readiness timed out: ' + ', '.join(services))


def prepare_network():
    if execute([*PODMAN, 'network', 'exists', NETWORK], check=False).returncode:
        execute([*PODMAN, 'network', 'create', '--subnet', '10.77.44.0/24',
                 '--gateway', '10.77.44.1', '--label', f'io.podman.compose.project={PROJECT}', NETWORK])
    data = json.loads(execute([*PODMAN, 'network', 'inspect', NETWORK]).stdout)[0]
    assert data['name'] == NETWORK
    assert data['args']['podman_labels']['io.podman.compose.project'] == PROJECT
    # ponytail: Ubuntu's old firewall CNI plugin needs 0.4; remove after upgrading Podman/CNI.
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    path = config_home / 'cni' / 'net.d' / (NETWORK + '.conflist')
    assert json.loads(path.read_text()) == data
    if data['cniVersion'] == '1.0.0':
        data['cniVersion'] = '0.4.0'
        path.write_text(json.dumps(data, indent=2) + '\n')
        print('Applied CNI 0.4 compatibility only to ' + NETWORK, flush=True)


def release_stale_test_port():
    """Recover the demonstrated legacy port leak only in an otherwise isolated engine."""
    result = execute(['ss', '-H', '-ltnp', '( sport = :8088 )'])
    if not result.stdout.strip():
        return
    rows = json.loads(execute([*PODMAN, 'ps', '-a', '--format', 'json']).stdout)
    assert all((row.get('Labels') or {}).get('io.podman.compose.project') == PROJECT for row in rows)
    if execute([*PODMAN, 'container', 'exists', f'{PROJECT}_nginx'], check=False).returncode == 0:
        assert not inspect('nginx')['State']['Running']
    assert len(result.stdout.splitlines()) == 1 and '127.0.0.1:8088' in result.stdout
    match = re.search(r'pid=(\d+),', result.stdout)
    assert match, 'Cannot identify the isolated port holder; refusing process cleanup'
    pid = int(match[1])
    process = Path('/proc') / str(pid)
    descriptor = os.pidfd_open(pid)
    try:
        assert process.stat().st_uid == os.getuid()
        assert (process / 'cmdline').read_bytes().strip(b'\0') == b'containers-rootlessport'
        assert str((process / 'exe').readlink()) == '/usr/bin/podman'
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    finally:
        os.close(descriptor)
    print(f'WARN: recovered orphan isolated rootlessport helper PID {pid}; native port cleanup failed', flush=True)
    time.sleep(2)


def up():
    # Fail if the isolated copy drifts from the production document/security rules.
    expected = (ROOT / 'nginx.conf').read_text().replace(
        'resolver 10.89.0.1', 'resolver 10.77.44.1'
    ).replace('portfolio_web:8000', 'portfolio_phase4a_web:8000')
    assert (DIRECTORY / 'nginx.integration.conf').read_text() == expected
    assert_owned_resources()
    prepare_network()
    for services in (('db', 'redis'), ('web',), ('nginx',)):
        result = execute([*COMPOSE, 'up', '--no-start', '--no-deps', *services])
        print(sanitized(result.stdout + result.stderr), flush=True)
        for service in services:
            data = inspect(service)
            networks = data['NetworkSettings']['Networks'] or {}
            if NETWORK not in networks:
                # Compose 1.6's network:alias syntax is unsupported by Podman 3.4.
                execute([*PODMAN, 'network', 'connect', '--alias', service, NETWORK, f'{PROJECT}_{service}'])
            if service == 'nginx' and not data['State']['Running']:
                release_stale_test_port()
            execute([*PODMAN, 'start', f'{PROJECT}_{service}'])
            for name in inspect(service)['NetworkSettings']['Networks']:
                if name != NETWORK:
                    assert name == 'podman', name
                    execute([*PODMAN, 'network', 'disconnect', name, f'{PROJECT}_{service}'])
        wait_for(*services)


def request(path, method='GET', headers=None):
    connection = HTTPConnection('127.0.0.1', 8088, timeout=10)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def seed_fixture():
    seeded = execute([*PODMAN, 'exec', f'{PROJECT}_web', 'python', '/integration/fixtures.py'])
    fixture = json.loads(seeded.stdout)
    REDACTIONS.append(fixture['cookie'].split('=', 1)[1])
    return fixture


def verify():
    wait_for(*SERVICES)
    for service in SERVICES:
        data = inspect(service)
        assert set(data['NetworkSettings']['Networks']) == {NETWORK}, service
        # Podman 3.4 includes image EXPOSE entries with null bindings.
        ports = {port: bindings for port, bindings in
                 (data['HostConfig'].get('PortBindings') or {}).items() if bindings}
        if service == 'nginx':
            assert ports == {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8088'}]}, ports
        else:
            assert not ports, f'{service} exposes a host port'
        assert data['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
    web = inspect('web')
    assert web['Config']['User'] == 'appuser'
    for mount in inspect('nginx')['Mounts']:
        if mount['Destination'] in ('/static', '/media'):
            assert mount['RW'] is False
    last_checks = {}
    for service in SERVICES:
        state = inspect(service)['State']
        health = state.get('Health') or state.get('Healthcheck')
        last_checks[service] = health['Log'][-1]['Start']
    time.sleep(12)
    stalled = []
    for service in SERVICES:
        state = inspect(service)['State']
        health = state.get('Health') or state.get('Healthcheck')
        if health['Status'] != 'healthy' or health['Log'][-1]['Start'] == last_checks[service]:
            stalled.append(service)
    for args in (
        ['python', 'manage.py', 'check'],
        ['python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--noinput'],
        ['/usr/local/bin/python', '-m', 'pip', '--python', '/opt/venv', 'check'],
        ['python', '/integration/verify_runtime.py'],
    ):
        result = execute([*PODMAN, 'exec', f'{PROJECT}_web', *args])
        print(sanitized(result.stdout), flush=True)
    result = execute([*PODMAN, 'exec', f'{PROJECT}_nginx', 'nginx', '-t'])
    print(sanitized(result.stderr), flush=True)
    fixture = seed_fixture()
    for path, status in (('/healthz', 200), ('/', 200), ('/phase4a-missing-route/', 404)):
        assert request(path)[0] == status, path
    assert request('/healthz')[2] == b'OK'
    for path in ('/static/css/output.css', '/static/css/custom.css', '/static/js/navigation.js'):
        status, headers, content = request(path)
        assert status == 200 and content and 'max-age=' in headers.get('Cache-Control', ''), path
        if path != '/static/css/output.css':
            assert content == (ROOT / 'app' / path.lstrip('/')).read_bytes(), path
    assert request('/media/' + fixture['marker'])[2] == b'phase4a synthetic persistent media'
    for kind, document in fixture['documents'].items():
        body = document['content'].encode()
        direct = document['direct']
        for path in (
            direct, direct + '?download=1', direct.replace('/documents/', '//documents/'),
            direct.replace('documents', '%64ocuments'), direct.replace('documents/', 'documents%2F'),
            direct.replace('documents/', 'images/../documents/'),
        ):
            for method in ('GET', 'HEAD'):
                status, _, content = request(path, method)
                assert status == 403 and body not in content, (path, method, status)
        assert request(direct, headers={'Cookie': fixture['cookie']})[0] == 403
        status, headers, content = request(document['url'])
        if kind == 'public':
            assert status == 200 and content == body
            assert headers.get('Content-Security-Policy') == "default-src 'none'"
            assert headers.get('X-Content-Type-Options') == 'nosniff'
            assert headers.get('Content-Disposition', '').startswith('attachment;')
        else:
            assert status == 302 and body not in content
            assert request(document['url'], 'HEAD')[0] == 302
            assert request(document['url'], headers={'Cookie': fixture['cookie']})[2] == body
    print('PASS HTTP, static/media permissions and real Wagtail document privacy through Nginx', flush=True)
    if stalled:
        raise RuntimeError('Automatic health checks did not advance: ' + ', '.join(stalled))
    print('PASS automatic health-check scheduling for all four services', flush=True)
    return fixture


def recover():
    wait_for(*SERVICES)
    fixture = seed_fixture()
    execute([*PODMAN, 'exec', f'{PROJECT}_web', 'python', '-c',
             'import django; django.setup(); from django.core.cache import cache; '
             'cache.set("phase4a-recovery", "synthetic cache marker", timeout=600)'])
    for service in ('db', 'redis', 'web'):
        execute([*PODMAN, 'restart', f'{PROJECT}_{service}'])
        wait_for(service)
    execute([*PODMAN, 'exec', f'{PROJECT}_web', 'python', '-c',
             'import django; django.setup(); from django.core.cache import cache; '
             'assert cache.get("phase4a-recovery") is None'])
    assert request('/media/' + fixture['marker'])[2] == b'phase4a synthetic persistent media'
    for document in fixture['documents'].values():
        assert request(document['url'], headers={'Cookie': fixture['cookie']})[2] == document['content'].encode()
    print('PASS db/Redis/web restarts preserve PostgreSQL documents, sessions and media; Redis cache is ephemeral', flush=True)

    execute([*PODMAN, 'stop', f'{PROJECT}_db'])
    failed = execute([*PODMAN, 'healthcheck', 'run', f'{PROJECT}_web'], check=False)
    assert failed.returncode != 0, 'Application readiness did not detect the database outage'
    execute([*PODMAN, 'start', f'{PROJECT}_db'])
    wait_for('db', 'web')
    assert request('/')[0] == 200
    print('PASS database outage detected by readiness; application recovers', flush=True)

    execute([*PODMAN, 'stop', f'{PROJECT}_redis'])
    failed = execute([*PODMAN, 'healthcheck', 'run', f'{PROJECT}_web'], check=False)
    assert failed.returncode != 0, 'Application readiness did not detect the Redis outage'
    execute([*PODMAN, 'start', f'{PROJECT}_redis'])
    wait_for('redis', 'web')
    print('PASS Redis outage detected by readiness; cache recovers', flush=True)

    before = inspect('web')
    execute([*PODMAN, 'exec', f'{PROJECT}_web', 'python', '-c',
             'import os, signal; os.kill(1, signal.SIGTERM)'])
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        after = inspect('web')
        if after.get('RestartCount', 0) > before.get('RestartCount', 0):
            break
        time.sleep(2)
    else:
        raise RuntimeError('Container restart policy did not recover terminated Gunicorn')
    wait_for('web', 'nginx')
    assert request('/')[0] == 200
    print('PASS restart policy recovers terminated Gunicorn', flush=True)

    execute([*COMPOSE, 'down'])
    up()
    for document in fixture['documents'].values():
        assert request(document['url'], headers={'Cookie': fixture['cookie']})[2] == document['content'].encode()
    assert request('/media/' + fixture['marker'])[2] == b'phase4a synthetic persistent media'
    assert request(fixture['documents']['private']['url'])[0] == 302
    assert request(fixture['documents']['private']['direct'])[0] == 403
    print('PASS container recreation preserves volumes and document access controls', flush=True)
    # Run last so an old rootlessport leak does not hide the other recovery results.
    restarted = execute([*PODMAN, 'restart', f'{PROJECT}_nginx'], check=False)
    if restarted.returncode:
        assert 'rootlessport' in restarted.stderr and 'address already in use' in restarted.stderr
        print('FAIL native Nginx restart: ' + sanitized(restarted.stderr), flush=True)
        release_stale_test_port()
        execute([*PODMAN, 'start', f'{PROJECT}_nginx'])
    wait_for('nginx')
    assert request('/')[0] == 200
    if restarted.returncode:
        raise RuntimeError('Native Nginx restart failed; isolated helper recovery restored HTTP')
    print('PASS native Nginx restart', flush=True)


def logs():
    for service in SERVICES:
        result = execute([*PODMAN, 'logs', '--tail', '150', f'{PROJECT}_{service}'], check=False)
        print(sanitized(result.stdout + result.stderr), flush=True)


def tests():
    inspect('web')
    for settings in ('config.test_settings', 'integration_test_settings'):
        result = execute([*PODMAN, 'exec', '-e', f'DJANGO_SETTINGS_MODULE={settings}',
                          '-e', 'TEST_DATABASE_ENGINE=sqlite', f'{PROJECT}_web',
                          'python', 'manage.py', 'test', '--noinput'])
        print(sanitized(result.stdout + result.stderr), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'up', 'verify', 'recover', 'tests', 'logs', 'stop', 'clean'))
    action = parser.parse_args().action
    try:
        if action == 'build':
            result = execute([*COMPOSE, 'build', 'web'])
            print(sanitized(result.stdout + result.stderr), flush=True)
        elif action == 'up':
            up()
        elif action == 'verify':
            verify()
        elif action == 'recover':
            recover()
        elif action == 'logs':
            logs()
        elif action == 'tests':
            tests()
        else:
            # Fixed project/config and explicitly isolated named volumes only.
            assert_owned_resources()
            if execute([*PODMAN, 'network', 'exists', NETWORK], check=False).returncode == 0:
                data = json.loads(execute([*PODMAN, 'network', 'inspect', NETWORK]).stdout)[0]
                assert data['args']['podman_labels']['io.podman.compose.project'] == PROJECT
            execute([*COMPOSE, 'down', *(['-v'] if action == 'clean' else [])])
            release_stale_test_port()
            if action == 'clean':
                if execute([*PODMAN, 'network', 'exists', NETWORK], check=False).returncode == 0:
                    execute([*PODMAN, 'network', 'rm', NETWORK])
    except (AssertionError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit('FAIL: ' + sanitized(str(error)))
