"""Authenticated home content and administrator layout publishing."""
from fastapi import APIRouter, Depends
from app.db import connect
from app.services.auth import current_user, administrator
from app.services import home_layout

router = APIRouter(tags=['首页编排'])


@router.get('/api/home/layout')
def published(user=Depends(current_user)):
    with connect() as db:
        return home_layout.read(db, public=True)


@router.get('/api/admin/home-layout')
def draft(user=Depends(administrator)):
    with connect() as db:
        return home_layout.read(db)


@router.put('/api/admin/home-layout')
def publish(payload: home_layout.Layout, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return home_layout.save(db, payload, user)
