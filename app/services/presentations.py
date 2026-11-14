"""Local Office conversion and private, immutable slide previews."""
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
import pymupdf
from fastapi import HTTPException
from fastapi.responses import FileResponse
from app.config import load_config


def prepare(content: bytes, filename: str):
    """Create a complete preview or remove all partial files on failure."""
    config = load_config()['presentation']
    name = Path(filename.replace('\\', '/')).name
    suffix = Path(name).suffix.lower()
    signatures = {'.pptx': b'PK\x03\x04', '.ppt': b'\xd0\xcf\x11\xe0', '.pdf': b'%PDF-'}
    if suffix not in signatures or not content.startswith(signatures[suffix]):
        raise HTTPException(400, '请上传有效的 PPT、PPTX 或 PDF 文件')
    root = Path(config['directory'])
    root.mkdir(parents=True, exist_ok=True)
    directory = root / secrets.token_hex(20)
    directory.mkdir()
    try:
        source = directory / ('source' + suffix)
        source.write_bytes(content)
        pdf = source if suffix == '.pdf' else convert(source, directory, config)
        try:
            with pymupdf.open(pdf) as document:
                if document.needs_pass or not 1 <= len(document) <= config['max_pages']:
                    raise HTTPException(400, f"文件需为未加密文档，且包含 1–{config['max_pages']} 页")
                pages = len(document)
                for index, page in enumerate(document, 1):
                    # Bound both dimensions, including unusual portrait/oversized slides.
                    scale = config['render_size'] / max(page.rect.width, page.rect.height)
                    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(directory / f'{index}.png')
        except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
            raise HTTPException(400, '无法读取演示文件，请检查文件或导出为 PDF 后重试') from error
        return {'directory': str(directory), 'name': name, 'pages': pages}
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def convert(source, directory, config):
    """Convert Office files with a separate LibreOffice profile and a timeout."""
    executable = shutil.which(config['converter'])
    if executable is None:
        raise HTTPException(503, 'PPT 转换服务未安装，请配置 LibreOffice，或先将 PPT 导出为 PDF 上传')
    environment = os.environ.copy()
    if config['fontconfig_file']:
        environment['FONTCONFIG_FILE'] = config['fontconfig_file']
    with tempfile.TemporaryDirectory(prefix='scu-office-') as profile:
        try:
            result = subprocess.run([executable, f'-env:UserInstallation={Path(profile).as_uri()}',
                '--headless', '--convert-to', 'pdf', '--outdir', str(directory), str(source)],
                capture_output=True, timeout=config['timeout_seconds'], check=False, env=environment)
        except subprocess.TimeoutExpired as error:
            raise HTTPException(504, 'PPT 转换超时，请缩减文件或导出为 PDF 后重试') from error
        except OSError as error:
            raise HTTPException(503, '无法启动 PPT 转换服务，请检查配置') from error
    pdf = directory / 'source.pdf'
    if result.returncode or not pdf.is_file():
        raise HTTPException(400, 'PPT 转换失败，请检查文件或导出为 PDF 后重试')
    return pdf


def page_response(db, iid, page):
    """Serve an authorized interview's slide; caller owns access checks."""
    row = db.execute('SELECT directory,pages FROM presentations WHERE interview_id=?', (iid,)).fetchone()
    if row is None or not 1 <= page <= row['pages']:
        raise HTTPException(404, '演示页不存在')
    path = Path(row['directory']) / f'{page}.png'
    if not path.is_file():
        raise HTTPException(404, '演示文件缺失，请联系管理员恢复文件')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, no-store'})
