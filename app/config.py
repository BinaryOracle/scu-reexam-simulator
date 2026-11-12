import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load_config():
    path = Path(os.environ.get('SCU_CONFIG', ROOT / 'config.toml'))
    if not path.exists():
        path = ROOT / 'config.example.toml'
    with path.open('rb') as f:
        config = tomllib.load(f)
    for key in ('database', 'upload_dir'):
        p = Path(config['app'][key])
        config['app'][key] = str(p if p.is_absolute() else ROOT / p)
    return config
