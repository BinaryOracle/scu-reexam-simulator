"""Invitation history and administrator-managed package purchases and cash rebate state."""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from app.db import connect
from app.services.auth import administrator, current_user, managed_user
from app.services import referrals, service_packages

router = APIRouter()


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: StrictStr = Field(min_length=1, max_length=100)
    description: StrictStr = Field(default='', max_length=50000)
    price_yuan: Decimal = Field(ge=0, le=100000000, decimal_places=2)
    rebate_percent: Decimal = Field(default=Decimal('5'), ge=0, le=100, decimal_places=2)
    enabled: StrictBool = True

    @field_validator('price_yuan', 'rebate_percent', mode='before')
    @classmethod
    def no_boolean_amount(cls, value):
        if isinstance(value, bool):
            raise ValueError('金额和比例必须为数字')
        return value


class PackageUpdate(PackageCreate):
    name: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    description: StrictStr | None = Field(default=None, max_length=50000)
    price_yuan: Decimal | None = Field(default=None, ge=0, le=100000000, decimal_places=2)
    rebate_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    enabled: StrictBool | None = None

    @field_validator('name', 'description', 'price_yuan', 'rebate_percent', 'enabled')
    @classmethod
    def no_null_fields(cls, value):
        if value is None:
            raise ValueError('配置项不能为 null')
        return value


class PurchaseCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    package_id: StrictInt = Field(gt=0)


class RebateUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    redeemed: StrictBool


def _ordinary_user(db, uid, actor):
    if managed_user(db, uid, actor)['is_admin']:
        raise HTTPException(404, '普通用户不存在')


@router.get('/api/profile/referrals')
def referral_profile(user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN')
        return referrals.profile(db, user['id'])


@router.get('/api/profile/referrals/{uid}/package-purchases')
def referred_purchases(uid: int, user=Depends(current_user)):
    with connect() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND referrer_id=? AND is_admin=0', (uid, user['id'])).fetchone():
            raise HTTPException(404, '邀请记录不存在')
        return service_packages.purchases(db, uid)


@router.get('/api/admin/service-packages')
def packages(user=Depends(administrator)):
    with connect() as db:
        return service_packages.catalog(db)


@router.post('/api/admin/service-packages', status_code=201)
def create_package(payload: PackageCreate, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return service_packages.save_package(db, None, payload.model_dump())


@router.patch('/api/admin/service-packages/{pid}')
def update_package(pid: int, payload: PackageUpdate, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return service_packages.save_package(db, pid, payload.model_dump(exclude_unset=True))


@router.get('/api/admin/users/{uid}/package-purchases')
def user_purchases(uid: int, user=Depends(administrator)):
    with connect() as db:
        _ordinary_user(db, uid, user)
        return service_packages.purchases(db, uid)


@router.post('/api/admin/users/{uid}/package-purchases', status_code=201)
def add_purchase(uid: int, payload: PurchaseCreate, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _ordinary_user(db, uid, user)
        return service_packages.add_purchase(db, uid, payload.package_id, user['id'])


@router.delete('/api/admin/users/{uid}/package-purchases/{purchase_id}', status_code=204)
def remove_purchase(uid: int, purchase_id: int, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _ordinary_user(db, uid, user)
        service_packages.remove_purchase(db, uid, purchase_id)
    return Response(status_code=204)


@router.patch('/api/admin/users/{uid}/rebate')
def update_rebate(uid: int, payload: RebateUpdate, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _ordinary_user(db, uid, user)
        return service_packages.settle(db, uid, payload.redeemed)
