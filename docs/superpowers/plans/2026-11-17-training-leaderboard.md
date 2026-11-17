# 每日训练与算法带刷排行榜 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每日训练和算法带刷增加累计排行榜，只展示普通用户用户名，并提供打卡天数、抽题训练数量和上机通过题目数量排名。

**Architecture:** 新增独立的 `leaderboard` 服务层执行参数化聚合查询，训练路由提供统一排行榜 API；前端抽取一个共享排行榜渲染模块，分别挂载到每日训练和算法带刷导航中。管理员通过 `users.is_admin=0` 在查询层排除，Accepted 题目按 `DISTINCT question_id` 计数。

**Tech Stack:** FastAPI、SQLite、原生 ES modules、现有 `ui.js` 工具、pytest、Node test runner。

## Global Constraints

- 只展示 `users.is_admin=0` 的普通用户，并返回 `username`，不返回管理员额度、密码或内部账号字段。
- 统计范围固定为累计总榜；并列时按用户名升序、用户 id 升序稳定排序。
- 上机通过数量使用 `COUNT(DISTINCT question_id)`，同一题多次 Accepted 只计一次。
- 保留现有未提交用户修改，不重置 `app/static/index.html` 或 `docs/deployment.md`。
- 所有新增接口使用参数化 SQL、现有认证依赖和局部错误提示，不使用浏览器原生弹窗。

---

### Task 1: 添加排行榜查询服务和 API

**Files:**
- Create: `app/services/leaderboard.py`
- Modify: `app/routes/training.py`
- Test: `tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `users`, `training_checkins`, `coding_checkins`, `training_daily_questions`, `coding_submissions`。
- Produces: `leaderboard.snapshot(db, user)` 和 `GET /api/leaderboard`。

- [ ] **Step 1: Write failing service tests**

在 `tests/test_leaderboard.py` 建立普通用户 `alice`、`bob`、管理员 `manager`，直接插入可控的打卡、抽题和 Accepted 提交记录；断言 `/api/leaderboard` 返回三张榜、用户名、管理员不在结果中、同一题重复 Accepted 只计一次、并列按用户名稳定排序。

```python
def test_leaderboard_excludes_admin_and_deduplicates_accepted(client):
    alice, bob, manager = login(client, 'alice'), login(client, 'bob'), login(client, 'manager')
    with connect() as db:
        ids = {name: db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()[0]
               for name in ('alice', 'bob', 'manager')}
        for day in ('2026-11-15', '2026-11-16'):
            db.execute('INSERT INTO training_checkins(user_id,date,streak,streak_start) VALUES (?,?,?,?,?)'.replace('?,?,?,?,?', '?,?,?,?'),
                       (ids['alice'], day, 1, day))
        db.execute('INSERT INTO coding_checkins(user_id,date,streak,credits) VALUES (?,?,?,?)',
                   (ids['bob'], '2026-11-16', 1, 0))
        db.execute('INSERT INTO training_daily_questions(user_id,date,question_id) VALUES (?,?,?)',
                   (ids['alice'], '2026-11-16', 1))
        db.execute('INSERT INTO coding_submissions(user_id,question_id,question_content_version,status,created,completed_date) VALUES (?,?,?,?,?,?)',
                   (ids['alice'], 1, 1, 'Accepted', 1, '2026-11-16'))
        db.execute('INSERT INTO coding_submissions(user_id,question_id,question_content_version,status,created,completed_date) VALUES (?,?,?,?,?,?)',
                   (ids['alice'], 1, 1, 'Accepted', 2, '2026-11-16'))
    result = client.get('/api/leaderboard', headers=alice)
    assert result.status_code == 200
    payload = result.json()
    assert all(item['username'] != 'manager' for board in payload['boards'].values() for item in board)
    assert next(item for item in payload['boards']['coding_solved'] if item['username'] == 'alice')['value'] == 1
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest -q tests/test_leaderboard.py`

Expected: FAIL because `/api/leaderboard` and `leaderboard.snapshot` do not exist.

- [ ] **Step 3: Implement the read-only service**

在 `app/services/leaderboard.py` 定义：

```python
def _rows(db, sql: str, limit: int = 100) -> list[dict]: ...
def _ranked(rows: list[dict]) -> list[dict]: ...
def snapshot(db, user: sqlite3.Row | dict) -> dict: ...
```

`_rows` 的 SQL 必须连接 `users u` 并包含 `WHERE u.is_admin=0`；返回 `rank`、`username`、`value`。`snapshot` 返回 `boards`（`training_checkins`、`coding_checkins`、`training_questions`、`coding_solved`）以及 `me`。`me` 只为普通用户计算排名，管理员返回 `None`。查询结果限制 100 条。

- [ ] **Step 4: 挂载认证路由**

在 `app/routes/training.py` 引入服务并添加：

```python
@router.get('/api/leaderboard')
def leaderboard(user=Depends(current_user)):
    with connect() as db:
        return leaderboard_service.snapshot(db, user)
```

不要使用 `training_user` 或 `coding_user`，登录用户可查看榜单，但训练/算法权限仍由具体操作入口控制。

- [ ] **Step 5: Run focused backend tests**

Run: `pytest -q tests/test_leaderboard.py tests/test_training.py::test_seed_and_random_round_no_duplicates_and_private_isolation tests/test_coding.py::test_home_requires_auth_and_does_not_assign_daily_question`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add app/services/leaderboard.py app/routes/training.py tests/test_leaderboard.py
git commit -m "feat: add user leaderboard API"
```

