"""Configure native LiveKit on the Linux deployment after installing its binary.

Run as root with --public-ip. Existing API credentials are reused. Egress stays
disabled until it is deployed on a host with sufficient CPU and memory.
"""
import argparse
import grp
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.request


def run(*args):
    subprocess.run(args, check=True)


def private_file(path, content, owner, group, mode=0o600):
    temporary = path.with_suffix(path.suffix + '.new')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, 'w') as output:
        output.write(content)
    os.chmod(temporary, mode)
    os.chown(temporary, pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-ip', required=True, type=ipaddress.IPv4Address)
    args = parser.parse_args()
    public_ip = str(args.public_ip)
    if os.geteuid() != 0:
        parser.error('Run as root')
    if not Path('/usr/local/bin/livekit-server').is_file():
        parser.error('Install the verified official LiveKit binary first')
    config_path = Path('/etc/scu/config.toml')
    original = config_path.read_text()
    tomllib.loads(original)
    try:
        pwd.getpwnam('scu-livekit')
    except KeyError:
        run('useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'scu-livekit')
    runtime = Path('/etc/scu-live')
    runtime.mkdir(mode=0o755, exist_ok=True)
    credential_path = runtime / 'credentials.json'
    if credential_path.exists():
        credentials = json.loads(credential_path.read_text())
    else:
        import secrets
        credentials = {'LIVEKIT_API_KEY': 'scu-' + secrets.token_hex(8),
                       'LIVEKIT_API_SECRET': secrets.token_urlsafe(48)}
    key, secret = credentials['LIVEKIT_API_KEY'], credentials['LIVEKIT_API_SECRET']
    if not key or not secret:
        raise ValueError('LiveKit credentials cannot be empty')
    private_file(credential_path, json.dumps(credentials) + '\n', 'scu', 'scu')
    tls = runtime / 'tls'
    tls.mkdir(mode=0o750, exist_ok=True)
    os.chown(tls, 0, grp.getgrnam('scu-livekit').gr_gid)
    for name in ('fullchain.pem', 'privkey.pem'):
        private_file(tls / name, Path('/etc/letsencrypt-scu/live/scu-ip', name).read_text(),
                     'root', 'scu-livekit', 0o640)
    livekit = {
        'port': 7880, 'bind_addresses': ['127.0.0.1'],
        'redis': {'address': '127.0.0.1:6379'},
        'rtc': {'tcp_port': 7881, 'udp_port': 7882, 'use_external_ip': False,
                'node_ip': public_ip, 'interfaces': {'includes': ['eth0']}},
        'turn': {'enabled': True, 'domain': public_ip, 'tls_port': 5349, 'udp_port': 0,
                 'bind_addresses': ['0.0.0.0'],
                 'cert_file': str(tls / 'fullchain.pem'), 'key_file': str(tls / 'privkey.pem'),
                 'relay_range_start': 30000, 'relay_range_end': 30100},
        'keys': {key: secret},
        'room': {'auto_create': False, 'max_participants': 50},
        'webhook': {'api_key': key, 'urls': ['http://127.0.0.1:8000/api/live/webhook']},
        'logging': {'level': 'info', 'sample': True},
    }
    private_file(runtime / 'livekit.json', json.dumps(livekit, indent=2) + '\n', 'root', 'scu-livekit', 0o640)
    source = Path(__file__).resolve().parent
    shutil.copyfile(source / 'scu-livekit.service', '/etc/systemd/system/scu-livekit.service')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'redis-server', 'scu-livekit')
    run('systemctl', 'restart', 'scu-livekit')
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:7880/', timeout=2) as response:
                if response.status != 200:
                    raise RuntimeError('Unexpected LiveKit health response')
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 19:
                raise RuntimeError('LiveKit failed to start; inspect journalctl -u scu-livekit')
            time.sleep(0.5)

    nginx_path = Path('/etc/nginx/sites-available/scu-app')
    nginx = nginx_path.read_text()
    if 'location ^~ /livekit/' not in nginx:
        proxy = '''    location ^~ /livekit/ {
        proxy_pass http://127.0.0.1:7880/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        access_log off;
    }

'''
        marker = '    client_max_body_size'
        if marker not in nginx:
            raise ValueError('HTTPS nginx server section not found')
        backup = nginx_path.with_suffix('.before-live')
        if not backup.exists():
            shutil.copyfile(nginx_path, backup)
        nginx_path.write_text(nginx.replace(marker, proxy + marker, 1))
        try:
            run('nginx', '-t')
        except subprocess.CalledProcessError:
            nginx_path.write_text(nginx)
            raise
    run('systemctl', 'reload', 'nginx')

    live = tomllib.loads(original).get('live', {})
    live.update(url=f'wss://{public_ip}/livekit/', api_url='http://127.0.0.1:7880',
                credentials_file=str(credential_path), api_key_env='LIVEKIT_API_KEY',
                api_secret_env='LIVEKIT_API_SECRET', recording_enabled=False,
                directory='/srv/scu/data/live', screen_share_width=1280,
                screen_share_height=720, screen_share_frame_rate=15, screen_share_max_bitrate=1500000)
    section = '[live]\n' + '\n'.join(f'{name} = {json.dumps(value)}' for name, value in live.items()) + '\n'
    updated, count = re.subn(r'^\[live\]\s*\n.*?(?=^\[|\Z)', lambda _: section + '\n', original, flags=re.M | re.S)
    if count != 1:
        raise ValueError('Expected exactly one [live] configuration section')
    tomllib.loads(updated)
    backup = runtime / 'config.before-live.toml'
    if not backup.exists():
        private_file(backup, original, 'root', 'root')
    private_file(config_path, updated, 'root', 'scu', 0o640)
    hook = Path('/etc/letsencrypt-scu/renewal-hooks/deploy/scu-livekit')
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / 'renew_live_tls.sh', hook)
    hook.chmod(0o700)
    run('systemctl', 'restart', 'scu')
    print('LiveKit configured; Egress recording remains disabled. Verify external media ports and two-browser media.')


if __name__ == '__main__':
    main()
