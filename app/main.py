import json
import re
import secrets
import shutil
import time
from pathlib import Path
from fastapi import FastAPI, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import StreamingResponse
import io
import zipfile
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, StrictInt, field_validator
from typing import Annotated
from app.services.problem_content import public_problem
from app.config import load_config, ROOT
from app.db import connect, initialize
from app.services import ai, judge, expert_context, speech
from app.services.security import verify_password
from app.services.password_vault import PasswordVaultError, encrypt_password
from app.services.auth import current_user, administrator, interview_user, exam_user, issue_session, public_user
from app.services.interviews import details, interview, active_interview, require_stage, summary, seed_answers
from app.services.contest_scoring import submission_score
from app.services.interview_clock import require_running, timing, timestamp
from app.services import question_bank
from app.services import luogu_catalog
from app.services import contest_access, home_layout
from app.routes.live import router as live_router
from app.routes.home_layout import router as home_layout_router
from app.routes.presentations import router as presentations_router
from app.routes.admin import router as admin_router
from app.routes.recordings import router as recordings_router
from app.routes.credits import router as credits_router
from app.routes.email_auth import router as email_auth_router
from app.routes.profile_account import router as profile_account_router

from app.routes.training import router as training_router
from app.routes.credit_transfers import router as credit_transfers_router
from app.routes.announcements import router as announcements_router
from app.routes.coding import router as coding_router
from app.routes.trends import router as trends_router

initialize()


@asynccontextmanager
async def lifespan(app):
    from app.services import trend_scheduler, leaderboard_scheduler
    trend_scheduler.start()
    leaderboard_scheduler.start()
    try:
        yield
    finally:
        trend_scheduler.stop()
        leaderboard_scheduler.stop()


app = FastAPI(title='复试模拟系统', lifespan=lifespan)


@app.exception_handler(PasswordVaultError)
async def password_vault_error(request, error):
    return JSONResponse(status_code=503, content={'detail': str(error)}, headers={'Cache-Control': 'no-store'})


app.include_router(admin_router)
app.include_router(recordings_router)
app.include_router(presentations_router)
app.include_router(credits_router)
app.include_router(email_auth_router)
app.include_router(profile_account_router)
app.include_router(training_router)
app.include_router(credit_transfers_router)
app.include_router(announcements_router)
app.include_router(coding_router)
app.include_router(trends_router)
app.include_router(home_layout_router)
app.include_router(live_router)
app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')

@app.get('/api/home/resources')
def home_resources(user=Depends(current_user)):
    with connect() as db:
        return [{**item, 'group': block['title']} for block in home_layout.read(db, public=True)['blocks']
                if block['type'] == 'resources' for item in block['items']]

class Login(BaseModel):
    username: str
    password: str
class PublicSample(BaseModel):
    input: str = Field(max_length=100000)
    output: str = Field(max_length=100000)
class Problem(BaseModel):
    id: int | None = None
    title: str = Field(min_length=1, max_length=100)
    statement: str = Field(min_length=1, max_length=100000)
    sample_input: str = ''
    sample_output: str = ''
    samples: list[PublicSample] = Field(default_factory=list, max_length=100)
    tests: list[dict[str, str]] = Field(default_factory=list, max_length=50)
    remote_problem_id: str = Field(default='', max_length=32)
    points: int = Field(default=100, ge=0, le=100000)
class ContestInfo(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=100)
    starts: float
    ends: float
    show_ranking: bool = True
    ranking_rule: str = Field(default='score', pattern='^(score|acm)$')

    @field_validator('title')
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip(): raise ValueError('请输入比赛名称')
        return value.strip()
class Contest(ContestInfo):
    judge_mode: str = Field(default='luogu', pattern='^(docker|luogu)$')
    problems: list[Problem] = Field(min_length=1, max_length=50)
    participant_ids: list[Annotated[StrictInt, Field(ge=1)]] = Field(default_factory=list, max_length=10000)
class ContestUpdate(ContestInfo):
    judge_mode: str = Field(default='luogu', pattern='^(docker|luogu)$')
    problems: list[Problem] | None = Field(default=None, min_length=1, max_length=50)
    participant_ids: list[Annotated[StrictInt, Field(ge=1)]] | None = Field(default=None, max_length=10000)
class Answer(BaseModel):
    transcript: str = Field(max_length=20000)
class InterviewTitle(BaseModel):
    title: str = Field(min_length=1, max_length=100)
class SubjectChoice(BaseModel):
    subject: str = Field(pattern='^(data_structures|operating_systems|computer_networks)$')
class Submission(BaseModel):
    language: str = Field(default='cpp11', pattern='^(cpp11|cpp14|c|python3|java|go)$')
    source: str = Field(min_length=1, max_length=30000)
class RemoteSubmissionResult(BaseModel):
    remote_submission_id: str = Field(default='', max_length=64)
    status: str = Field(pattern='^(Submitted|Judging|Accepted|Wrong Answer|Output Limit Exceeded|Time Limit Exceeded|Memory Limit Exceeded|Runtime Error|Compile Error|System Error|Submission Failed)$')
    detail: str = Field(default='', max_length=10000)

