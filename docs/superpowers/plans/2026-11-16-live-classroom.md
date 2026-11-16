# Live Classroom Implementation Plan

**Goal:** 在知序实现 50 人以内互动课堂，覆盖管理、音视频、资料、评论、点赞、举手、录播与回放。

**Architecture:** FastAPI + SQLite 保存课程与权限、互动、资料及录播状态。LiveKit API 生成短期入会凭证并控制发布权限，Egress 负责录播；浏览器使用本地固定版本 SDK。新增 routes/services/static 模块，仅在主文件接入路由与导航。

**Tech Stack:** Python/FastAPI/SQLite、LiveKit Server SDK / browser SDK、原生 ES modules / CSS。

## Global Constraints

- 复用已有登录鉴权，不新增全局教师角色。
- 权限由服务端校验；资料、回放、互动不可被其他课程用户读取。
- 资料私有存储，所有可配置参数统一 [live]。
- 未配置媒体服务时不得呈现虚假的连接/录制成功。
- 主舞台优先、工具栏固定、站内弹层、移动端抽屉、离开释放所有设备。
- 已存在的分页留白修改必须保留。

## Tasks

- [x] Backend: 新建直播 schema、配置、课程/课次 API、名单与主持人、资料、互动、媒体 token/权限控制、录制。先编写 tests/test_live.py 观察未实现失败，再实现；运行 `.venv/bin/pytest tests/test_live.py -q`。接口约定记录在 `.superpowers/live/api.md`，媒体依赖可通过官方 SDK 验证。
- [x] UI: 新建 live.js、live-room.js、live.css，接入 app.js/index.html；实现课程列表、编辑弹层、课次详情、资料、入会准备、沉浸式课堂、固定工具栏、互动面板、录播播放器。纯状态逻辑放 live-model.mjs 并先编写 node 行为测试。
- [x] Integration: 本地托管 SDK，编写部署配置样例与使用文档；实际 API 与 UI 对齐，检查同课程权限、重连、切换视图、退出与录制状态。
- [x] Verification: 运行直播后端与前端测试、已有相关测试及 diff 检查；使用浏览器检查桌面与移动布局、创建课程/课次、资料上传、未配置提示；关闭临时验证进程。

## Verification outcome

Backend live/system checks: 35 passed; focused live config/moderation/recording checks: 19 passed after final backend edits. Frontend helpers, device ownership and delayed classroom recovery: 15 passed. Existing route/history/mobile checks: 19 passed. Browser smoke used isolated data for creating/editing a course, arranging a lesson, uploading a private file and unconfigured-service messaging. Layout preview used controlled participant fixtures at 390/768/1440 widths; local SDK loading and tab keyboard interaction passed. These previews do not establish real SFU connectivity, Egress output or 50-participant capacity. No LiveKit or Egress instance was available; complete the deployment acceptance in docs/live-classroom.md before live use.
