import os
import re
import tomllib
from urllib.parse import urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _email_auth_config(config):
    """Validate SMTP transport and persisted verification/rate-limit settings."""
    email = config.setdefault('email_auth', {})
    defaults = {
        'enabled': False, 'smtp_host': 'smtp.qq.com', 'smtp_port': 465,
        'smtp_security': 'ssl', 'smtp_username': '', 'smtp_password': '',
        'smtp_password_env': 'SCU_SMTP_PASSWORD', 'from_email': '',
        'from_name': '复试模拟系统', 'timeout_seconds': 15,
        'code_ttl_seconds': 300, 'resend_seconds': 60, 'max_attempts': 5,
        'rate_window_seconds': 3600, 'max_email_codes': 5,
        'max_ip_codes': 30, 'max_ip_attempts': 60,
    }
    for key, value in defaults.items():
        email.setdefault(key, value)
    if type(email['enabled']) is not bool:
        raise ValueError('email_auth.enabled 必须是布尔值')
    for key in ('smtp_host', 'smtp_username', 'smtp_password', 'smtp_password_env', 'from_email', 'from_name'):
        value = email[key]
        if not isinstance(value, str) or any(char in value for char in ('\r', '\n', '\x00')):
            raise ValueError(f'email_auth.{key} 必须是单行字符串')
    if not email['smtp_host'] or not re.fullmatch(r'[A-Za-z0-9.-]+', email['smtp_host']):
        raise ValueError('email_auth.smtp_host 必须是 SMTP 服务器域名或 IPv4 地址')
    if email['smtp_security'] not in ('ssl', 'starttls'):
        raise ValueError('email_auth.smtp_security 仅支持 ssl 或 starttls')
    if type(email['smtp_port']) is not int or not 1 <= email['smtp_port'] <= 65535:
        raise ValueError('email_auth.smtp_port 必须在 1 到 65535 之间')
    for key in ('timeout_seconds', 'code_ttl_seconds', 'resend_seconds', 'max_attempts',
                'rate_window_seconds', 'max_email_codes', 'max_ip_codes', 'max_ip_attempts'):
        if type(email[key]) is not int or email[key] <= 0:
            raise ValueError(f'email_auth.{key} 必须是正整数')
    if email['max_attempts'] > 10:
        raise ValueError('email_auth.max_attempts 不能超过 10')
    if email['timeout_seconds'] >= email['resend_seconds']:
        raise ValueError('email_auth.timeout_seconds 必须小于 resend_seconds')
    if email['code_ttl_seconds'] < email['resend_seconds']:
        raise ValueError('email_auth.code_ttl_seconds 不能小于 resend_seconds')


