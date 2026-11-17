# 算法带刷实施与验收

## 用户目标与约定

独立于限时比赛的带刷系统：由易到难的阶段题单、可调整的阶段/题目顺序和重要性星级、每日随机一题、连续打卡奖励、用户私人投稿及审核奖励。采用现有 FastAPI + SQLite、原生模块前端、洛谷提交桥接、同风格分栏编程界面。用户要求自主实施，因此直接实现并验证，不设置额外审批步骤。

每日题以北京时间日期固定；从公开启用题和本人私人启用题抽取，通过评测后方可打卡。当日重复打卡不重复奖励；连续第 N 天（N 为 7 的倍数）奖励 N/7 积分。投稿“每 5 道通过获得一个题目”按上下文解释为每 5 道首次审核公开奖励 1 积分；管理员免奖励，积分账本原子入账。私人题对他人不可见。

洛谷优先，已有 PDF 原链接保留；找不到准确对应题时保留其他平台链接或本地模板练习，不把近似题冒充原题。非洛谷题明确为公开样例评测，不声称具备完整隐藏测试集。PDF 原代码作为参考单独展示，明确片段/可运行完整程序的区别。所有引入题目保留来源文件和页码。

## 实施分工

1. 后端：`app/services/coding_schema.py`、`coding_catalog.py`、`coding_practice.py`、`app/routes/coding.py`、`tests/test_coding.py`。负责人后端子任务，不修改 main/db/config，主任务集成。事务、权限、幂等、版本冲突、阶段编排和删除保护均须覆盖。
2. 内容：`app/assets/coding/catalog.json`、`scripts/import_coding_sources.py`、`docs/coding-catalog.md`。整理两份 PDF 的全部题单条目和模板主题，提取代码，标注来源，验证链接和默认样例。
3. 前端：`app/static/coding.js`、`coding-admin.js`、`coding.css`。负责人前端子任务；主任务集成导航/app/index。首页→阶段→题目工作区；每日题/签到；个人题库/新增编辑/送审；后台阶段/题目/审核/奖励配置。
4. 主任务：集成 schema/router/config，扩展安全容器样例评测（C/C++/Python）、复用桥接且隔离比赛/带刷提交回调，接通导航、账户删除、账本展示，运行集成验证和浏览器检查。

种子文件结构为 `{stages:[{id,title,description,position}],questions:[{source_key,stage_id,...}]}`；阶段 id 为稳定字符串，题目 source_key 用于幂等导入。

## 前后端接口

所有接口需要现有 Bearer 登录。前台 `/api/coding`，后台 `/api/admin/coding`。

- GET `/coding/home` → `{stages:[{id,title,description,position,active,total,solved}],progress:{total,solved},daily:{date,question_id,question_title,solved,checked_in,streak,reward},contribution:{approved_count,questions_per_reward,credits_per_reward,credits_earned},judge:{available,languages,notice}}`。每日题未选择时 question_id=null，不因 GET 计入签到。
- GET `/coding/questions?stage_id=&q=&mine=false&page=1&page_size=20` → `{items:[question],total,page,page_size,pages}`。
- GET `/coding/questions/{id}` → question，含安全渲染 `statement_html`、samples、reference_code、reference_language、source_info，私有题受 owner 检查。
- POST `/coding/daily` → 与 home.daily 相同，随机固定当天题目，重复调用复用；POST `/coding/checkin` → `{already_checked,credits,streak,home}`。
- POST `/coding/questions`；PATCH `/coding/questions/{id}`（必须带 version）；DELETE `/coding/questions/{id}`；POST `/coding/questions/{id}/submit` `{version}` 送审。
- question 输入：`stage_id,title,topic,difficulty`(1..5),`stars`(1..5),`position`(>=0),`statement,samples:[{input,output}],reference_code,reference_language`(cpp11/c/python3),`source_url,remote_problem_id,judge_mode`(luogu/samples)。输出增加 id/version/owner_user_id/visibility(private/public)/review_status(draft/pending/approved/rejected)/review_reason/active/solved/source_info。
- POST `/coding/questions/{id}/submissions` `{language,source}` → `{id,question_id,status,detail,judge_mode,remote_problem_id?,passed_cases?,total_cases?}`，本地评测交给 `app.services.coding_judge.evaluate(language,source,samples)`。无评测器时返回明确 503，不执行宿主机用户代码。
- POST `/coding/submissions/{id}/remote-result` `{remote_submission_id,status,detail}`；GET `/coding/questions/{id}/submissions` → `{items:[submission]}`；GET `/coding/submissions/{id}` → submission（含 source，仅本人/有权限管理员）。终态不能改变，状态和题目匹配必须检查。
- 后台 GET `/admin/coding/stages` → `{items:[stage]}`；POST `/stages`；PATCH `/stages/{id}`；DELETE `/stages/{id}`（非空拒绝）；字段 title,description,position,active。
- 后台 GET `/admin/coding/questions?stage_id=&q=&status=&page=1&page_size=20`；POST `/questions` 直接公开；PATCH `/questions/{id}`；DELETE `/questions/{id}`；POST `/questions/{id}/review` `{version,approve,reason}`。
- GET/PUT `/admin/coding/settings` `{questions_per_reward:5,credits_per_reward:1}`，新规则仅影响后续首次通过稿件，重复审核不重复计数/奖励。
- POST `/admin/coding/import-luogu` `{problem_id}` → 题干、samples、remote_problem_id、source_url、judge_mode（前台填充编辑器后再保存）。

