"""Signed-in referral details and administrator-managed service settlements."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from app.db import connect
from app.services.auth import administrator, current_user
from app.services import referrals

router = APIRouter()


@router.get('/api/profile/referrals')
def referral_profile(user=Depends(current_user)):
    with connect() as db:
        return referrals.profile(db, user['id'])


class PurchaseServiceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    purchase_service: StrictStr = Field(max_length=160)
    rebate_redeemed: StrictBool


@router.patch('/api/admin/users/{uid}/purchase-service')
def update_purchase_service(uid: int, payload: PurchaseServiceUpdate, user=Depends(administrator)):
    with connect() as db:
        return referrals.set_purchase_service(db, uid, payload.purchase_service.strip(), payload.rebate_redeemed)
