"""Manage the localhost LiveKit stack and a single application worker on macOS.

Secrets and runtime logs live under ignored data/live-deploy. No Docker data is
pruned and no application process outside this launcher's PID file is stopped.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / 'data/live-deploy'
COMPOSE = ROOT / 'deploy/live-local/compose.yaml'
PYTHON = ROOT / '.venv/bin/python'
PIDFILE = RUNTIME / 'app.pid'


def private_write(path, content):
    """Write credentials and process metadata without world-readable permissions."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(content)
    path.chmod(0o600)


def environment():
    """Read the local credentials without printing them or adding them to argv."""
    credentials = json.loads((RUNTIME / 'credentials.json').read_text())
    config_path = Path(os.environ.get('SCU_CONFIG', ROOT / 'config.toml')).resolve()
    sys.path.insert(0, str(ROOT))
    from app.config import load_config
    config = load_config()
    return {**os.environ, **credentials, 'SCU_CONFIG': str(config_path),
            'LIVE_RUNTIME_DIR': str(RUNTIME),
            'LIVE_RECORDINGS_DIR': str(Path(config['live']['directory']) / 'recordings')}


def prepare():
    """Generate stable credentials and update only the local [live] settings."""
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    credentials_file = RUNTIME / 'credentials.json'
    if not credentials_file.exists():
        private_write(credentials_file, json.dumps({
            'LIVEKIT_API_KEY': 'scu-local-' + secrets.token_hex(8),
            'LIVEKIT_API_SECRET': secrets.token_urlsafe(48)}, indent=2) + '\n')
    credentials = json.loads(credentials_file.read_text())
    config_path = Path(os.environ.get('SCU_CONFIG', ROOT / 'config.toml')).resolve()
    if not config_path.exists():
        private_write(config_path, (ROOT / 'config.example.toml').read_text())
    text = config_path.read_text()
    backup = RUNTIME / 'config.before-live.toml'
    if not backup.exists():
        private_write(backup, text)
    settings = {'url': 'ws://127.0.0.1:7880', 'api_url': 'http://127.0.0.1:7880',
                'api_key_env': 'LIVEKIT_API_KEY', 'api_secret_env': 'LIVEKIT_API_SECRET',
                'credentials_file': str(credentials_file),
                'recording_enabled': True, 'egress_directory': '/out'}
    match = re.search(r'^\[live\][^\n]*\n(?P<body>.*?)(?=^\[|\Z)', text, re.M | re.S)
    body = match['body'] if match else ''
    for key, value in settings.items():
        assignment = f'{key} = {json.dumps(value)}'
        pattern = rf'^{re.escape(key)}\s*=.*$'
        body = re.sub(pattern, lambda _: assignment, body, flags=re.M) if re.search(pattern, body, re.M) else body.rstrip() + '\n' + assignment + '\n'
    section = '[live]\n' + body.strip() + '\n\n'
    updated = text[:match.start()] + section + text[match.end():] if match else text.rstrip() + '\n\n' + section
    if updated != text:
        private_write(config_path, updated)
    env = environment()
    recordings = Path(env['LIVE_RECORDINGS_DIR'])
    recordings.mkdir(parents=True, exist_ok=True)
    # Docker Desktop maps bind mounts to the current Mac owner; the official
    # Egress image runs as egress. The enclosing private directory stays 0700.
    recordings.chmod(0o770)
    private_write(RUNTIME / 'livekit.yaml', f'''port: 7880
bind_addresses:
  - "0.0.0.0"
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: false
  node_ip: 127.0.0.1
  # Docker forwards host loopback to the bridge socket. A second container
  # loopback socket would receive ICE packets that cannot be returned to Mac.
  enable_loopback_candidate: false
  advertise_internal_ip: true
redis:
  address: redis:6379
keys:
  {credentials['LIVEKIT_API_KEY']}: {credentials['LIVEKIT_API_SECRET']}
webhook:
  api_key: {credentials['LIVEKIT_API_KEY']}
  urls:
    - http://host.docker.internal:8000/api/live/webhook
logging:
  level: info
''')
    print('本机配置已准备；密钥保存在 data/live-deploy（不会提交 Git）。')


def compose(*args):
    """Run only this project's Compose services with private environment values."""
    subprocess.run(['docker', 'compose', '-f', str(COMPOSE), *args], cwd=ROOT,
                   env=environment(), check=True)


