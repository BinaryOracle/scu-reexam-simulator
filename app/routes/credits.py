"""Balance and voucher endpoints; the external shop only receives exported codes."""
import re
import secrets
import sqlite3
import time
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from app.db import connect
from app.services.auth import administrator, current_user
from app.services import credits

router = APIRouter()
Package = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')]
Status = Literal['all', 'unused', 'redeemed']


class VoucherBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    package: Package
    count: StrictInt = Field(ge=1, le=10000)


class CreditSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    default_credits: StrictInt = Field(ge=0, le=1000000)


class VoucherPackage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    price_fen: StrictInt = Field(ge=1, le=100000000)
    credits: StrictInt = Field(ge=1, le=1000000)


@router.post('/api/admin/voucher-packages', status_code=201)
def create_package(payload: VoucherPackage, user=Depends(administrator)):
    key = 'pkg_' + secrets.token_hex(12)
    with connect() as db:
        try:
            db.execute('INSERT INTO voucher_packages VALUES (?,?,?,?)',
                       (key, payload.price_fen, payload.credits, time.time()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, '相同金额与次数的套餐已存在，请直接选择') from error
    return {'id': key, **payload.model_dump()}


class Redeem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=1, max_length=100)


@router.get('/api/profile')
def get_profile(user=Depends(current_user)):
    with connect() as db:
        return credits.profile(db, user['id'])


@router.post('/api/profile/redeem')
def redeem(payload: Redeem, user=Depends(current_user)):
    raw = re.sub(r'[-\s]', '', payload.code).upper()
    if len(raw) != 24 or any(character not in credits.ALPHABET for character in raw):
        raise HTTPException(422, '卡密格式不正确，请检查并完整粘贴所购买的卡密')
    code = '-'.join(raw[index:index + 4] for index in range(0, 24, 4))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
        if account['is_admin']:
            raise HTTPException(409, '当前账号已开通模拟面试，无需兑换，卡密尚未使用')
        card = db.execute('SELECT * FROM vouchers WHERE code=?', (code,)).fetchone()
        if card is None:
            raise HTTPException(404, '卡密不存在，请检查输入或联系购买平台')
        if card['redeemed_at'] is not None:
            raise HTTPException(409, '该卡密已被兑换，请勿重复使用')
        db.execute('UPDATE vouchers SET redeemed_by=?,redeemed_at=?,redeemed_username=? WHERE id=? AND redeemed_at IS NULL',
                   (user['id'], time.time(), account['username'], card['id']))
        credits.adjust(db, user['id'], account['interview_credits'] + card['credits'],
                       kind='redemption', amount_fen=card['price_fen'], reference=str(card['id']))
        return credits.profile(db, user['id'])


@router.get('/api/admin/credit-settings')
def get_settings(user=Depends(administrator)):
    from app.config import load_config
    with connect() as db:
        return {'default_credits': credits.default_credits(db), 'packages': credits.packages(db),
                'max_voucher_batch': load_config()['credits']['max_voucher_batch']}


@router.patch('/api/admin/credit-settings')
def update_settings(payload: CreditSettings, user=Depends(administrator)):
    with connect() as db:
        db.execute("UPDATE app_settings SET value=? WHERE key='default_interview_credits'", (str(payload.default_credits),))
    return get_settings(user)


@router.post('/api/admin/vouchers', status_code=201)
def create_vouchers(payload: VoucherBatch, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return JSONResponse(credits.generate_vouchers(db, payload.package, payload.count), status_code=201,
                            headers={'Cache-Control': 'no-store'})


def voucher_filters(package, status, query='', batch=''):
    clauses, values = [], []
    if package:
        clauses.append('v.package=?'); values.append(package)
    if status != 'all':
        clauses.append('v.redeemed_at IS NULL' if status == 'unused' else 'v.redeemed_at IS NOT NULL')
    if query:
        clauses.append('(instr(v.code,?)>0 OR instr(COALESCE(u.username,v.redeemed_username),?)>0)'); values.extend((query.upper(), query))
    if batch:
        clauses.append('v.batch=?'); values.append(batch)
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), values


@router.get('/api/admin/vouchers')
def list_vouchers(package: Package | None = None, status: Status = 'all', q: str = Query('', max_length=100),
                  batch: str = Query('', max_length=24), page: int = Query(1, ge=1),
                  page_size: int = Query(50, ge=1, le=200), user=Depends(administrator)):
    where, values = voucher_filters(package, status, q.strip(), batch)
    with connect() as db:
        table = ' FROM vouchers v LEFT JOIN users u ON u.id=v.redeemed_by'
        counts = db.execute('SELECT COUNT(*) total,COALESCE(SUM(v.redeemed_at IS NULL),0) unused' + table + where, values).fetchone()
        rows = [dict(row) for row in db.execute('''SELECT v.id,v.code,v.package,v.credits,v.price_fen,v.batch,
            v.created,v.redeemed_at,COALESCE(u.username,NULLIF(v.redeemed_username,'') || '（已删除）') redeemed_by''' + table + where + ' ORDER BY v.id DESC LIMIT ? OFFSET ?',
            (*values, page_size, (page - 1) * page_size))]
        return JSONResponse({'items': rows, 'total': counts['total'], 'unused': counts['unused'],
                             'redeemed': counts['total'] - counts['unused'], 'page': page, 'page_size': page_size},
                            headers={'Cache-Control': 'no-store'})


@router.get('/api/admin/vouchers/export')
def export_vouchers(package: Package, status: Status = 'unused', batch: str = Query('', max_length=24),
                    q: str = Query('', max_length=100), user=Depends(administrator)):
    """Export one raw code per line for upload to a separate shop, with no shop API."""
    where, values = voucher_filters(package, status, q.strip(), batch)
    with connect() as db:
        codes = [row[0] for row in db.execute('SELECT v.code FROM vouchers v LEFT JOIN users u ON u.id=v.redeemed_by' + where + ' ORDER BY v.id', values)]
    return Response('\n'.join(codes) + ('\n' if codes else ''), media_type='text/plain; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="vouchers-{package}-{status}.txt"', 'Cache-Control': 'no-store'})
