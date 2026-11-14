import json
import secrets
import subprocess
import tempfile
from pathlib import Path
from app.config import load_config

def judge(language, source, tests):
    if language != 'python3':
        return 'Unsupported language'
    cfg = load_config()['judge']
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'main.py'
            path.write_text(source, encoding='utf-8')
            for case in json.loads(tests):
                name = 'scu-judge-' + secrets.token_hex(16)
                cmd = ['docker', 'run', '--name', name, '--rm', '-i', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32', '--memory', str(cfg['memory_mb']) + 'm', '--cpus', '1', '--user', '65534:65534', '--mount', f'type=bind,src={path},dst=/app/main.py,readonly', cfg['image'], 'python3', '-I', '-B', '/app/main.py']
                try:
                    result = subprocess.run(cmd, input=case['input'], text=True, capture_output=True, timeout=cfg['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                                             timeout=cfg['cleanup_timeout_seconds'])
                    return 'Time Limit Exceeded' if cleanup.returncode == 0 else 'Judge Error'
                if result.returncode:
                    return 'Runtime Error' if result.returncode < 125 else 'Judge Error'
                if result.stdout.rstrip() != case['output'].rstrip():
                    return 'Wrong Answer'
        return 'Accepted'
    except subprocess.TimeoutExpired:
        return 'Judge Error'
    except (OSError, ValueError, KeyError):
        return 'Judge Error'
