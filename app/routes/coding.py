"""Authenticated coding study and administrator catalog/reward APIs."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from app.db import connect
from app.services.auth import administrator, current_user
from app.services import coding_catalog as catalog
from app.services import coding_practice as practice
from app.services import luogu_catalog

router = APIRouter(tags=['算法带刷'])


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Sample(Payload):
    input: str = Field(max_length=100000)
    output: str = Field(max_length=100000)


class Question(Payload):
    stage_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(default='', max_length=300)
    difficulty: StrictInt = Field(default=1, ge=1, le=5)
    stars: StrictInt = Field(default=3, ge=1, le=5)
    position: StrictInt = Field(default=0, ge=0, le=1000000)
    statement: str = Field(default='', max_length=200000)
    samples: list[Sample] = Field(default_factory=list, max_length=50)
    reference_code: str = Field(default='', max_length=200000)
    reference_language: Literal['cpp11', 'c', 'python3'] = 'cpp11'
    source_url: str = Field(default='', max_length=2000)
    remote_problem_id: str = Field(default='', max_length=32)
    judge_mode: Literal['luogu', 'samples'] = 'samples'
    active: StrictBool = True


class QuestionEdit(Payload):
    version: StrictInt = Field(ge=1)
    stage_id: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    topic: str | None = Field(default=None, max_length=300)
    difficulty: StrictInt | None = Field(default=None, ge=1, le=5)
    stars: StrictInt | None = Field(default=None, ge=1, le=5)
    position: StrictInt | None = Field(default=None, ge=0, le=1000000)
    statement: str | None = Field(default=None, max_length=200000)
    samples: list[Sample] | None = Field(default=None, max_length=50)
    reference_code: str | None = Field(default=None, max_length=200000)
    reference_language: Literal['cpp11', 'c', 'python3'] | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    remote_problem_id: str | None = Field(default=None, max_length=32)
    judge_mode: Literal['luogu', 'samples'] | None = None
    active: StrictBool | None = None

    @field_validator('*', mode='before')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('字段不得为 null；不修改的字段请省略')
        return value


class Version(Payload):
    version: StrictInt = Field(ge=1)


class Review(Version):
    approve: StrictBool
    reason: str = Field(default='', max_length=5000)


class Stage(Payload):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    position: StrictInt = Field(default=0, ge=0, le=1000000)
    active: StrictBool = True

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError('阶段名称不能为空')
        return value.strip()


class StageEdit(Payload):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    position: StrictInt | None = Field(default=None, ge=0, le=1000000)
    active: StrictBool | None = None

    @field_validator('*', mode='before')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('字段不得为 null')
        return value

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError('阶段名称不能为空')
        return value.strip()


class Settings(Payload):
    questions_per_reward: StrictInt = Field(ge=1, le=10000)
    credits_per_reward: StrictInt = Field(ge=1, le=10000)


class Submission(Payload):
    language: Literal['cpp11', 'c', 'python3'] = 'cpp11'
    source: str = Field(min_length=1, max_length=100000)


class RemoteResult(Payload):
    remote_submission_id: str = Field(default='', max_length=64, pattern=r'^\d*$')
    remote_problem_id: str = Field(default='', max_length=32)
    status: Literal['Submitted', 'Judging', 'Accepted', 'Wrong Answer', 'Output Limit Exceeded',
                    'Time Limit Exceeded', 'Memory Limit Exceeded', 'Runtime Error', 'Compile Error',
                    'System Error', 'Submission Failed']
    detail: str = Field(default='', max_length=10000)


class LuoguImport(Payload):
    problem_id: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z][A-Za-z0-9_-]*$')


@router.get('/api/coding/home')
def home(user=Depends(current_user)):
    with connect() as db:
        return practice.home(db, user)


@router.get('/api/coding/questions')
def questions(stage_id: str = Query('', max_length=100), q: str = Query('', max_length=300), mine: bool = False,
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    with connect() as db:
        return catalog.list_questions(db, user, stage_id=stage_id, q=q, mine=mine, page=page, page_size=page_size)


@router.get('/api/coding/questions/{qid}')
def question(qid: int, user=Depends(current_user)):
    with connect() as db:
        return catalog.serialize(db, catalog.require_access(db, qid, user['id']), user['id'])


@router.post('/api/coding/questions', status_code=201)
def create(payload: Question, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.create_question(db, user, payload.model_dump())


@router.patch('/api/coding/questions/{qid}')
def edit(qid: int, payload: QuestionEdit, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.update_question(db, user, qid, payload.model_dump(exclude_unset=True))


@router.delete('/api/coding/questions/{qid}', status_code=204)
def delete(qid: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        catalog.delete_question(db, user, qid)
    return Response(status_code=204)


@router.post('/api/coding/questions/{qid}/submit')
def submit(qid: int, payload: Version, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.submit(db, user, qid, payload.version)


@router.post('/api/coding/daily')
def daily(user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.assign_daily(db, user)


@router.post('/api/coding/checkin')
def checkin(user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.checkin(db, user)


@router.post('/api/coding/questions/{qid}/submissions')
def submission(qid: int, payload: Submission, user=Depends(current_user)):
    from app.services import coding_judge
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        result, samples = practice.new_submission(db, qid, user, payload.language, payload.source)
    if result['judge_mode'] == 'luogu':
        return result
    failure = None
    try:
        evaluated = coding_judge.evaluate(payload.language, payload.source, samples)
    except coding_judge.JudgeUnavailable as error:
        failure = HTTPException(503, str(error))
        evaluated = {'status': 'System Error', 'detail': str(error), 'passed_cases': 0, 'total_cases': len(samples)}
    except ValueError as error:
        failure = HTTPException(422, str(error))
        evaluated = {'status': 'System Error', 'detail': str(error), 'passed_cases': 0, 'total_cases': len(samples)}
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        practice.finish_local(db, result['id'], evaluated)
        completed = practice.submission(db, result['id'], user)
    if failure:
        raise failure
    return completed


@router.get('/api/coding/questions/{qid}/submissions')
def submissions(qid: int, user=Depends(current_user)):
    with connect() as db:
        # Personal history remains readable after a question is withdrawn or tombstoned.
        owned = db.execute('SELECT 1 FROM coding_submissions WHERE question_id=? AND user_id=? LIMIT 1', (qid, user['id'])).fetchone()
        if not owned:
            catalog.require_access(db, qid, user['id'])
        rows = db.execute('SELECT id FROM coding_submissions WHERE question_id=? AND user_id=? ORDER BY id DESC LIMIT 100', (qid, user['id'])).fetchall()
        return {'items': [practice.submission(db, row['id'], user) for row in rows]}


@router.get('/api/coding/submissions/{sid}')
def submission_detail(sid: int, user=Depends(current_user)):
    with connect() as db:
        return practice.submission(db, sid, user)


@router.post('/api/coding/submissions/{sid}/remote-result')
def remote_result(sid: int, payload: RemoteResult, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.remote_result(db, sid, user, payload.model_dump())


@router.get('/api/admin/coding/stages')
def admin_stages(user=Depends(administrator)):
    with connect() as db:
        return {'items': catalog.stages(db)}


@router.post('/api/admin/coding/stages', status_code=201)
def create_stage(payload: Stage, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.save_stage(db, payload.model_dump())


@router.patch('/api/admin/coding/stages/{stage_id}')
def edit_stage(stage_id: str, payload: StageEdit, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.save_stage(db, payload.model_dump(exclude_unset=True), stage_id)


@router.delete('/api/admin/coding/stages/{stage_id}', status_code=204)
def delete_stage(stage_id: str, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        catalog.delete_stage(db, stage_id)
    return Response(status_code=204)


@router.get('/api/admin/coding/questions')
def admin_questions(stage_id: str = Query('', max_length=100), q: str = Query('', max_length=300),
                    status: Literal['', 'all', 'pending', 'approved', 'public', 'rejected', 'draft'] = '',
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(administrator)):
    with connect() as db:
        return catalog.list_questions(db, user, stage_id=stage_id, q=q, status=status, page=page, page_size=page_size)


@router.post('/api/admin/coding/questions', status_code=201)
def admin_create(payload: Question, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.create_question(db, user, payload.model_dump(), admin=True)


@router.patch('/api/admin/coding/questions/{qid}')
def admin_edit(qid: int, payload: QuestionEdit, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.update_question(db, user, qid, payload.model_dump(exclude_unset=True), admin=True)


@router.delete('/api/admin/coding/questions/{qid}', status_code=204)
def admin_delete(qid: int, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        catalog.delete_question(db, user, qid, admin=True)
    return Response(status_code=204)


@router.post('/api/admin/coding/questions/{qid}/review')
def review(qid: int, payload: Review, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return catalog.review(db, user, qid, payload.version, payload.approve, payload.reason)


@router.get('/api/admin/coding/settings')
def settings(user=Depends(administrator)):
    with connect() as db:
        return practice.settings(db)


@router.put('/api/admin/coding/settings')
def change_settings(payload: Settings, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return practice.set_settings(db, user, payload.questions_per_reward, payload.credits_per_reward)


@router.post('/api/admin/coding/import-luogu')
def import_luogu(payload: LuoguImport, user=Depends(administrator)):
    try:
        result = luogu_catalog.problem(payload.problem_id)
    except luogu_catalog.LuoguCatalogError as error:
        raise HTTPException(502, str(error)) from error
    if not result['statement'].strip():
        raise HTTPException(502, '洛谷没有返回完整题面，请稍后重试或保留原题链接')
    return result | {'remote_problem_id': result['problem_id'], 'judge_mode': 'luogu',
                     'source_url': f"https://www.luogu.com.cn/problem/{result['problem_id']}"}
