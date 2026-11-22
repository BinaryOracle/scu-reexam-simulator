"""Authenticated AI trend reading and administrator generation/editing APIs."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db import connect
from app.services.auth import administrator, current_user
from app.services import trends

router = APIRouter(tags=['热点趋势'])
Period = Literal['week', 'month', 'year']


class TrendGeneration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    period: Period


class TrendEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body_markdown: str = Field(min_length=1, max_length=100000)


@router.get('/api/trends/current')
def current_period(period: Period = 'week', user=Depends(current_user)):
    with connect() as db:
        return {'item': trends.current_trend(db, period=period)}


@router.post('/api/admin/trends/generate', status_code=201)
def generate(payload: TrendGeneration, actor=Depends(administrator)):
    with connect() as db:
        return trends.generate(db, actor['id'], **payload.model_dump())


@router.patch('/api/admin/trends/{trend_id}')
def edit(trend_id: int, payload: TrendEdit, actor=Depends(administrator)):
    with connect() as db:
        if not db.execute('SELECT 1 FROM ai_trends WHERE id=?', (trend_id,)).fetchone():
            raise HTTPException(404, '趋势记录不存在')
        return trends.edit(db, trend_id, actor['id'], payload.body_markdown)