### Task 2: 创建共享排行榜前端模块

**Files:**
- Create: `app/static/leaderboard.js`
- Create: `app/static/leaderboard.css`
- Modify: `app/static/index.html`
- Test: `tests/leaderboard_ui.test.mjs`

**Interfaces:**
- Consumes: `api('/leaderboard')`、`el`、`button`、`emptyState`、`state`。
- Produces: `renderLeaderboard(root, options)`，供两个业务模块挂载。

- [ ] **Step 1: Write failing UI tests**

断言模块导出 `renderLeaderboard`，请求 `/api/leaderboard`，渲染三项切换、普通用户用户名、当前用户高亮、空状态和重试按钮；测试数据中包含管理员时页面不渲染管理员名。

- [ ] **Step 2: Run UI test and verify it fails**

Run: `node --test tests/leaderboard_ui.test.mjs`

Expected: FAIL because the shared module is missing.

- [ ] **Step 3: Implement `leaderboard.js`**

实现 `renderLeaderboard(root, { compact = false })`：

- 只消费后端已经过滤好的榜单数据，并在渲染前再次防御性过滤 `is_admin`（若字段存在且为真则跳过）。
- 顶部使用三个按钮切换“打卡天数 / 抽题训练 / 上机通过”。
- 前三名渲染为 podium 卡片，其余渲染为列表；每行显示排名、用户名、数值。
- 当前用户使用 `is_current_user` 添加 `is-current` 类。
- API 失败渲染 `emptyState('排行榜暂时不可用', error.message)` 和“重试”按钮。
- 不显示用户 id、密码、额度或管理员身份字段。

- [ ] **Step 4: Add visual styles**

在 `leaderboard.css` 定义与现有卡片、按钮、颜色变量一致的样式：桌面端三列 podium，列表单列；小屏横向滚动切换和纵向榜单；行间距、数字对齐、当前用户强调色清晰但不喧宾夺主。

- [ ] **Step 5: Include stylesheet once**

在 `app/static/index.html` 的现有样式引用区域加入 `/static/leaderboard.css`，保持版本查询参数按当前静态资源约定更新。

- [ ] **Step 6: Run UI tests**

Run: `node --test tests/leaderboard_ui.test.mjs`

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add app/static/leaderboard.js app/static/leaderboard.css app/static/index.html tests/leaderboard_ui.test.mjs
git commit -m "feat: add shared leaderboard UI"
```

### Task 3: 在每日训练与算法带刷增加入口

**Files:**
- Modify: `app/static/training.js`
- Modify: `app/static/coding.js`
- Modify: `app/static/training.css`
- Modify: `app/static/coding.css`
- Test: `tests/leaderboard_ui.test.mjs`

**Interfaces:**
- Consumes: `renderLeaderboard`。
- Produces: 每日训练和算法带刷中的“排行榜”导航入口及独立榜单页面。

- [ ] **Step 1: Extend UI tests with navigation behavior**

模拟点击两个模块的“排行榜”按钮，断言当前模块练习列表被替换为榜单容器；切回原标签后原有练习内容恢复，且不会重复挂载多个榜单实例。

- [ ] **Step 2: Add training entry**

在 `training.js` 导航标签中添加 `leaderboard` 状态；进入时渲染 `renderLeaderboard(root)`，离开时恢复原有 `renderHome`/`renderQuestions` 流程，不改变已有 session 恢复逻辑。

- [ ] **Step 3: Add coding entry**

在 `coding.js` 的 `coding-mode-tabs` 添加“排行榜”按钮；进入时隐藏题单筛选和阶段列表，挂载共享榜单；从榜单切回阶段题单、投稿、已完成等标签时重新调用现有加载流程。

- [ ] **Step 4: Tune local spacing**

为两个模块补充榜单页面上下边距、导航按钮间距和移动端横向滚动规则，确保榜单不挤压练习入口，符合现有页面的圆角、线条和字体层级。

- [ ] **Step 5: Run focused frontend tests**

Run: `node --test tests/leaderboard_ui.test.mjs tests/coding_ui.test.mjs tests/mobile_navigation.test.mjs`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add app/static/training.js app/static/coding.js app/static/training.css app/static/coding.css tests/leaderboard_ui.test.mjs
git commit -m "feat: expose leaderboard in practice modules"
```

### Task 4: 全量相关验证与文档更新

**Files:**
- Modify: `README.md` or `docs/deployment.md` only if the project’s feature index requires the new endpoint.

- [ ] **Step 1: Run backend and frontend focused suites**

Run: `pytest -q tests/test_leaderboard.py tests/test_training.py tests/test_coding.py` and `node --test tests/leaderboard_ui.test.mjs tests/coding_ui.test.mjs`.

Expected: PASS。

- [ ] **Step 2: Check formatting and accidental changes**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors; only the planned files and prior user modifications are present.

- [ ] **Step 3: Update feature documentation if needed**

Add a short API and UI entry to the existing practice documentation, stating that榜单只展示普通用户用户名，统计为累计总榜，Accepted 按题目去重；不要写入管理员内部额度。

- [ ] **Step 4: Commit documentation and verification**

```bash
git add README.md docs
git commit -m "docs: document practice leaderboards"
```
