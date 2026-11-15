"""Versioned home sections stored as one validated document and saved atomically."""
import json
import time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

KEY = 'preparation_home_layout'
Identifier = Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
Title = Annotated[str, Field(min_length=1, max_length=100)]


class Content(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: Identifier
    title: Title
    enabled: StrictBool = True

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError('标题不能为空')
        return value.strip()


class Step(Content):
    summary: str = Field(default='', max_length=1000)


class Resource(Step):
    stars: StrictInt = Field(default=3, ge=0, le=5)
    notice: str = Field(default='', max_length=1000)
    kind: Literal['view', 'external'] = 'view'
    view: Literal['home', 'training', 'coding', 'interview', 'contest', 'profile'] = 'training'
    section: Literal['', 'interview', 'written_ai', 'written_c'] = ''
    url: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_link(self):
        if self.kind == 'external':
            parsed = urlsplit(self.url)
            try:
                parsed.port
            except ValueError as error:
                raise ValueError('外部链接的端口无效') from error
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in self.url):
                raise ValueError('外部资料请填写有效的 HTTP 或 HTTPS 链接')
        elif self.section and self.view != 'training':
            raise ValueError('训练篇目仅适用于每日训练入口')
        return self


class Roadmap(Content):
    type: Literal['roadmap'] = 'roadmap'
    eyebrow: str = Field(default='', max_length=100)
    summary: str = Field(default='', max_length=1000)
    items: list[Step] = Field(default_factory=list, max_length=30)


class Resources(Content):
    type: Literal['resources'] = 'resources'
    eyebrow: str = Field(default='', max_length=100)
    summary: str = Field(default='', max_length=1000)
    items: list[Resource] = Field(default_factory=list, max_length=100)


Block = Annotated[Roadmap | Resources, Field(discriminator='type')]


class Layout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: StrictInt = Field(ge=1)
    blocks: list[Block] = Field(max_length=30)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError('区块标识不能重复')
        for block in self.blocks:
            ids = [item.id for item in block.items]
            if len(ids) != len(set(ids)):
                raise ValueError('同一区块中的内容标识不能重复')
        return self


def initialize(db):
    if db.execute('SELECT 1 FROM app_settings WHERE key=?', (KEY,)).fetchone():
        return
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'assets/home-resources-v1.json').read_text(encoding='utf-8'))
    roadmap = Roadmap(id='preparation-roadmap', title='先夯实基础，再练习表达', eyebrow='复试准备路线', items=[
        Step(id='fundamentals', title='基础与 AI', summary='数学基础 · 机器学习 · 深度学习 · LLM'),
        Step(id='written', title='笔试与机试', summary='软件工程 · AI 笔试 · 文献翻译 · 算法题'),
        Step(id='interview', title='面试准备', summary='专业课 · 英文 · PPT 自我介绍 · 专家问答')])
    blocks = [roadmap]
    for index, group in enumerate(dict.fromkeys(item['group'] for item in catalog)):
        blocks.append(Resources(id=f'resources-{index}', title=group, items=[
            Resource(**{key: value for key, value in item.items() if key != 'group'})
            for item in catalog if item['group'] == group]))
    document = Layout(revision=1, blocks=blocks).model_dump()
    db.execute('INSERT INTO app_settings(key,value) VALUES (?,?)', (KEY, json.dumps(document, ensure_ascii=False)))


def read(db, *, public=False):
    document = json.loads(db.execute('SELECT value FROM app_settings WHERE key=?', (KEY,)).fetchone()['value'])
    if public:
        document['blocks'] = [block for block in document['blocks'] if block['enabled']]
        for block in document['blocks']:
            block['items'] = [item for item in block['items'] if item['enabled']]
    return document


def save(db, payload, actor):
    current = read(db)
    if current['revision'] != payload.revision:
        raise HTTPException(409, '首页配置已被其他管理员修改，请重新加载后编辑')
    document = {**payload.model_dump(), 'revision': payload.revision + 1}
    db.execute('UPDATE app_settings SET value=? WHERE key=?', (json.dumps(document, ensure_ascii=False), KEY))
    db.execute("""INSERT INTO app_settings(key,value) VALUES ('preparation_home_last_edit',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (json.dumps({'user_id': actor['id'], 'time': time.time()}),))
    return document
