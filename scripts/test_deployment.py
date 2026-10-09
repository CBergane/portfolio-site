"""Focused host-script regressions; never invoke Podman or production settings."""
from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader('portfolio_wait_healthy', str(ROOT / 'deploy/scripts/portfolio-wait-healthy'))
helper = module_from_spec(spec_from_loader(loader.name, loader))
loader.exec_module(helper)


class HostReadinessTests(unittest.TestCase):
    def run_gate(self, state, probe_status=0, failure=None):
        clock = [0]
        def run(command, **kwargs):
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 2)
            self.assertEqual(command[0], '/usr/bin/podman')
            if failure:
                raise failure
            if command[1] == 'healthcheck':
                return subprocess.CompletedProcess(command, probe_status)
            return subprocess.CompletedProcess(command, 0, json.dumps([{
                'State': state, 'Config': {'Env': ['SYNTHETIC_SECRET=never-print-this']},
            }]))
        output = StringIO()
        with patch.object(helper.subprocess, 'run', side_effect=run) as calls:
            with patch.object(helper.time, 'monotonic', side_effect=lambda: clock[0]):
                with patch.object(helper.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
                    with redirect_stdout(output):
                        result = helper.wait_for_health(timeout=2)
        self.assertNotIn('never-print-this', output.getvalue())
        return result, calls, output.getvalue()

    def test_both_health_formats_and_all_four_services(self):
        for field in ('Health', 'Healthcheck'):
            with self.subTest(field=field):
                result, calls, _ = self.run_gate({'Status': 'running', field: {'Status': 'healthy'}})
                self.assertEqual(result, 0)
                names = [call.args[0][-1] for call in calls.call_args_list if call.args[0][1] == 'healthcheck']
                self.assertEqual(names, list(helper.CONTAINERS))
                self.assertIn('portfolio_redis', names)

    def test_failed_probe_cannot_use_cached_healthy_state(self):
        result, _, output = self.run_gate({'Status': 'running', 'Health': {'Status': 'healthy'}}, probe_status=1)
        self.assertEqual(result, 1)
        self.assertIn('probe_failed', output)

    def test_missing_unhealthy_and_stopped_containers_fail_closed(self):
        for state in ({}, {'Status': 'running'},
                      {'Status': 'running', 'Healthcheck': {'Status': 'unhealthy'}},
                      {'Status': 'exited', 'Health': {'Status': 'healthy'}}):
            with self.subTest(state=state):
                self.assertEqual(self.run_gate(state)[0], 1)

    def test_hanging_podman_calls_are_bounded(self):
        self.assertEqual(self.run_gate({}, failure=subprocess.TimeoutExpired('podman', 2))[0], 1)

    def test_missing_podman_is_redacted_and_fails_closed(self):
        self.assertEqual(self.run_gate({}, failure=OSError('synthetic-secret'))[0], 1)

    def test_empty_container_list_cannot_pass(self):
        self.assertEqual(helper.wait_for_health(()), 1)


class EntrypointTests(unittest.TestCase):
    def entrypoint(self, mode, timeout='1'):
        with tempfile.TemporaryDirectory(prefix='portfolio-phase6a-entrypoint-') as directory:
            root = Path(directory)
            python = root / 'python'
            python.write_text('#!/usr/bin/python3\nimport os, sys, time\n'
                              'if sys.argv[1:] == ["-"]:\n'
                              '    sys.stdin.read()\n'
                              '    if os.environ["SYNTHETIC_MODE"] == "hang": time.sleep(30)\n'
                              '    if os.environ["SYNTHETIC_MODE"] == "fail": raise SystemExit(1)\n')
            python.chmod(0o755)
            gunicorn = root / 'gunicorn'
            gunicorn.write_text('#!/bin/sh\nprintf "GUNICORN_REACHED\\n"\n')
            gunicorn.chmod(0o755)
            environment = {
                'PATH': str(root) + ':/usr/bin:/bin', 'SYNTHETIC_MODE': mode,
                'DB_TIMEOUT_SEC': timeout, 'RUN_MIGRATIONS': '0', 'RUN_COLLECTSTATIC': '0',
                'INIT_WAGTAIL_HOME': '0', 'POSTGRES_PASSWORD': 'synthetic-secret@:/#?%+$',
            }
            started = time.monotonic()
            result = subprocess.run(['bash', str(ROOT / 'app/entrypoint.sh')], cwd=root,
                                    env=environment, capture_output=True, text=True, timeout=6)
            elapsed = time.monotonic() - started
            self.assertNotIn(environment['POSTGRES_PASSWORD'], result.stdout + result.stderr)
            return result, elapsed

    def test_ready_database_reaches_gunicorn(self):
        result, _ = self.entrypoint('success')
        self.assertEqual(result.returncode, 0)
        self.assertIn('GUNICORN_REACHED', result.stdout)

    def test_hanging_database_check_times_out_without_starting_gunicorn(self):
        result, elapsed = self.entrypoint('hang')
        self.assertEqual(result.returncode, 1)
        self.assertLess(elapsed, 3)
        self.assertNotIn('GUNICORN_REACHED', result.stdout)

    def test_failed_database_configuration_does_not_continue(self):
        result, _ = self.entrypoint('fail')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('GUNICORN_REACHED', result.stdout)

    def test_invalid_deadlines_are_rejected(self):
        for timeout in ('0', '-1', '3601', '18446744073709551617', '1;echo unsafe'):
            with self.subTest(timeout=timeout):
                result, elapsed = self.entrypoint('success', timeout)
                self.assertEqual(result.returncode, 1)
                self.assertLess(elapsed, 2)


if __name__ == '__main__':
    unittest.main()