## 集成函数

- `coding_schema.initialize_coding(db)`：幂等建表/seed，只插入缺失的稳定 key，不覆盖管理员修改。
- `coding_judge.evaluate(language,source,samples)` → `{status,detail,passed_cases,total_cases}`；`coding_judge.availability()` → `{available,languages,notice}`。
- `coding.js` 导出 `refreshCoding,clearCoding`；`coding-admin.js` 导出 `refreshCodingAdmin,clearCodingAdmin`。根容器分别 `codingContent` 和 `codingAdminContent`，顶层 section IDs `coding` 与 `codingAdmin`。
- 复用 `requestLuoguSubmit`（contest.js 导出）并带 `context:'coding'`；插件所有 status 事件透传 context，比赛监听忽略 coding，带刷监听只接收 coding。
- 路由 `#view=coding` / `#view=coding/question/{id}`；浏览器前进/后退与刷新应保留题目。

## 验收清单

- [x] 全部来源条目整理、分类、页码和引用，能追溯；远端导入失败能重试且不会伪造数据。
- [x] 前后台阶段/排序/星级配置有效，停用题不再抽中，私人题仅本人能看/抽；后端接口测试覆盖。
- [x] 本地 C/C++/Python 真实容器样例运行、错误/超时/输出超限反馈；桥接复用及回调隔离通过自动测试。
- [x] 每日固定抽题、通过后签到、断签重置、7/14 天奖励、重复请求和并发幂等。
- [x] 投稿送审、拒绝反馈、编辑重新审核、首次批准五题奖励一次、规则版本隔离。
- [x] 账本、用户删除和历史提交保护；本地配置、部署说明、有限评测范围说明。
- [x] 前后端定向测试；浏览器实测登录、题库加载、搜索、打开题目与刷新保留路由。
- [x] 浏览器真实运行 Python 公开样例 3/3；刷新保留代码草稿，返回题单及浏览器后退恢复题目。
- [x] 390×844 手机尺寸题面/代码切换及页面无横向溢出；后台阶段、奖励页操作隔离，阶段与题目编辑弹窗打开/关闭及手机表单布局。
- [ ] 新扩展真实洛谷提交、手机端完整投稿审核闭环尚未实测；不以接口测试代替上述实测。

浏览器截图保存在本地 `output/playwright/coding-*-verified.png`、`coding-mobile-editor.png` 与 `coding-admin-*.png`。后台检查未修改现有题库与奖励配置；审核、奖励及权限写入行为由隔离数据库测试覆盖。

## 通过记录、内容修订与远端确认限制

题目题干、公开样例、评测方式或洛谷题号变更时递增独立内容版本；提交保留提交时的内容版本。题目详情、阶段进度和每日通过条件只统计当前内容版本的 Accepted，旧版本的结果仍保留在本人提交历史中。排序、星级、参考代码与审核状态变化不重置通过记录。尚未携带内容版本的早期预览提交保留原结果，但不推定它验证了当前题面。

每日题按北京时间日期固定，同一天重复请求复用原题，不因题目被停用、删除或撤回而自动换题。每日通过要求 Accepted 在当天完成且匹配当前内容版本；既往日期已经完成的通过、重复上报终态以及旧内容版本回调不计入新一天或新内容的通过。已完成的签到和奖励不因后续题库修订撤销。没有公开样例的样例题不进入每日抽题池，新增或修改样例题须提供至少一组输入输出。

洛谷结果沿用比赛模块的浏览器插件报告方式。服务端校验登录账号对本地提交的所有权、提交对应的评测方式、回调携带的题号、远端提交编号绑定、终态不可变和远端编号不可重复关联，但当前没有独立向洛谷核验 Accepted、远端账号或代码归属。题号比对仅验证回调与本地快照一致，不代表外站真实性验证；拥有自己登录凭据的用户仍可自行构造回调。当前远端通过与签到奖励适用于学习激励，不能当作防作弊成绩或独立核验的奖励结算。若部署要求抵御蓄意伪造，应先加入服务端对洛谷评测记录及归属的验证，再据此发放远端通过奖励。