@app.get('/admin')
@app.get('/admin/')
@app.get('/')
def index():
    return FileResponse(ROOT / 'app/static/index.html', headers={'Cache-Control': 'no-cache'})

@app.get('/api/luogu-extension')
def luogu_extension():
    extension = ROOT / 'browser-extension'
    archive = io.BytesIO()
    with connect() as db:
        app_origin = db.execute("SELECT value FROM app_settings WHERE key='luogu_app_origin'").fetchone()['value']
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        manifest_path = extension / 'manifest.json'
        if not manifest_path.is_file(): raise HTTPException(503, '浏览器插件文件不完整')
        manifest = json.loads(manifest_path.read_text())
        manifest['host_permissions'] = ['https://www.luogu.com.cn/*', f'{app_origin}/*']
        bundle.writestr('browser-extension/manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr('browser-extension/extension-config.js', f'export const APP_ORIGIN = {json.dumps(app_origin)};\n')
        for name in ('background.js', 'app-content.js', 'options.html', 'options.js', 'README.md'):
            path = extension / name
            if not path.is_file(): raise HTTPException(503, '浏览器插件文件不完整')
            bundle.write(path, f'browser-extension/{name}')
    archive.seek(0)
    return StreamingResponse(archive, media_type='application/zip', headers={
        'Content-Disposition': 'attachment; filename="scu-luogu-bridge.zip"',
        'Cache-Control': 'no-store',
    })

@app.post('/api/login')
def login(payload: Login):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute('SELECT * FROM users WHERE username=?', (payload.username,)).fetchone()
        if not user or not user['is_active'] or not verify_password(payload.password, user['password']):
            raise HTTPException(401, '用户名或密码错误')
        if not user['password_ciphertext']:
            db.execute('UPDATE users SET password_ciphertext=? WHERE id=?', (encrypt_password(payload.password), user['id']))
        token = issue_session(db, user['id'])
        return {'token': token, **public_user(user)}

@app.get('/api/me')
def me(user=Depends(current_user)):
    return user

@app.post('/api/logout', status_code=204)
def logout(authorization: str = Header(), user=Depends(current_user)):
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE token=? AND user_id=?', (authorization[7:], user['id']))
    return Response(status_code=204)

@app.get('/api/interviews')
def interviews(user=Depends(interview_user)):
    with connect() as db:
        return [summary(x) for x in db.execute('SELECT * FROM interviews WHERE user_id=? ORDER BY id DESC', (user['id'],))]

@app.post('/api/interviews')
def create_interview(user=Depends(interview_user)):
    with connect() as db:
        iid = db.execute('INSERT INTO interviews(user_id,created,workflow_version) VALUES (?,?,5)', (user['id'], time.time())).lastrowid
        seed_answers(db, iid)
        return details(db, iid)

@app.get('/api/interviews/{iid}')
def get_interview(iid: int, user=Depends(interview_user)):
    with connect() as db:
        interview(db, iid, user)
        return details(db, iid)

@app.patch('/api/interviews/{iid}')
def rename_interview(iid: int, payload: InterviewTitle, user=Depends(interview_user)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, '名称不能为空')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        interview(db, iid, user)
        db.execute('UPDATE interviews SET title=? WHERE id=?', (title, iid))
        return details(db, iid)

@app.delete('/api/interviews/{iid}', status_code=204)
def delete_interview(iid: int, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = interview(db, iid, user)
        paths = {row['audio_path'] for row in db.execute(
            'SELECT audio_path FROM answers WHERE interview_id=? AND audio_path IS NOT NULL', (iid,))}
        paths.update(row['audio_path'] for row in db.execute(
            'SELECT audio_path FROM interview_recordings WHERE interview_id=? AND audio_path IS NOT NULL', (iid,)))
        presentation = db.execute('SELECT directory FROM presentations WHERE interview_id=?', (iid,)).fetchone()
        db.execute('DELETE FROM answers WHERE interview_id=?', (iid,))
        db.execute('DELETE FROM interview_recordings WHERE interview_id=?', (iid,))
        db.execute('DELETE FROM presentations WHERE interview_id=?', (iid,))
        db.execute('DELETE FROM interviews WHERE id=?', (iid,))
    for path in paths:
        Path(path).unlink(missing_ok=True)
    if presentation:
        shutil.rmtree(presentation['directory'], ignore_errors=True)
    return Response(status_code=204)

@app.put('/api/interviews/{iid}/answers/{stage}')
def answer(iid: int, stage: int, payload: Answer, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        if not db.execute('UPDATE answers SET transcript=? WHERE interview_id=? AND stage=?', (payload.transcript, iid, stage)).rowcount:
            raise HTTPException(404, '题目不存在')
        return details(db, iid)

@app.post('/api/interviews/{iid}/answers/{stage}/audio')
async def audio(iid: int, stage: int, file: UploadFile = File(...), user=Depends(interview_user)):
    with connect() as db:
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        if not db.execute('SELECT 1 FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone(): raise HTTPException(404, '题目不存在')
    limit = load_config()['app']['max_audio_mb'] * 1024 * 1024
    content = await file.read(limit + 1)
    if not content or len(content) > limit: raise HTTPException(400, '录音为空或超出大小限制')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        directory = Path(load_config()['app']['upload_dir']); directory.mkdir(parents=True, exist_ok=True)
        path = directory / (secrets.token_hex(20) + '.webm')
        try:
            path.write_bytes(content)
            require_running(item)
            db.execute('UPDATE answers SET audio_path=? WHERE interview_id=? AND stage=?', (str(path), iid, stage))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return {'message': '录音已保存'}

@app.get('/api/interviews/{iid}/answers/{stage}/audio')
def get_audio(iid: int, stage: int, user=Depends(interview_user)):
    with connect() as db:
        interview(db, iid, user)
        row = db.execute('SELECT audio_path FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not row or not row['audio_path'] or not Path(row['audio_path']).is_file(): raise HTTPException(404, '录音不存在')
        return FileResponse(row['audio_path'], media_type='audio/webm')

@app.post('/api/interviews/{iid}/answers/{stage}/transcribe')
def transcribe(iid: int, stage: int, user=Depends(interview_user)):
    with connect() as db:
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        row = db.execute('SELECT audio_path FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not row or not row['audio_path']: raise HTTPException(404, '录音不存在')
        source = row['audio_path']
    text = ai.transcribe(Path(source))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        current = db.execute('SELECT audio_path FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if current['audio_path'] != source:
            raise HTTPException(409, '录音已更新，请对当前录音重新转写')
        db.execute('UPDATE answers SET transcript=? WHERE interview_id=? AND stage=?', (text, iid, stage))
        return {'transcript': text}

@app.post('/api/interviews/{iid}/teacher-question')
def question(iid: int, user=Depends(interview_user)):
    """Ask a PPT-first expert question without requiring successful ASR first."""
    with connect() as db:
        item = active_interview(db, iid, user)
        require_stage(db, item, 2)
        count = 4 if item['workflow_version'] >= 5 else len(load_config()['interview']['questions'])
        if item['workflow_version'] >= 5:
            for stage in (3, 4):
                require_stage(db, item, stage)
        existing = db.execute('SELECT question FROM answers WHERE interview_id=? AND stage=?', (iid, count + 1)).fetchone()
        if existing: return {'question': existing['question']}
        evidence = expert_context.snapshot(db, item)
        if [row['stage'] for row in evidence['answers']] != list(range(1, count + 1)):
            raise HTTPException(409, '前面的面试环节记录不完整，请刷新后重试')
    context = expert_context.build(evidence, purpose='question')
    q = ai.chat(context.prompt, system=expert_context.QUESTION_SYSTEM, media=context.media)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, 2)
        existing = db.execute('SELECT question FROM answers WHERE interview_id=? AND stage=?', (iid, count + 1)).fetchone()
        if existing: return {'question': existing['question']}
        current = expert_context.snapshot(db, item)
        if (expert_context.revision(current, question=True) != expert_context.revision(evidence, question=True)
                or expert_context.presentation_digest(current) != context.presentation_digest):
            raise HTTPException(409, 'PPT 或已选题目已更新，请重新进入专家问答')
        db.execute('INSERT INTO answers(interview_id,stage,question) VALUES (?,?,?)', (iid, count + 1, q))
        return {'question': q}


@app.post('/api/interviews/{iid}/stage-speech/{stage}')
def stage_speech(iid: int, stage: int, user=Depends(interview_user)):
    """Read a fixed stage introduction without generating questions or reviews."""
    introductions = {
        1: '当前进入自我介绍环节。',
        2: '当前进入专业课问答环节。',
        3: '当前进入英文翻译环节。',
        4: '当前进入英文问答环节。',
        5: '当前进入专家问答环节。专家给出的问题为。',
    }
    if stage not in introductions:
        raise HTTPException(404, '面试环节不存在')
    with connect() as db:
        item = interview(db, iid, user)
        if not item['started_at']:
            raise HTTPException(409, '请先开始面试')
        if item['workflow_version'] < 5:
            raise HTTPException(409, '历史面试不支持新流程环节播报')
        if stage > 1 and not item['intro_completed']:
            raise HTTPException(409, '请先完成自我介绍，再进入后续面试环节')
        if not db.execute('SELECT 1 FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone():
            raise HTTPException(409, '请先进入对应面试环节')
    content, mime = speech.cached(introductions[stage])
    with connect() as db:
        interview(db, iid, user)
    return Response(content=content, media_type=mime, headers={'Cache-Control': 'private, no-store'})


@app.post('/api/interviews/{iid}/expert-speech')
def expert_speech(iid: int, user=Depends(interview_user)):
    """Synthesize only this owner's saved expert question; feedback is independent."""
    with connect() as db:
        item = interview(db, iid, user)
        stage = 5 if item['workflow_version'] >= 5 else len(load_config()['interview']['questions']) + 1
        row = db.execute('SELECT question FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not row:
            raise HTTPException(409, '请先进入专家问答，再播放专家问题')
        text = row['question']
    content, mime = speech.cached(text, interview_id=iid)
    with connect() as db:
        interview(db, iid, user)
        current = db.execute('SELECT question FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not current or current['question'] != text:
            raise HTTPException(409, '专家问题已更新，请刷新后重新播放')
    return Response(content=content, media_type=mime, headers={'Cache-Control': 'private, no-store'})

@app.post('/api/interviews/{iid}/professional-question')
def professional_question(iid: int, payload: SubjectChoice, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, 2, selecting=True)
        if item['workflow_version'] < 5:
            raise HTTPException(409, '历史面试保留原题目')
        answer_row = db.execute('SELECT * FROM answers WHERE interview_id=? AND stage=2', (iid,)).fetchone()
        if not answer_row:
            raise HTTPException(404, '面试环节不存在')
        if answer_row['question_choices'] and answer_row['subject'] == payload.subject:
            raise HTTPException(409, '换题必须选择另一门学科')
        if answer_row['question_choices'] >= 2:
            raise HTTPException(409, '本环节只能选择或更换一次题目')
        question = question_bank.choose_question(db, 'professional', payload.subject)
        history = json.loads(answer_row['question_history'])
        history.append({'question': question['content'], 'subject': payload.subject})
        db.execute("UPDATE answers SET question=?,subject=?,question_history=?,question_choices=question_choices+1,transcript='',audio_path=NULL WHERE id=?",
                   (question['content'], payload.subject, json.dumps(history, ensure_ascii=False), answer_row['id']))
        return details(db, iid)


@app.post('/api/interviews/{iid}/draw-question/{stage}')
def draw_question(iid: int, stage: int, user=Depends(interview_user)):
    if stage not in (3, 4):
        raise HTTPException(404, '该环节不支持随机抽题')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        require_stage(db, item, stage, selecting=True)
        if item['workflow_version'] < 5:
            raise HTTPException(409, '历史面试保留原题目')
        row = db.execute('SELECT * FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not row:
            raise HTTPException(404, '面试环节不存在')
        if row['question_choices']:
            return details(db, iid)
        category = 'translation' if stage == 3 else 'oral'
        question = question_bank.choose_question(db, category)
        db.execute('UPDATE answers SET question=?,question_choices=1 WHERE id=?', (question['content'], row['id']))
        return details(db, iid)

@app.post('/api/interviews/{iid}/stop')
def stop_interview(iid: int, user=Depends(interview_user)):
    """Close a user's interview immediately without invoking AI or discarding saved answers."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = interview(db, iid, user)
        if item['status'] != 'finished':
            ended = item['deadline_at'] if timing(item)['timed_out'] else timestamp()
            db.execute("UPDATE interviews SET status='finished',ended_at=? WHERE id=?", (ended, iid))
        return details(db, iid)


@app.post('/api/interviews/{iid}/finish')
def finish(iid: int, user=Depends(interview_user)):
    """Generate a manually requested review from a stable, complete evidence snapshot."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = interview(db, iid, user)
        if item['feedback'] is not None:
            return details(db, iid)
        expert_stage = 5 if item['workflow_version'] >= 5 else len(load_config()['interview']['questions']) + 1
        if not db.execute('SELECT 1 FROM answers WHERE interview_id=? AND stage=?', (iid, expert_stage)).fetchone():
            raise HTTPException(409, '进入最后的专家问答环节后才能生成点评')
        clock = timing(item)
        expired = clock['timed_out']
        stopped = item['status'] == 'finished'
        if not expired and not stopped:
            require_running(item)
            require_stage(db, item, 2)
        ended = item['ended_at'] if stopped else item['deadline_at'] if expired else timestamp()
        # End an active interview before the slow request; a failed review stays retryable.
        if not expired and not stopped:
            db.execute("UPDATE interviews SET status='finished',ended_at=? WHERE id=?", (ended, iid))
            item = interview(db, iid, user)
        evidence = expert_context.snapshot(db, item)
        evidence['interview']['ended_at'] = ended
    context = expert_context.build(evidence, purpose='feedback')
    feedback = ai.chat(context.prompt, system=expert_context.FEEDBACK_SYSTEM, media=context.media)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = interview(db, iid, user)
        if item['feedback'] is not None:
            return details(db, iid)
        current = expert_context.snapshot(db, item)
        if (expert_context.revision(current) != expert_context.revision(evidence)
                or expert_context.presentation_digest(current) != context.presentation_digest):
            raise HTTPException(409, '面试材料或最终录音已更新，请重新生成点评')
        if item['ended_at'] is not None:
            ended = item['ended_at']
        elif timing(item)['timed_out']:
            ended = item['deadline_at']
        db.execute("UPDATE interviews SET status='finished',feedback=?,ended_at=? WHERE id=?", (feedback, ended, iid))
        return details(db, iid)

@app.get('/api/contests')
def contests(user=Depends(exam_user)):
    with connect() as db:
        return [{**dict(x), 'can_access': contest_access.can_access(db, x, user)}
                for x in db.execute('SELECT * FROM contests ORDER BY id DESC')]


@app.get('/api/contests/{cid}')
def contest_overview(cid: int, user=Depends(exam_user)):
    """Return contest metadata and problem titles without revealing future statements."""
    with connect() as db:
        contest = contest_access.require_access(db, cid, user)
        problems = [dict(row) for row in db.execute('''SELECT problems.id,title,remote_problem_id,points,
            (SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=problems.id AND users.is_admin=0) AS attempt_count,
            (SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=problems.id AND status='Accepted' AND users.is_admin=0) AS accepted_count
            FROM problems WHERE contest_id=? ORDER BY id''', (cid,))]
        if not user['is_admin'] and not contest['show_ranking']:
            for problem in problems:
                problem['attempt_count'] = None
                problem['accepted_count'] = None
        return {**dict(contest), 'problem_count': len(problems), 'problems': problems}


@app.get('/api/contests/{cid}/ranking')
def contest_ranking(cid: int, user=Depends(exam_user)):
    """Return the configured contest ranking and per-problem attempt counts."""
    with connect() as db:
        contest = contest_access.require_access(db, cid, user)
        problems = [dict(row) for row in db.execute('''SELECT problems.id,problems.title,problems.points,
            (SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=problems.id AND users.is_admin=0) AS attempt_count,
            (SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=problems.id AND status='Accepted' AND users.is_admin=0) AS accepted_count
            FROM problems WHERE contest_id=? ORDER BY id''', (cid,))]
        if not contest['show_ranking']:
            if not user['is_admin']:
                for problem in problems:
                    problem['attempt_count'] = None
                    problem['accepted_count'] = None
            return {'visible': False, 'ranking_rule': contest['ranking_rule'], 'problems': problems, 'rows': []}
        users = list(db.execute('''SELECT DISTINCT users.id,users.username FROM submissions
            JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id
            WHERE problems.contest_id=? AND users.is_admin=0''', (cid,)))
        rows = []
        for candidate in users:
            per_problem = []
            score = accepted = attempts = 0
            first_accept = None
            for problem in problems:
                submissions = list(db.execute('''SELECT status,created,detail FROM submissions
                    WHERE user_id=? AND problem_id=? ORDER BY id''', (candidate['id'], problem['id'])))
                accepted_rows = [row for row in submissions if row['status'] == 'Accepted']
                solved = bool(accepted_rows)
                scored_submissions = [(submission_score(problem['points'], row['status'], row['detail']), row)
                                      for row in submissions]
                problem_score, best_submission = max(scored_submissions, key=lambda item: item[0], default=(0, None))
                testcase_match = re.search(r'通过测试(?:用例|点)数\s*[:：]\s*(\d+)\s*/\s*(\d+)', best_submission['detail']) if best_submission else None
                attempts += len(submissions)
                accepted += int(solved)
                score += problem_score
                if solved:
                    solved_at = accepted_rows[0]['created']
                    first_accept = solved_at if first_accept is None else min(first_accept, solved_at)
                per_problem.append({'problem_id': problem['id'], 'attempts': len(submissions),
                    'accepted': len(accepted_rows), 'solved': solved, 'score': problem_score,
                    'passed_cases': int(testcase_match.group(1)) if testcase_match else 0,
                    'total_cases': int(testcase_match.group(2)) if testcase_match else 0})
            rows.append({'user_id': candidate['id'], 'username': candidate['username'], 'score': score,
                'accepted_count': accepted, 'attempt_count': attempts, 'first_accepted_at': first_accept,
                'problems': per_problem})
        if contest['ranking_rule'] == 'acm':
            rows.sort(key=lambda item: (-item['accepted_count'], item['attempt_count'], item['first_accepted_at'] or float('inf'), item['username'].casefold()))
        else:
            rows.sort(key=lambda item: (-item['score'], -item['accepted_count'], item['attempt_count'], item['first_accepted_at'] or float('inf'), item['username'].casefold()))
        for rank, row in enumerate(rows, 1): row['rank'] = rank
        return {'visible': True, 'ranking_rule': contest['ranking_rule'], 'problems': problems, 'rows': rows}

@app.get('/api/admin/luogu/problem-suggestions')
def luogu_problem_suggestions(q: str = Query(min_length=1, max_length=64), user=Depends(administrator)):
    query = q.strip()
    if not query: raise HTTPException(422, '请输入题目编号或名称')
    try:
        return luogu_catalog.search(query)
    except luogu_catalog.LuoguCatalogError as error:
        raise HTTPException(502, str(error)) from error

@app.get('/api/admin/luogu/problems/{problem_id}')
def luogu_problem_details(problem_id: str, user=Depends(administrator)):
    try:
        return luogu_catalog.problem(problem_id)
    except luogu_catalog.LuoguCatalogError as error:
        raise HTTPException(502, str(error)) from error

@app.post('/api/admin/contests')
def create_contest(payload: Contest, user=Depends(administrator)):
    if payload.ends <= payload.starts: raise HTTPException(400, '结束时间必须晚于开始时间')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        iid = db.execute('INSERT INTO contests(title,starts,ends,judge_mode,show_ranking,ranking_rule) VALUES (?,?,?,?,?,?)',
            (payload.title, payload.starts, payload.ends,payload.judge_mode,int(payload.show_ranking),payload.ranking_rule)).lastrowid
        contest_access.set_participants(db, iid, payload.participant_ids)
        problem_ids = []
        seen = set()
        for problem in payload.problems:
            if payload.judge_mode == 'luogu':
                if not re.fullmatch(r'[A-Z]{1,4}[0-9]{1,8}', problem.remote_problem_id):
                    raise HTTPException(400, '洛谷题目编号格式无效，例如 P1000')
                if problem.remote_problem_id in seen:
                    raise HTTPException(400, '比赛中不能重复添加同一道洛谷题目')
                seen.add(problem.remote_problem_id)
            elif not problem.tests or any(set(case) != {'input', 'output'} for case in problem.tests):
                raise HTTPException(400, '本地评测需要至少一组 input/output 测试用例')
            pid = db.execute('''INSERT INTO problems(contest_id,title,statement,sample_input,sample_output,tests,remote_problem_id,samples,points)
                VALUES (?,?,?,?,?,?,?,?,?)''', (iid, *problem_values(problem), problem.points)).lastrowid
            problem_ids.append(pid)
        return {'id': iid, 'problem_ids': problem_ids}


def problem_values(problem):
    """Keep the legacy first sample and the complete public sample list in sync."""
    samples = [sample.model_dump() for sample in problem.samples]
    first = samples[0] if samples else {'input': problem.sample_input, 'output': problem.sample_output}
    return (problem.title, problem.statement, first['input'], first['output'],
            json.dumps(problem.tests, ensure_ascii=False), problem.remote_problem_id,
            json.dumps(samples, ensure_ascii=False))


@app.put('/api/admin/contests/{cid}')
def update_contest(cid: int, payload: ContestUpdate, user=Depends(administrator)):
    """Update a contest atomically, preserving problem IDs and submitted evidence."""
    if payload.ends <= payload.starts: raise HTTPException(400, '结束时间必须晚于开始时间')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        contest = db.execute('SELECT * FROM contests WHERE id=?', (cid,)).fetchone()
        if not contest: raise HTTPException(404, '比赛不存在')
        if payload.judge_mode != contest['judge_mode']:
            raise HTTPException(400, '已有比赛不能切换评测平台')
        if payload.participant_ids is not None:
            contest_access.set_participants(db, cid, payload.participant_ids)
        existing = list(db.execute('SELECT * FROM problems WHERE contest_id=?', (cid,)))
        ids = [row['id'] for row in existing]
        if payload.problems is not None:
            if contest['judge_mode'] != 'luogu':
                raise HTTPException(400, '历史本地评测比赛只支持修改名称和起止时间')
            by_remote = {row['remote_problem_id']: row for row in existing}
            by_id = {row['id']: row for row in existing}
            seen = set()
            keep = []
            for problem in payload.problems:
                if not re.fullmatch(r'[A-Z]{1,4}[0-9]{1,8}', problem.remote_problem_id):
                    raise HTTPException(400, '洛谷题目编号格式无效，例如 P1000')
                if problem.remote_problem_id in seen:
                    raise HTTPException(400, '比赛中不能重复添加同一道洛谷题目')
                seen.add(problem.remote_problem_id)
                old = by_id.get(problem.id) if problem.id is not None else by_remote.get(problem.remote_problem_id)
                if problem.id is not None and (not old or old['remote_problem_id'] != problem.remote_problem_id):
                    raise HTTPException(400, '题目不属于本比赛或题号发生变化，请重新打开编辑页')
                if old:
                    db.execute('''UPDATE problems SET title=?,statement=?,sample_input=?,sample_output=?,tests=?,remote_problem_id=?,samples=?,points=?
                        WHERE id=?''', (*problem_values(problem), problem.points, old['id']))
                    keep.append(old['id'])
                else:
                    pid = db.execute('''INSERT INTO problems(contest_id,title,statement,sample_input,sample_output,tests,remote_problem_id,samples,points)
                        VALUES (?,?,?,?,?,?,?,?,?)''', (cid, *problem_values(problem), problem.points)).lastrowid
                    keep.append(pid)
            for old in existing:
                if old['id'] in keep: continue
                if db.execute('SELECT 1 FROM submissions WHERE problem_id=? LIMIT 1', (old['id'],)).fetchone():
                    raise HTTPException(409, '不能移除已有提交记录的题目；可修改比赛信息或新增题目')
                db.execute('DELETE FROM problems WHERE id=?', (old['id'],))
            ids = keep
        db.execute('UPDATE contests SET title=?,starts=?,ends=?,show_ranking=?,ranking_rule=? WHERE id=?',
            (payload.title, payload.starts, payload.ends, int(payload.show_ranking), payload.ranking_rule, cid))
        return {'id': cid, 'problem_ids': ids}


@app.post('/api/admin/problems/{pid}/refresh')
def refresh_problem(pid: int, user=Depends(administrator)):
    """Reimport public statement and samples, retaining submissions and local IDs."""
    with connect() as db:
        old = db.execute('SELECT * FROM problems WHERE id=?', (pid,)).fetchone()
        if not old: raise HTTPException(404, '题目不存在')
        remote_id = old['remote_problem_id']
        if not remote_id: raise HTTPException(400, '此题不是洛谷导入题目')
    try:
        imported = luogu_catalog.problem(remote_id)
    except luogu_catalog.LuoguCatalogError as error:
        raise HTTPException(502, str(error)) from error
    problem = Problem(**{**imported, 'remote_problem_id': remote_id})
    with connect() as db:
        cursor = db.execute('''UPDATE problems SET title=?,statement=?,sample_input=?,sample_output=?,tests=?,remote_problem_id=?,samples=?
            WHERE id=? AND remote_problem_id=?''', (*problem_values(problem), pid, remote_id))
        if not cursor.rowcount: raise HTTPException(409, '题目已发生变化，请刷新比赛信息')
        return public_problem(db.execute('SELECT * FROM problems WHERE id=?', (pid,)).fetchone())

@app.delete('/api/admin/contests/{cid}', status_code=204)
def delete_contest(cid: int, user=Depends(administrator)):
    with connect() as db:
        problem_ids = [row['id'] for row in db.execute('SELECT id FROM problems WHERE contest_id=?', (cid,))]
        if not db.execute('SELECT 1 FROM contests WHERE id=?', (cid,)).fetchone():
            raise HTTPException(404, '比赛不存在')
        if problem_ids:
            placeholders = ','.join('?' for _ in problem_ids)
            db.execute(f'DELETE FROM submissions WHERE problem_id IN ({placeholders})', problem_ids)
            db.execute(f'DELETE FROM problems WHERE id IN ({placeholders})', problem_ids)
        db.execute('DELETE FROM contests WHERE id=?', (cid,))
    return Response(status_code=204)

@app.post('/api/admin/contests/{cid}/problems')
def create_problem(cid: int, payload: Problem, user=Depends(administrator)):
    with connect() as db:
        contest = db.execute('SELECT judge_mode FROM contests WHERE id=?', (cid,)).fetchone()
        if not contest: raise HTTPException(404, '比赛不存在')
        if contest['judge_mode'] == 'luogu':
            if not re.fullmatch(r'[A-Z]{1,4}[0-9]{1,8}', payload.remote_problem_id): raise HTTPException(400, '洛谷题目编号格式无效，例如 P1000')
        elif not payload.tests or any(set(case) != {'input', 'output'} for case in payload.tests):
            raise HTTPException(400, '本地评测需要至少一组 input/output 测试用例')
        pid = db.execute('INSERT INTO problems(contest_id,title,statement,sample_input,sample_output,tests,remote_problem_id,samples,points) VALUES (?,?,?,?,?,?,?,?,?)', (cid, *problem_values(payload), payload.points)).lastrowid
        return {'id': pid}

@app.get('/api/contests/{cid}/problems')
def problems(cid: int, user=Depends(exam_user)):
    with connect() as db:
        contest = contest_access.require_access(db, cid, user)
        if time.time() < contest['starts']: raise HTTPException(403, '比赛尚未开始')
        return [{**public_problem(row), 'judge_mode': contest['judge_mode'],
            'points': row['points'],
            'attempt_count': db.execute('''SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=? AND users.is_admin=0''', (row['id'],)).fetchone()[0] if user['is_admin'] or contest['show_ranking'] else None,
            'accepted_count': db.execute("""SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=? AND status='Accepted' AND users.is_admin=0""", (row['id'],)).fetchone()[0] if user['is_admin'] or contest['show_ranking'] else None}
            for row in db.execute('SELECT * FROM problems WHERE contest_id=? ORDER BY id', (cid,))]

@app.post('/api/problems/{pid}/submissions')
def submit(pid: int, payload: Submission, user=Depends(exam_user)):
    with connect() as db:
        p = db.execute('SELECT problems.*,contests.starts,contests.ends,contests.judge_mode FROM problems JOIN contests ON contests.id=problems.contest_id WHERE problems.id=?', (pid,)).fetchone()
        if not p: raise HTTPException(404, '题目不存在')
        contest_access.require_access(db, p['contest_id'], user)
        if not p['starts'] <= time.time() <= p['ends']: raise HTTPException(403, '不在比赛时间内')
        if p['judge_mode'] == 'docker' and payload.language != 'python3':
            raise HTTPException(422, '历史本地评测比赛目前仅支持 Python 3')
        initial = 'Waiting for browser extension' if p['judge_mode'] == 'luogu' else 'Judging'
        sid = db.execute('INSERT INTO submissions(user_id,problem_id,language,source,status,created) VALUES (?,?,?,?,?,?)', (user['id'],pid,payload.language,payload.source,initial,time.time())).lastrowid
    if p['judge_mode'] == 'luogu': return {'id': sid, 'status': initial, 'judge_mode': 'luogu', 'remote_problem_id': p['remote_problem_id']}
    status = judge.judge(payload.language, payload.source, p['tests'])
    with connect() as db: db.execute('UPDATE submissions SET status=? WHERE id=?', (status, sid))
    return {'id': sid, 'status': status}

@app.post('/api/submissions/{sid}/remote-result')
def update_remote_submission(sid: int, payload: RemoteSubmissionResult, user=Depends(exam_user)):
    with connect() as db:
        row = db.execute('''SELECT submissions.status,submissions.remote_submission_id,problems.contest_id
            FROM submissions JOIN problems ON problems.id=submissions.problem_id
            JOIN contests ON contests.id=problems.contest_id
            WHERE submissions.id=? AND submissions.user_id=? AND contests.judge_mode='luogu' ''',
            (sid,user['id'])).fetchone()
        if not row: raise HTTPException(404, '提交记录不存在')
        contest_access.require_access(db, row['contest_id'], user)
        if row['remote_submission_id'] and row['remote_submission_id'] != payload.remote_submission_id:
            raise HTTPException(409, '远端提交编号与本地记录不一致')
        terminal = {'Accepted','Wrong Answer','Output Limit Exceeded','Time Limit Exceeded','Memory Limit Exceeded','Runtime Error','Compile Error','System Error','Submission Failed'}
        if row['status'] in terminal and row['status'] != payload.status:
            raise HTTPException(409, '已完成的评测结果不能被覆盖')
        if payload.status != 'Submission Failed' and not (row['remote_submission_id'] or payload.remote_submission_id):
            raise HTTPException(422, '远端评测状态必须包含洛谷提交编号')
        db.execute('UPDATE submissions SET remote_submission_id=?,status=?,detail=? WHERE id=?',
                   (payload.remote_submission_id,payload.status,payload.detail,sid))
        return {'id':sid,'remote_submission_id':payload.remote_submission_id,'status':payload.status}

@app.get('/api/submissions')
def submissions(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                contest_id: int | None = Query(default=None, ge=1), user=Depends(exam_user)):
    with connect() as db:
        where = 'submissions.user_id=?'
        params: list[object] = [user['id']]
        if not user['is_admin']:
            where += " AND (problems.contest_id IN (SELECT id FROM contests WHERE access_mode='all') OR problems.contest_id IN (SELECT contest_id FROM contest_participants WHERE user_id=?))"
            params.append(user['id'])
        if contest_id is not None:
            contest_access.require_access(db, contest_id, user)
            where += ' AND problems.contest_id=?'
            params.append(contest_id)
        joins = 'JOIN problems ON problems.id=submissions.problem_id'
        total = db.execute(f'SELECT COUNT(*) FROM submissions {joins} WHERE {where}', params).fetchone()[0]
        rows = [dict(row) for row in db.execute(f'''SELECT submissions.id,username,problem_id,problems.title AS problem_title,
            language,status,created,detail FROM submissions JOIN users ON users.id=submissions.user_id
            {joins} WHERE {where} ORDER BY submissions.id DESC LIMIT ? OFFSET ?''', (*params,page_size,(page-1)*page_size))]
        pages = (total + page_size - 1) // page_size
        stats = db.execute(f'''SELECT SUM(CASE WHEN status='Accepted' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN status IN ('Waiting for browser extension','Submitted','Judging') THEN 1 ELSE 0 END) AS judging
            FROM submissions {joins} WHERE {where}''', params).fetchone()
        return {'items': rows, 'total': total, 'page': page, 'page_size': page_size, 'pages': pages,
            'stats': {'accepted': stats['accepted'] or 0, 'judging': stats['judging'] or 0}}


@app.get('/api/submissions/{sid}')
def submission_detail(sid: int, user=Depends(exam_user)):
    """Return source and judge details only to the submission owner."""
    with connect() as db:
        row = db.execute('''SELECT submissions.id,submissions.user_id,submissions.problem_id,problems.contest_id,problems.title AS problem_title,
            contests.title AS contest_title,submissions.language,submissions.source,submissions.status,submissions.created,
            submissions.detail FROM submissions
            JOIN problems ON problems.id=submissions.problem_id JOIN contests ON contests.id=problems.contest_id
            WHERE submissions.id=? AND submissions.user_id=?''', (sid,user['id'])).fetchone()
        if not row: raise HTTPException(404, '提交记录不存在')
        contest_access.require_access(db, row['contest_id'], user)
        return dict(row)
