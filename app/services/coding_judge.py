"""Bounded public-sample evaluation; submitted programs execute only in Docker."""
import json
import os
import selectors
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import load_config

LANGUAGES = {'cpp11': ('main.cpp', 'g++', '-std=c++11'), 'c': ('main.c', 'gcc', '-std=c11'),
             'python3': ('main.py', None, None)}


class JudgeUnavailable(RuntimeError):
    """Docker or the configured compiler image is unavailable."""


def availability():
    """Check the local compiler image without pulling images or executing user code."""
    cfg = load_config()['judge']
    notice = '公开样例评测，仅验证题面样例，不代表完整隐藏测试。'
    if not shutil.which('docker'):
        return {'available': False, 'languages': [], 'notice': '样例评测暂不可用：服务器尚未安装 Docker。'}
    try:
        result = subprocess.run(['docker', 'image', 'inspect', '--format', '{{json .Config.Labels}}', cfg['image']],
                                capture_output=True, text=True, timeout=cfg['cleanup_timeout_seconds'])
        labels = json.loads(result.stdout) if result.returncode == 0 else {}
        ready = (labels or {}).get('scu.coding.languages') == 'cpp11,c,python3'
    except (OSError, subprocess.TimeoutExpired, ValueError):
        ready = False
    return {'available': ready, 'languages': list(LANGUAGES) if ready else [],
            'notice': notice if ready else '样例评测暂不可用：请启动 Docker 并构建 judge/Dockerfile 对应的评测镜像。'}


def _run_container(cfg, mounts, command, stdin, timeout):
    """Limit output while draining pipes; force-remove our container on every exit path."""
    name = 'scu-coding-' + secrets.token_hex(16)
    args = ['docker', 'run', '--rm', '--name', name, '-i', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32',
            '--memory', f"{cfg['memory_mb']}m", '--memory-swap', f"{cfg['memory_mb']}m",
            '--cpus', '1', '--user', '65534:65534', '--ulimit', 'nofile=64:64',
            '--ulimit', f"fsize={cfg['artifact_limit_bytes']}:{cfg['artifact_limit_bytes']}",
            '--tmpfs', f"/tmp:rw,nosuid,nodev,noexec,size={cfg['memory_mb']}m"]
    for source, destination, readonly in mounts:
        args += ['--mount', f"type=bind,src={source},dst={destination}" + (',readonly' if readonly else '')]
    args += [cfg['image'], *command]
    output = {1: bytearray(), 2: bytearray()}
    reason = ''
    process = None
    try:
        with tempfile.TemporaryFile() as input_file, selectors.DefaultSelector() as selector:
            input_file.write(stdin.encode('utf-8'))
            input_file.seek(0)
            process = subprocess.Popen(args, stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for number, pipe in ((1, process.stdout), (2, process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, number)
            deadline = time.monotonic() + timeout
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = 'Time Limit Exceeded'
                    break
                for key, _ in selector.select(min(remaining, .1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = output[key.data]
                    room = cfg['output_limit_bytes'] - len(buffer)
                    buffer.extend(chunk[:max(room, 0)])
                    if len(chunk) > room:
                        reason = 'Output Limit Exceeded'
                        break
                if reason:
                    break
            if not reason:
                try:
                    process.wait(timeout=max(.01, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    reason = 'Time Limit Exceeded'
    except OSError as error:
        raise JudgeUnavailable('无法启动或读取容器评测，请检查 Docker 服务后重试。') from error
    finally:
        # Killing the Docker client does not stop its container.
        try:
            cleanup = subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     timeout=cfg['cleanup_timeout_seconds'])
            if cleanup.returncode and b'No such container' not in cleanup.stderr:
                reason = 'System Error'
        except (OSError, subprocess.TimeoutExpired):
            reason = 'System Error'
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()
    return reason, process.returncode, *(bytes(output[key]).decode('utf-8', errors='replace') for key in (1, 2))


def evaluate(language, source, samples):
    """Compile C/C++ once, then run each sample in a fresh isolated container."""
    cfg = load_config()['judge']
    if language not in LANGUAGES:
        raise ValueError('样例评测仅支持 C、C++11 和 Python3')
    if not samples:
        raise ValueError('该题尚未配置公开样例')
    ready = availability()
    if not ready['available']:
        raise JudgeUnavailable(ready['notice'])
    total, passed = len(samples), 0
    filename, compiler, standard = LANGUAGES[language]
    verdicts = []
    test_results = []
    with tempfile.TemporaryDirectory(prefix='scu-coding-') as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        source_file = root / filename
        source_file.write_text(source, encoding='utf-8')
        source_file.chmod(0o644)
        artifacts = root / 'artifacts'
        artifacts.mkdir(mode=0o777)
        artifacts.chmod(0o777)
        if compiler:
            reason, code, stdout, stderr = _run_container(cfg,
                [(source_file, f'/app/{filename}', True), (artifacts, '/work', False)],
                [compiler, standard, '-O2', '-pipe', f'/app/{filename}', '-o', '/work/main'], '', cfg['compile_timeout_seconds'])
            if reason or code:
                status = 'System Error' if reason == 'System Error' or code == 125 else 'Compile Error'
                return {'status': status, 'detail': f'编译未完成，未运行测试用例（共 {total} 个）。\n{reason or stderr or stdout}',
                        'passed_cases': 0, 'total_cases': total, 'cases': []}
        overall = 'Accepted'
        for index, sample in enumerate(samples):
            command = ['/work/main'] if compiler else ['python3', '-I', '-B', '/app/main.py']
            reason, code, stdout, stderr = _run_container(cfg,
                [(artifacts, '/work', True), (source_file, f'/app/{filename}', True)],
                command, sample['input'], cfg['timeout_seconds'])
            status = reason or ('System Error' if code == 125 else 'Runtime Error' if code else
                               'Accepted' if stdout.split() == sample['output'].split() else 'Wrong Answer')
            if status == 'Accepted':
                passed += 1
            elif overall == 'Accepted':
                overall = status
            verdicts.append(f'样例 #{index+1}：{status}' + (f'\n{stderr[:2000]}' if stderr else ''))
            test_results.append({'input': sample['input'], 'expected_output': sample['output'],
                                 'actual_output': stdout[:cfg['output_limit_bytes']], 'status': status})
            if status == 'System Error':
                break
        return {'status': overall, 'detail': f'通过公开样例数：{passed} / {total}\n' + '\n'.join(verdicts),
                'passed_cases': passed, 'total_cases': total, 'cases': test_results}
