"""Authenticated daily practice, private submissions and administrator moderation."""
import json
import time
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from app.db import connect
from app.config import load_config
from app.services.auth import current_user, administrator, training_user, require_training
from app.services import training as practice
from app.services import training_catalog as catalog
from app.services.training_schema import ASSETS
from app.services import contribution_rewards
from app.services import leaderboard as leaderboard_service

router = APIRouter(tags=['每日训练'])


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Question(Payload):
    collection_id: str = Field(max_length=40)
    question: str = Field(min_length=1, max_length=100000)
    answer: str = Field(default='', max_length=200000)


class Version(Payload):
    version: StrictInt = Field(ge=1)


class QuestionEdit(Question, Version):
    pass


class OfficialEdit(QuestionEdit):
    active: StrictBool = True


class Round(Payload):
    section_id: Literal['interview', 'written_c', 'written_ai'] = 'interview'
    collection_id: str = Field(default='', max_length=40)
    source: Literal['all', 'favorites'] = 'all'
    mode: Literal['random', 'sequential'] = 'random'
    question_count: Annotated[StrictInt, Field(ge=1)] | Literal['all'] | None = None


class Rating(Payload):
    rating: Literal['again', 'known', 'done'] = 'done'


class Favorite(Payload):
    favorite: StrictBool


class Active(Payload):
    active: StrictBool


class VersionActive(Active, Version):
    pass


class Review(Version):
    approve: StrictBool
    reason: str = Field(default='', max_length=2000)


class Import(Payload):
    items: list[Question] = Field(min_length=1, max_length=1000)


class Settings(Payload):
    daily_goal: StrictInt = Field(ge=1, le=100)
    round_size: StrictInt = Field(ge=1, le=50)


class ContributionPolicy(Payload):
    questions_per_reward: StrictInt = Field(ge=1,le=10000)
    credits_per_reward: StrictInt = Field(ge=1,le=1000000)


@router.get('/api/training/home')
def home(section_id: str = Query('interview', max_length=40), user=Depends(current_user)):
    with connect() as db:
        return practice.home(db, user, section_id)

@router.get('/api/leaderboard')
def leaderboard(user=Depends(current_user)):
    with connect() as db:
        return leaderboard_service.snapshot(db, user)


@router.get('/api/training/contribution-rewards')
def contribution_progress(user=Depends(current_user)):
    with connect() as db: return contribution_rewards.progress(db,user['id'])


@router.get('/api/admin/training/contribution-rewards')
def contribution_admin(page:int=Query(1,ge=1),user=Depends(administrator)):
    with connect() as db: return contribution_rewards.admin_summary(db,page)