def load_config():
    path = Path(os.environ.get('SCU_CONFIG', ROOT / 'config.toml'))
    if not path.exists():
        path = ROOT / 'config.example.toml'
    with path.open('rb') as f:
        config = tomllib.load(f)
    _email_auth_config(config)
    judge = config['judge']
    judge.setdefault('cleanup_timeout_seconds', 5)
    if type(judge['cleanup_timeout_seconds']) is not int or judge['cleanup_timeout_seconds'] <= 0:
        raise ValueError('judge.cleanup_timeout_seconds 必须是正整数')
    for key in ('database', 'upload_dir'):
        p = Path(config['app'][key])
        config['app'][key] = str(p if p.is_absolute() else ROOT / p)
    courses = config.setdefault('courses', {})
    for key, value, maximum in [('max_material_mb', 50, 1024), ('max_video_mb', 1024, 10240),
                                ('max_live_minutes', 180, 360), ('max_concurrent_live', 1, 10)]:
        courses.setdefault(key, value)
        if type(courses[key]) is not int or not 1 <= courses[key] <= maximum:
            raise ValueError(f'courses.{key} 必须在 1 到 {maximum} 之间')
    courses.setdefault('directory', str(Path(config['app']['database']).with_name('courses')))
    courses.setdefault('ffmpeg', 'ffmpeg')
    for key in ('directory', 'ffmpeg'):
        if not isinstance(courses[key], str) or not courses[key].strip():
            raise ValueError(f'courses.{key} 必须为非空字符串')
    course_directory = Path(courses['directory'])
    courses['directory'] = str(course_directory if course_directory.is_absolute() else ROOT / course_directory)
    security = config.setdefault('security', {})
    key_file = security.setdefault('password_key_file', str(Path(config['app']['database']).with_name('password-view.key')))
    if not isinstance(key_file, str) or not key_file:
        raise ValueError('security.password_key_file 必须指定密钥文件路径')
    key_path = Path(key_file)
    security['password_key_file'] = str(key_path if key_path.is_absolute() else ROOT / key_path)
    credits = config.setdefault('credits', {})
    credits.setdefault('shop_url', 'https://wzyp.cn/shop/E1GQFV0P')
    shop_url = credits['shop_url']
    if not isinstance(shop_url, str):
        raise ValueError('credits.shop_url 必须为 HTTP/HTTPS 商品或店铺链接，或留空隐藏购买入口')
    shop = urlsplit(shop_url)
    if shop_url and (shop.scheme not in ('http', 'https') or not shop.hostname or shop.username or shop.password):
        raise ValueError('credits.shop_url 必须为 HTTP/HTTPS 商品或店铺链接，或留空隐藏购买入口')
    for key, default, minimum, maximum in [('default_credits', 1, 0, 1000000), ('max_voucher_batch', 500, 1, 10000)]:
        credits.setdefault(key, default)
        if type(credits[key]) is not int or not minimum <= credits[key] <= maximum:
            raise ValueError(f'credits.{key} 必须在 {minimum} 到 {maximum} 之间')
    packages = credits.setdefault('packages', {
        'three': {'credits': 3, 'price_fen': 200}, 'ten': {'credits': 10, 'price_fen': 500}})
    for key, package in packages.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key):
            raise ValueError('credits.packages 的标识仅支持字母、数字、下划线和短横线')
        for field in ('credits', 'price_fen'):
            if type(package.get(field)) is not int or package[field] <= 0:
                raise ValueError(f'credits.packages.{key}.{field} 必须为正整数')
    interview = config['interview']
    for key, default in [('duration_seconds', 600), ('warning_seconds', 60)]:
        interview.setdefault(key, default)
        if type(interview[key]) is not int or interview[key] <= 0:
            raise ValueError(f'interview.{key} 必须是正整数')
    if interview['warning_seconds'] > interview['duration_seconds']:
        raise ValueError('interview.warning_seconds 不能超过面试时长')
    ai = config.setdefault('ai', {})
    for key, default in {
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen3.8-omni-flash', 'api_key': '', 'api_key_env': 'DASHSCOPE_API_KEY',
        'request_timeout_seconds': 90, 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 30,
        'max_audio_mb': 8, 'max_slide_pages': 60, 'slide_image_size': 768,
        'max_context_chars': 120000, 'include_audio': True, 'include_slide_images': True,
    }.items():
        ai.setdefault(key, default)
    tts = config.setdefault('tts', {})
    for key, default in {
        'enabled': True, 'provider': 'dashscope', 'protocol': 'dashscope_audio',
        'base_url': 'https://dashscope.aliyuncs.com/api/v1',
        'model': 'qwen-audio-3.1-tts-plus', 'voice': 'longanhuan_v3.1',
        'format': 'wav', 'sample_rate': 24000, 'language_type': 'Chinese',
        'api_key': '', 'api_key_env': 'DASHSCOPE_API_KEY', 'request_timeout_seconds': 60,
        'max_audio_mb': 12, 'download_hosts': ['dashscope-result-bj.oss-cn-beijing.aliyuncs.com',
            'dashscope-result-sh.oss-cn-shanghai.aliyuncs.com'],
        'cache_lock_timeout_seconds': 90,
    }.items():
        tts.setdefault(key, default)
    for section, fields in [('ai', ('request_timeout_seconds', 'conversion_timeout_seconds', 'max_audio_mb',
                                   'max_slide_pages', 'slide_image_size', 'max_context_chars')),
                            ('tts', ('request_timeout_seconds', 'max_audio_mb', 'cache_lock_timeout_seconds'))]:
        for key in fields:
            if type(config[section][key]) is not int or config[section][key] <= 0:
                raise ValueError(f'{section}.{key} 必须是正整数')
    for section, fields in [('ai', ('include_audio', 'include_slide_images')), ('tts', ('enabled',))]:
        for key in fields:
            if type(config[section][key]) is not bool:
                raise ValueError(f'{section}.{key} 必须是布尔值')
    if tts['provider'] not in ('dashscope', 'openai'):
        raise ValueError('tts.provider 仅支持 dashscope 或 openai')
    hosts = tts['download_hosts']
    if not isinstance(hosts, list) or any(not isinstance(host, str) or not re.fullmatch(
            r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host) for host in hosts):
        raise ValueError('tts.download_hosts 必须是精确域名列表，不得包含协议、端口或路径')
    for section, fields in [('ai', ('model', 'api_key_env', 'ffmpeg')), ('tts', ('model', 'api_key_env', 'voice', 'language_type'))]:
        for key in fields:
            if not isinstance(config[section][key], str) or not config[section][key]:
                raise ValueError(f'{section}.{key} 必须是非空字符串')
    for section in ('ai', 'tts'):
        url = config[section]['base_url']
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f'{section}.base_url 必须是 HTTP/HTTPS 接口地址')
    recording = config.setdefault('recording', {})
    for key, default in [('bitrate', 64000), ('checkpoint_seconds', 15),
                         ('finalize_grace_seconds', 120), ('live_chunk_seconds', 5)]:
        recording.setdefault(key, default)
        if type(recording[key]) is not int or recording[key] <= 0:
            raise ValueError(f'recording.{key} 必须是正整数')
    asr = config['asr']
    asr.setdefault('api_key', '')
    asr.setdefault('ffmpeg', 'ffmpeg')
    asr.setdefault('conversion_timeout_seconds', 30)
    asr.setdefault('request_timeout_seconds', 120)
    asr.setdefault('max_segment_seconds', 30)
    if type(asr['max_segment_seconds']) is not int or not 1 <= asr['max_segment_seconds'] <= 60:
        raise ValueError('asr.max_segment_seconds 必须在 1 到 60 秒之间')
    if type(asr['conversion_timeout_seconds']) is not int or asr['conversion_timeout_seconds'] <= 0:
        raise ValueError('asr.conversion_timeout_seconds 必须是正整数')
    if type(asr['request_timeout_seconds']) is not int or asr['request_timeout_seconds'] <= 0:
        raise ValueError('asr.request_timeout_seconds 必须是正整数')
    if not isinstance(asr['ffmpeg'], str) or not asr['ffmpeg']:
        raise ValueError('asr.ffmpeg 必须指定可执行文件')
    presentation = config.setdefault('presentation', {})
    defaults = {'directory': 'data/presentations', 'max_mb': 25, 'max_pages': 60,
                'converter': 'soffice', 'timeout_seconds': 60, 'render_size': 1440,
                'fontconfig_file': 'config/fonts.conf'}
    for key, value in defaults.items():
        presentation.setdefault(key, value)
    for key in ('max_mb', 'max_pages', 'timeout_seconds', 'render_size'):
        if type(presentation[key]) is not int or presentation[key] <= 0:
            raise ValueError(f'presentation.{key} 必须是正整数')
    if not isinstance(presentation['converter'], str) or not presentation['converter']:
        raise ValueError('presentation.converter 必须指定 LibreOffice 可执行文件')
    fontconfig = presentation['fontconfig_file']
    if not isinstance(fontconfig, str):
        raise ValueError('presentation.fontconfig_file 必须是文件路径或空字符串')
    if fontconfig:
        fontpath = Path(fontconfig)
        fontpath = fontpath if fontpath.is_absolute() else ROOT / fontpath
        if not fontpath.is_file():
            raise ValueError('presentation.fontconfig_file 文件不存在，请检查字体配置路径')
        presentation['fontconfig_file'] = str(fontpath)
    directory = Path(presentation['directory'])
    presentation['directory'] = str(directory if directory.is_absolute() else ROOT / directory)
    template = config.setdefault('presentation_template', {})
    for key, value in {'directory': 'app/assets/reexam-2026', 'year': 2026,
                       'name': '附件2：研究生复试-个人情况简介模板（统考生）.pptx',
                       'source_url': 'https://cs.scu.edu.cn/info/1266/19768.htm'}.items():
        template.setdefault(key, value)
    directory = Path(template['directory'])
    template['directory'] = str(directory if directory.is_absolute() else ROOT / directory)
    training = config.setdefault('training', {})
    for key, default, limit in [('round_size', 5, 50), ('daily_goal', 5, 100),
                                ('weight_again', 4, 1000), ('weight_unseen', 2, 1000), ('weight_known', 1, 1000),
                                ('max_round_questions', 10000, 1000000),
                                ('max_import_items', 100, 1000), ('max_import_bytes', 1048576, 10485760),
                                ('max_question_chars', 12000, 100000), ('max_answer_chars', 60000, 200000)]:
        training.setdefault(key, default)
        if type(training[key]) is not int or not 1 <= training[key] <= limit:
            raise ValueError(f'training.{key} 必须在 1 到 {limit} 之间')
    if not training['weight_again'] > training['weight_unseen'] > training['weight_known']:
        raise ValueError('training 随机抽题权重须满足 weight_again > weight_unseen > weight_known')
    training.setdefault('timezone', 'Asia/Shanghai')
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(training['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError) as error:
        raise ValueError('training.timezone 必须是有效的 IANA 时区') from error
    return config
