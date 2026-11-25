"""Superadministrator Feishu connection actions and browser-bound OAuth callback."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from app.db import connect
from app.services import feishu_oauth
from app.services.auth import administrator

router = APIRouter(prefix='/api/feishu/oauth', tags=['feishu-oauth'])
COOKIE = 'feishu_oauth_binding'


def superadministrator(user=Depends(administrator)):
    if not user['is_superadmin']:
        raise HTTPException(403, '仅超级管理员可以连接飞书资料管理账号')
    return user


@router.get('/status')
def connection_status(response: Response, user=Depends(administrator)):
    response.headers['Cache-Control'] = 'no-store'
    with connect() as db:
        return feishu_oauth.status(db)


@router.post('/connect')
def start_connection(request: Request, response: Response, user=Depends(superadministrator)):
    try:
        url, binding, secure = feishu_oauth.begin(user['id'], request.headers['authorization'][7:])
    except (ValueError, feishu_oauth.OAuthError) as error:
        raise HTTPException(400, str(error)) from None
    response.set_cookie(COOKIE, binding, max_age=600, httponly=True, secure=secure,
                        samesite='lax', path='/api/feishu/oauth')
    response.headers['Cache-Control'] = 'no-store'
    return {'authorization_url': url}


@router.delete('/connection')
def disconnect(response: Response, user=Depends(superadministrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        feishu_oauth.disconnect(db)
    response.delete_cookie(COOKIE, path='/api/feishu/oauth')
    response.headers['Cache-Control'] = 'no-store'
    return {'disconnected': True}


@router.get('/callback')
def callback(request: Request, state: str = Query(default='', max_length=1024),
             code: str = Query(default='', max_length=8192)):
    try:
        feishu_oauth.complete(state, request.cookies.get(COOKIE, ''), code)
    except feishu_oauth.OAuthError as error:
        from html import escape
        response = HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>飞书连接未完成</title><link rel="stylesheet" href="/static/style.css">'
            '<main class="panel feishu-oauth-result"><h1>飞书连接未完成</h1><p>' + escape(str(error)) +
            '</p><a class="button primary" href="/admin#view=systemSettings">返回系统设置</a></main></html>', status_code=400)
    else:
        response = RedirectResponse('/admin#view=systemSettings', status_code=303)
    response.delete_cookie(COOKIE, path='/api/feishu/oauth')
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                             'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'"})
    return response