def pull_missing_images():
    """Stop this stack's download before it consumes the last GiB of Mac disk."""
    images = subprocess.check_output(['docker', 'compose', '-f', str(COMPOSE), 'config', '--images'],
                                     env=environment(), text=True).splitlines()
    for image in images:
        if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            continue
        if shutil.disk_usage(ROOT).free < 2 * 1024**3:
            raise RuntimeError('镜像尚未安装且磁盘不足 2 GiB；请先释放空间再重试。首次安装建议预留 10 GiB。')
        process = subprocess.Popen(['docker', 'pull', image])
        while process.poll() is None:
            if shutil.disk_usage(ROOT).free < 1024**3:
                process.terminate()
                process.wait(timeout=15)
                raise RuntimeError('磁盘余量低于 1 GiB，已中止本次镜像下载；请释放空间后重试。')
            time.sleep(0.5)
        if process.returncode:
            raise RuntimeError(f'{image} 下载失败；请检查 Docker 和网络后重试。')


def reachable(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def listener_exists():
    with socket.socket() as client:
        return client.connect_ex(('127.0.0.1', 8000)) == 0


def managed_command():
    """Read the saved process's command before treating it as the managed app."""
    if not PIDFILE.exists():
        return ''
    pid = int(PIDFILE.read_text().strip())
    return subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                          capture_output=True, text=True, check=False).stdout.strip()


def is_app_command(command):
    return str(PYTHON) in command and '-m uvicorn app.main:app' in command


def app_start():
    """Start the configured app without taking over any existing port listener."""
    if listener_exists():
        raise RuntimeError('8000 端口已有应用运行；请先停止原启动命令，再运行本脚本 start。')
    with (RUNTIME / 'app.log').open('ab') as log:
        process = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'app.main:app',
            '--host', '127.0.0.1', '--port', '8000', '--workers', '1', '--no-access-log'],
            cwd=ROOT, env=environment(), stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
    private_write(PIDFILE, str(process.pid) + '\n')
    for _ in range(40):
        if process.poll() is not None:
            raise RuntimeError('应用启动失败，请检查 data/live-deploy/app.log。')
        if reachable('http://127.0.0.1:8000/'):
            print('应用已启动：http://127.0.0.1:8000/ → 直播课堂')
            return
        time.sleep(0.25)
    raise RuntimeError('应用健康检查超时，请检查 data/live-deploy/app.log。')


def app_stop():
    """Stop only the process recorded by this launcher after checking its argv."""
    if not PIDFILE.exists():
        return
    pid = int(PIDFILE.read_text().strip())
    command = managed_command()
    if command:
        if not is_app_command(command):
            raise RuntimeError('PID 文件不再对应本启动器的应用，未终止该进程。')
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not listener_exists():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('应用仍在退出，请稍后检查状态；未强制终止进程。')
    PIDFILE.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'stop', 'status', 'logs', 'app'])
    action = parser.parse_args().action
    if action in ('prepare', 'start'):
        prepare()
    if action == 'start':
        pull_missing_images()
        if shutil.disk_usage(ROOT).free < 1024**3:
            raise RuntimeError('磁盘不足 1 GiB，未启动录播服务；请先释放空间。')
        compose('up', '-d', '--wait', '--wait-timeout', '60')
        for _ in range(40):
            if reachable('http://127.0.0.1:7880/'):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('LiveKit 未就绪，请运行本脚本 logs。')
        if is_app_command(managed_command()) and listener_exists():
            print('已有运行中的应用；重载配置或密钥后请 stop / start。')
        else:
            app_start()
    elif action == 'stop':
        app_stop()
        compose('down')
    elif action == 'status':
        compose('ps')
        print('应用 HTTP:', '正常' if reachable('http://127.0.0.1:8000/') else '不可达')
        print('LiveKit HTTP:', '正常' if reachable('http://127.0.0.1:7880/') else '不可达')
    elif action == 'logs':
        compose('logs', '--tail', '60', 'livekit', 'egress')
    elif action == 'app':
        os.chdir(ROOT)
        os.execve(PYTHON, [str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                         '--port', '8000', '--workers', '1', '--no-access-log'], environment())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'本机直播部署失败：{error}', file=sys.stderr)
        sys.exit(1)
