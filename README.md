# 四川大学计算机复试模拟系统 V1.0

独立部署的学校/培训机构模拟考试系统，包含考生、教师两类账号，模拟面试录音与 AI 点评，以及参考 VJudge/洛谷竞赛流程的限时 OJ。此项目不依赖 DeepSeek Harness。V1.0 的代码语言为 Python 3.12，数据库为 SQLite；上机提交仅支持 Python 3。

## 快速启动

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
.venv/bin/python -m scripts.create_user teacher --role teacher
.venv/bin/python -m scripts.create_user student --role student
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000。配置文件 `config.toml` 集中设置数据路径、录音大小、会话时长、面试题、AI/ASR 接口、评测镜像和资源限制。API 密钥通过配置指定的环境变量注入，不应写入配置或提交到版本控制。

## V1.0 能力

- 教师创建限时比赛、录入题目与隐藏测试数据；学生在比赛时间内查看题目、保存本地草稿、提交 Python 3 代码并查看判题状态。
- 判题在 Docker 容器中逐测试用例执行，关闭网络、只读根文件系统、删除 Linux capabilities、限制进程/内存/CPU、以非 root 用户运行。构建镜像：`docker build -t scu-judge:1.0 judge/`。**Docker daemon 未运行时提交显示 Judge Error，不会退回宿主机执行代码。**
- 面试固定题目在配置文件中调整。浏览器按题录音并上传、回放、调用可配置 ASR；考生可编辑转写文本。AI 只生成最后的老师追问和整场点评。
- 面试转写、录音及点评按场次保存；教师可查看考生面试和提交记录。会话凭证使用 Bearer token，密码使用 scrypt 哈希。

## 外部服务与规则

默认 AI 配置兼容 OpenAI Chat Completions 格式。语音识别配置兼容 `/audio/transcriptions` 格式。需分别配置 URL、模型和环境变量凭据。未配置 ASR 时录音仍会保存，可人工输入/修改转写。未配置 AI 时不会产生虚构追问或点评，接口返回清晰错误。

VJudge 比赛页需登录后才能核实题目，本系统不抓取或复制其受限内容。教师应仅录入有权使用的题目。比赛时长、试题、语言和评分规则由机构确认后配置；示例配置中的面试问题和计时并非四川大学官方规定。

## 验证

```sh
python -m pytest -q
```

当前测试覆盖账号隔离、面试状态、比赛权限/截止时间、隐藏测试数据，以及 ASR 未配置时录音保留。判题以注入的假评测服务做路由测试；真实 Docker 镜像执行需在 Docker daemon 可用的主机另行验证。

## V1.0 部署边界

此版本定位为本地/单机试点：SQLite、同步评测和本地录音存储。正式部署应放在 HTTPS 反向代理之后，配置授权的 AI/ASR 服务并启用 Docker；备份数据库和录音目录。账号由教师在服务器命令行创建，暂不含自助注册、密码重置、考生批量导入、机构单点登录、远程多节点判题、审计报表或防作弊监控。
