"""A timed out submission must stop its own Docker container."""
import subprocess
from types import SimpleNamespace
import pytest
from app.services import judge


@pytest.mark.parametrize('cleanup_status,expected', [(0, 'Time Limit Exceeded'), (1, 'Judge Error')])
def test_timeout_removes_only_its_own_container(monkeypatch, cleanup_status, expected):
    calls = []
    monkeypatch.setattr(judge, 'load_config', lambda: {'judge': {
        'image': 'scu-judge:1', 'memory_mb': 256, 'timeout_seconds': 1, 'cleanup_timeout_seconds': 3}})

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == 'run':
            raise subprocess.TimeoutExpired(command, 1)
        return SimpleNamespace(returncode=cleanup_status)

    monkeypatch.setattr(judge.subprocess, 'run', run)
    assert judge.judge('python3', 'while True: pass', '[{"input":"","output":""}]') == expected
    assert len(calls) == 2
    start, cleanup = calls
    name = start[0][start[0].index('--name') + 1]
    assert name.startswith('scu-judge-')
    assert cleanup[0] == ['docker', 'rm', '-f', name]
    assert cleanup[1]['timeout'] == 3
