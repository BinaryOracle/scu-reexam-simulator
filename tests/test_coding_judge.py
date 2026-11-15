"""Public-sample verdicts and unavailable compiler behavior without host execution."""
from types import SimpleNamespace
import pytest
from app.services import coding_judge as judge


@pytest.fixture
def evaluator(monkeypatch):
    cfg = {'image': 'scu-judge:1', 'memory_mb': 256, 'timeout_seconds': 5,
           'compile_timeout_seconds': 30, 'cleanup_timeout_seconds': 5,
           'output_limit_bytes': 65536, 'artifact_limit_bytes': 16777216}
    monkeypatch.setattr(judge, 'load_config', lambda: {'judge': cfg})
    monkeypatch.setattr(judge, 'availability', lambda: {'available': True, 'languages': list(judge.LANGUAGES), 'notice': ''})
    return cfg


def test_counts_all_samples_after_wrong_answer(evaluator, monkeypatch):
    answers = iter([('', 0, 'no', ''), ('', 0, ' 2\n', '')])
    monkeypatch.setattr(judge, '_run_container', lambda *args: next(answers))
    result = judge.evaluate('python3', 'print(input())', [{'input': '1', 'output': '1'}, {'input': '2', 'output': '2'}])
    assert result['status'] == 'Wrong Answer'
    assert (result['passed_cases'], result['total_cases']) == (1, 2)
    assert '样例 #2：Accepted' in result['detail']


def test_compiler_failure_never_runs_user_program(evaluator, monkeypatch):
    calls = []
    def execute(*args):
        calls.append(args)
        return '', 1, '', 'main.cpp: syntax error'
    monkeypatch.setattr(judge, '_run_container', execute)
    result = judge.evaluate('cpp11', 'oops', [{'input': '', 'output': ''}])
    assert result['status'] == 'Compile Error'
    assert 'syntax error' in result['detail']
    assert len(calls) == 1
    assert calls[0][2][0] == 'g++'


@pytest.mark.parametrize('reason', ['Time Limit Exceeded', 'Output Limit Exceeded', 'System Error'])
def test_preserves_resource_failure(evaluator, monkeypatch, reason):
    monkeypatch.setattr(judge, '_run_container', lambda *args: (reason, -9, '', ''))
    result = judge.evaluate('python3', 'print(1)', [{'input': '', 'output': '1'}])
    assert result['status'] == reason
    assert result['passed_cases'] == 0


def test_unavailable_raises_before_attempting_execution(evaluator, monkeypatch):
    monkeypatch.setattr(judge, 'availability', lambda: {'available': False, 'notice': 'not ready'})
    monkeypatch.setattr(judge, '_run_container', lambda *args: pytest.fail('must not execute'))
    with pytest.raises(judge.JudgeUnavailable, match='not ready'):
        judge.evaluate('python3', 'print(1)', [{'input': '', 'output': '1'}])


def test_old_python_only_image_is_not_advertised_as_compiler(monkeypatch):
    monkeypatch.setattr(judge, 'load_config', lambda: {'judge': {'image': 'old', 'cleanup_timeout_seconds': 1}})
    monkeypatch.setattr(judge.shutil, 'which', lambda name: '/docker')
    monkeypatch.setattr(judge.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='null'))
    assert judge.availability()['available'] is False
