"""Balance and voucher endpoints; the external shop only receives exported codes."""
import re
import secrets
import sqlite3
import time
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from app.db import connect
from app.services.auth import administrator, current_user
from app.services import credits, points

router = APIRouter()
Package = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')]
Status = Literal['all', 'unused', 'redeemed']


class VoucherBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    package: Package
    count: StrictInt = Field(ge=1, le=10000)


class CreditSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    default_credits: StrictInt | None = Field(default=None, ge=0, le=1000000)
    interview_points_cost: StrictInt | None = Field(default=None, ge=1, le=1000000)
    invite_signup_points: StrictInt | None = Field(default=None, ge=0, le=1000000)
    training_checkin_points_per_week: StrictInt | None = Field(default=None, ge=0, le=1000000)
    coding_checkin_points_per_week: StrictInt | None = Field(default=None, ge=0, le=1000000)
    training_questions_per_reward: StrictInt | None = Field(default=None, ge=1, le=10000)
    training_contribution_points: StrictInt | None = Field(default=None, ge=1, le=1000000)
    coding_questions_per_reward: StrictInt | None = Field(default=None, ge=1, le=10000)
    coding_contribution_points: StrictInt | None = Field(default=None, ge=1, le=1000000)
    leaderboard_rewards: list[StrictInt] | None = Field(default=None, min_length=3, max_length=3)

    @field_validator('leaderboard_rewards')
    @classmethod
    def validate_leaderboard_rewards(cls, value):
        if value is not None and any(item < 0 or item > 1000000 for item in value):
            raise ValueError('周榜奖励需在 0 到 1000000 积分之间')
        return value


class VoucherPackage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    price_fen: StrictInt = Field(ge=1, le=100000000)
    credits: StrictInt = Field(ge=1, le=1000000)


@router.post('/api/admin/voucher-packages', status_code=201)
def create_package(payload: VoucherPackage, user=Depends(administrator)):
    key = 'pkg_' + secrets.token_hex(12)
    with connect() as db:
        try:
            db.execute('INSERT INTO voucher_packages(id,price_fen,credits,created) VALUES (?,?,?,?)',
                       (key, payload.price_fen, payload.credits, time.time()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, '相同金额与积分的套餐已存在，请直接选择') from error
    return {'id': key, **payload.model_dump()}


@router.delete('/api/admin/voucher-packages/{package}', status_code=204)
def delete_package(package: str, user=Depends(administrator)):
    """Permanently delete a package and every issued voucher that belongs to it."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        exists = db.execute('SELECT 1 FROM voucher_packages WHERE id=? AND deleted=0', (package,)).fetchone()
        if not exists:
            raise HTTPException(404, '套餐不存在或已删除')
        db.execute('DELETE FROM vouchers WHERE package=?', (package,))
        db.execute('DELETE FROM voucher_packages WHERE id=?', (package,))
    return Response(status_code=204)


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
        points.adjust(db, user['id'], card['credits'], kind='redemption', reference=str(card['id']))
        return credits.profile(db, user['id'])


@router.get('/api/admin/credit-settings')
def get_settings(user=Depends(administrator)):
    from app.config import load_config
    with connect() as db:
        return {'default_credits': credits.default_credits(db), 'packages': credits.packages(db),
                'interview_points_cost': points.cost(db),
                'reward_rules': points.reward_rules(db),
                'max_voucher_batch': load_config()['credits']['max_voucher_batch']}


@router.patch('/api/admin/credit-settings')
def update_settings(payload: CreditSettings, user=Depends(administrator)):
    with connect() as db:
        changes = payload.model_dump(exclude_none=True)
        if payload.default_credits is not None:
            db.execute("UPDATE app_settings SET value=? WHERE key='default_interview_credits'", (str(payload.default_credits),))
        if payload.interview_points_cost is not None:
            db.execute("UPDATE app_settings SET value=? WHERE key='interview_points_cost'", (str(payload.interview_points_cost),))
        for key in ('invite_signup_points', 'training_checkin_points_per_week', 'coding_checkin_points_per_week'):
            if key in changes:
                db.execute('UPDATE app_settings SET value=? WHERE key=?', (str(changes[key]), key))
        if 'leaderboard_rewards' in changes:
            import json
            db.execute("UPDATE app_settings SET value=? WHERE key='leaderboard_rewards'", (json.dumps(changes['leaderboard_rewards']),))
        if any(key in changes for key in ('training_questions_per_reward', 'training_contribution_points')):
            from app.services import contribution_rewards
            current = contribution_rewards.current_policy(db)
            contribution_rewards.set_policy(db, user['id'], changes.get('training_questions_per_reward', current['questions_per_reward']),
                                             changes.get('training_contribution_points', current['credits_per_reward']))
        if any(key in changes for key in ('coding_questions_per_reward', 'coding_contribution_points')):
            from app.services import coding_practice
            current = coding_practice.settings(db)
            coding_practice.set_settings(db, user, changes.get('coding_questions_per_reward', current['questions_per_reward']),
                                          changes.get('coding_contribution_points', current['credits_per_reward']))
    return get_settings(user)


class Purchase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product: Literal['interview'] = 'interview'
    quantity: StrictInt = Field(default=1, ge=1, le=10000)
    idempotency_key: str = Field(min_length=8, max_length=100)
    expected_unit_cost: StrictInt = Field(ge=1, le=1000000)


@router.get('/api/profile/shop')
def shop(user=Depends(current_user)):
    with connect() as db:
        return points.shop(db, user['id'])


@router.post('/api/profile/purchases')
def purchase(payload: Purchase, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return points.purchase(db, user['id'], payload.quantity, payload.idempotency_key, payload.expected_unit_cost)


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
