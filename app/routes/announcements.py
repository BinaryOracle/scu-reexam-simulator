"""Authenticated announcement reads and administrator content management."""
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from app.db import connect
from app.services.auth import current_user, administrator
from app.services import announcements

router=APIRouter(tags=['公告'])


class Announcement(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=120)
    summary:str=Field(default='',max_length=500)
    cover_url:str=Field(default='',max_length=500)
    body_markdown:str=Field(default='',max_length=100000)
    blocks:list[dict]=Field(default_factory=list,max_length=100)
    remind_on_first_visit:bool=False


@router.get('/api/announcements')
def published(user=Depends(current_user)):
    with connect() as db: return announcements.list_items(db,user_id=user['id'])


@router.get('/api/announcements/{aid}')
def published_detail(aid:int,user=Depends(current_user)):
    with connect() as db: return announcements.get_item(db,aid,public=True,user_id=user['id'])


@router.post('/api/announcements/{aid}/dismiss-reminder')
def dismiss_reminder(aid:int,user=Depends(current_user)):
    with connect() as db: return announcements.dismiss_reminder(db,user['id'],aid)


@router.get('/api/announcements/assets/{asset_id}')
def image(asset_id:str,user=Depends(current_user)):
    with connect() as db: path,mime=announcements.image_path(db,asset_id)
    return FileResponse(path,media_type=mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/api/admin/announcements')
def admin_list(status:Literal['','draft','published','withdrawn']='',q:str=Query('',max_length=120),
               page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=100),actor=Depends(administrator)):
    with connect() as db: return announcements.list_items(db,admin=True,status=status,q=q,page=page,page_size=page_size)


@router.post('/api/admin/announcements',status_code=201)
def create(payload:Announcement,actor=Depends(administrator)):
    with connect() as db: return announcements.save(db,actor['id'],aid=None,**payload.model_dump())


@router.post('/api/admin/announcements/preview')
def preview(payload:Announcement,actor=Depends(administrator)):
    with connect() as db: return announcements.preview(db,**payload.model_dump())


@router.put('/api/admin/announcements/{aid}')
def update(aid:int,payload:Announcement,actor=Depends(administrator)):
    with connect() as db: return announcements.save(db,actor['id'],aid=aid,**payload.model_dump())


@router.delete('/api/admin/announcements/{aid}',status_code=204)
def delete(aid:int,actor=Depends(administrator)):
    with connect() as db: announcements.delete_item(db,aid)
    return Response(status_code=204)


@router.post('/api/admin/announcements/{aid}/status')
def status(aid:int,payload:dict,actor=Depends(administrator)):
    value=payload.get('status') if set(payload)=={'status'} else None
    if value not in ('published','withdrawn','draft'): raise HTTPException(422,'公告状态无效')
    with connect() as db: return announcements.set_status(db,aid,actor['id'],value)


@router.post('/api/admin/announcements/assets',status_code=201)
async def upload(file:UploadFile=File(...),actor=Depends(administrator)):
    data=await file.read(5*1024*1024+1)
    with connect() as db: return announcements.upload_image(db,actor['id'],data,file.content_type or '')


@router.get('/api/admin/announcements/assets/{asset_id}')
def admin_image(asset_id:str,actor=Depends(administrator)):
    with connect() as db: path,mime=announcements.image_path(db,asset_id,admin=True)
    return FileResponse(path,media_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
