"""The external shop link is configurable and does not expose private settings."""
import os
from pathlib import Path
import pytest
from test_system import client, login


def test_profile_uses_configured_shop_link_and_supports_hiding_it(client):
    headers = login(client, 'alice')
    assert client.get('/api/profile', headers=headers).json()['shop_url'] == 'https://wzyp.cn/shop/E1GQFV0P'
    path = Path(os.environ['SCU_CONFIG'])
    original = path.read_text()
    for target in ('https://example.com/new-shop', ''):
        path.write_text(original.replace('https://wzyp.cn/shop/E1GQFV0P', target))
        profile = client.get('/api/profile', headers=headers).json()
        assert profile['shop_url'] == target
        assert 'api_key' not in profile and 'database' not in profile


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///tmp/shop', 'https://user:pass@example.com'])
def test_shop_link_rejects_non_web_urls_and_embedded_credentials(client, url):
    from app.config import load_config
    path = Path(os.environ['SCU_CONFIG'])
    path.write_text(path.read_text().replace('https://wzyp.cn/shop/E1GQFV0P', url))
    with pytest.raises(ValueError, match='credits.shop_url'):
        load_config()