@router.put('/api/admin/training/contribution-rewards')
def contribution_policy(payload:ContributionPolicy,user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        contribution_rewards.set_policy(db,user['id'],payload.questions_per_reward,payload.credits_per_reward)
        return contribution_rewards.admin_summary(db)


@router.post('/api/training/sessions', status_code=201)
def start(payload: Round, user=Depends(training_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.start_session(db, user, payload.collection_id, payload.source, payload.mode, payload.question_count, payload.section_id)


@router.get('/api/training/sessions/{sid}')
def session(sid: int, user=Depends(training_user)):
    with connect() as db:
        return practice.get_session(db, sid, user['id'])


@router.post('/api/training/sessions/{sid}/cards/{card_id}/complete')
def complete(sid: int, card_id: int, payload: Rating, user=Depends(training_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.complete(db, user, sid, card_id, payload.rating)


@router.post('/api/training/sessions/{sid}/end', status_code=204)
def end(sid: int, user=Depends(current_user)):
    with connect() as db:
        practice.get_session(db, sid, user['id'])
        db.execute("UPDATE training_sessions SET status='ended' WHERE id=? AND status='active'", (sid,))
    return Response(status_code=204)


@router.post('/api/training/checkin')
def checkin(user=Depends(training_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.checkin(db, user)


@router.get('/api/training/questions')
def questions(section_id: str = Query('interview', max_length=40), mine: bool = False, favorites: bool = False, collection_id: str = Query('', max_length=40),
              q: str = Query('', max_length=200), page: int = Query(1, ge=1), user=Depends(current_user)):
    if not mine:
        require_training(user)
    with connect() as db:
        return catalog.list_questions(db, user, mine=mine, favorites=favorites, collection_id=collection_id, q=q, page=page, section_id=section_id)


@router.post('/api/training/questions', status_code=201)
def create(payload: Question, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.create_question(db, user, payload.model_dump())


@router.patch('/api/training/questions/{qid}')
def edit(qid: int, payload: QuestionEdit, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.update_question(db, user, qid, payload.model_dump(), payload.version)


@router.delete('/api/training/questions/{qid}', status_code=204)
def delete(qid: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = catalog.editable(db, qid, user)
        db.execute("UPDATE training_questions SET deleted=1,visibility='private',version=version+1,updated=? WHERE id=?", (time.time(), qid))
        catalog.event(db, qid, user, 'delete', row['version'] + 1)
    return Response(status_code=204)


@router.put('/api/training/questions/{qid}/favorite')
def favorite(qid: int, payload: Favorite, user=Depends(current_user)):
    with connect() as db:
        if payload.favorite:
            catalog.require_access(db, qid, user['id'])
            db.execute('INSERT OR IGNORE INTO training_favorites VALUES (?,?,?)', (user['id'], qid, time.time()))
        else:
            db.execute('DELETE FROM training_favorites WHERE user_id=? AND question_id=?', (user['id'], qid))
    return {'favorite': payload.favorite}


@router.post('/api/training/questions/{qid}/submit')
def submit(qid: int, payload: Version, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.submit(db, user, qid, payload.version)


@router.post('/api/training/questions/{qid}/withdraw')
def withdraw(qid: int, payload: Version, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.submit(db, user, qid, payload.version, withdraw=True)


@router.get('/api/training/questions/{qid}/images/{index}')
def image(qid: int, index: int, user=Depends(current_user)):
    with connect() as db:
        row = catalog.get_question(db, qid)
        if row['owner_user_id'] != user['id']:
            require_training(user)
        if not catalog.accessible(row, user['id']):
            if not user['is_admin']:
                raise HTTPException(404, '图片不存在')
            catalog.reviewable(db, qid, user)
        images = json.loads(row['images'])
        if index < 0 or index >= len(images):
            raise HTTPException(404, '图片不存在')
        path = (ASSETS / 'images' / images[index]).resolve()
        if not path.is_relative_to((ASSETS / 'images').resolve()) or not path.is_file():
            raise HTTPException(404, '参考图片不存在')
    return FileResponse(path, headers={'Cache-Control': 'no-store'})


@router.post('/api/training/import/preview')
async def preview(file: UploadFile = File(...), user=Depends(current_user)):
    config = load_config()['training']
    raw = await file.read(config['max_import_bytes'] + 1)
    if len(raw) > config['max_import_bytes']:
        raise HTTPException(413, '导入文件超过大小限制')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(422, '请上传 UTF-8 编码的 JSON 题目列表') from error
    if not isinstance(data, list) or not 1 <= len(data) <= config['max_import_items']:
        raise HTTPException(422, f"JSON 必须为包含1～{config['max_import_items']}道题的列表")
    items, errors = [], []
    with connect() as db:
        for number, item in enumerate(data, 1):
            try:
                value = Question.model_validate(item).model_dump()
                items.append(catalog.validate_item(db, value))
            except (ValidationError, HTTPException) as error:
                detail = error.detail if isinstance(error, HTTPException) else '请检查集合、题干和参考答案字段'
                errors.append(f'第 {number} 题：{detail}')
    return dict(items=items, count=len(items), errors=errors)


@router.post('/api/training/import', status_code=201)
def import_questions(payload: Import, user=Depends(current_user)):
    if len(payload.items) > load_config()['training']['max_import_items']:
        raise HTTPException(422, '本批导入题数超过限制')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for item in payload.items:
            catalog.create_question(db, user, item.model_dump())
    return {'created': len(payload.items)}


@router.get('/api/admin/training/settings')
def settings(user=Depends(administrator)):
    with connect() as db:
        return practice.settings(db)


@router.patch('/api/admin/training/settings')
def change_settings(payload: Settings, user=Depends(administrator)):
    with connect() as db:
        for key, value in payload.model_dump().items():
            db.execute('UPDATE app_settings SET value=? WHERE key=?', (str(value), 'training_' + key))
        return practice.settings(db)


@router.patch('/api/admin/training/collections/{cid}', status_code=204)
def collection_state(cid: str, payload: Active, user=Depends(administrator)):
    with connect() as db:
        if not db.execute('UPDATE training_collections SET active=? WHERE id=?', (payload.active, cid)).rowcount:
            raise HTTPException(404, '集合不存在')
    return Response(status_code=204)


@router.get('/api/admin/training/questions')
def admin_questions(section_id: str = Query('', max_length=40), status: Literal['all', 'pending', 'public'] = 'all', collection_id: str = Query('', max_length=40),
                    q: str = Query('', max_length=200), page: int = Query(1, ge=1), user=Depends(administrator)):
    with connect() as db:
        return catalog.list_questions(db, user, admin_status=status, collection_id=collection_id, q=q, page=page, section_id=section_id)


@router.post('/api/admin/training/questions', status_code=201)
def official(payload: Question, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.create_question(db, user, payload.model_dump(), official=True)


@router.patch('/api/admin/training/questions/{qid}')
def edit_official(qid: int, payload: OfficialEdit, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.update_question(db, user, qid, payload.model_dump(), payload.version, official=True, active=payload.active)


@router.post('/api/admin/training/questions/{qid}/review')
def review(qid: int, payload: Review, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.review(db, user, qid, payload.version, payload.approve, payload.reason)


@router.post('/api/admin/training/questions/{qid}/active')
def question_state(qid: int, payload: VersionActive, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = catalog.reviewable(db, qid, user)
        catalog.check_version(row, payload.version)
        db.execute('UPDATE training_questions SET active=?,version=version+1,updated=? WHERE id=?', (payload.active, time.time(), qid))
        catalog.event(db, qid, user, 'enable' if payload.active else 'disable', payload.version + 1)
        return catalog.serialize(db, catalog.get_question(db, qid), user['id'])


@router.get('/api/admin/training/rewards')
def rewards(page: int = Query(1, ge=1), user=Depends(administrator)):
    with connect() as db:
        query = ''' FROM training_reward_grants g JOIN users u ON u.id=g.user_id WHERE (? OR u.is_admin=0)'''
        total = db.execute('SELECT COUNT(*)' + query, (user['is_superadmin'],)).fetchone()[0]
        items = [dict(row) for row in db.execute('SELECT u.username,g.date,g.streak,g.credits' + query + ' ORDER BY g.id DESC LIMIT 12 OFFSET ?',
                                                (user['is_superadmin'], (page - 1) * 12))]
        return dict(items=items, total=total, page=page, page_size=12)
