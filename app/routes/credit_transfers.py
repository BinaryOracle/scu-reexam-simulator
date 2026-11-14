"""Authenticated per-account transfer receipts and idempotent transfers."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from app.db import connect
from app.services.auth import current_user
from app.services import credit_transfers

router = APIRouter(prefix='/api/profile')


class Transfer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recipient: str = Field(min_length=1, max_length=1000)
    credits: StrictInt = Field(ge=1, le=1000000)
    idempotency_key: str = Field(min_length=8, max_length=128)


@router.post('/transfers', status_code=201)
def transfer(payload: Transfer, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return credit_transfers.transfer(db, user['id'], payload.recipient, payload.credits, payload.idempotency_key)


@router.get('/transfers')
def history(page: int = Query(1, ge=1), user=Depends(current_user)):
    with connect() as db:
        return credit_transfers.history(db, user['id'], page)
