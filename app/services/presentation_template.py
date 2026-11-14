"""Bundled public reference slides, independent of private interview uploads."""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from app.config import load_config


def metadata():
    """Describe the reference year, original download and official source."""
    config = load_config()['presentation_template']
    manifest = json.loads((Path(config['directory']) / 'manifest.json').read_text())
    return {'name': config['name'], 'year': config['year'], 'pages': manifest['pages'],
            'source_url': config['source_url'],
            'notice': f"{config['year']} 年复试 PPT 模板文件，最新版请从复试官网下载。",
            'download_url': '/api/presentation-template/download',
            'pages_url': '/api/presentation-template/pages'}


def download():
    """Download the supplied original PPTX without modifying its contents."""
    config = load_config()['presentation_template']
    return FileResponse(Path(config['directory']) / 'template.pptx', filename=config['name'],
        media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation')


def page_response(page):
    """Serve one of the bundled public preview pages."""
    if not 1 <= page <= metadata()['pages']:
        raise HTTPException(404, '模板演示页不存在')
    return FileResponse(Path(load_config()['presentation_template']['directory']) / f'{page}.png',
                        media_type='image/png')
