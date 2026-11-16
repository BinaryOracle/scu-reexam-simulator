# 系统部署手册

本文从空环境部署四川大学计算机复试模拟系统。系统由 FastAPI 应用、SQLite 和私有文件目录组成；上机代码隔离运行于 Docker；直播音视频通过 LiveKit 传输，录播由 Egress 合成并写入私有存储。AI 面试点评、语音识别和语音合成使用服务端配置的阿里云百炼 API。洛谷提交插件运行在用户浏览器中，不在服务器保存洛谷凭证。

本手册覆盖两种部署：Mac 本机试用使用仓库提供的一键脚本；面向异地学员的公网部署需要域名、HTTPS、可达的 WebRTC 媒体端口及 TURN 规划。`deploy/live-local` 只供本机使用，不能直接公开到互联网。

## 组件清单

| 组件 | 用途 | 是否必需 |
| --- | --- | --- |
| Python 3.12、FastAPI、Uvicorn | 网页、账号、面试、上机、管理后台 API | 必需 |
| SQLite 与 `data/` 私有文件 | 账号、记录、题库、PPT、音频、公告附件、直播资料和录播 | 必需 |
| Docker Engine | 隔离运行旧版本地比赛和算法带刷代码 | 使用本地 Docker 评测时必需 |
| LiveKit Server | 直播信令和 WebRTC 音视频转发 | 启用直播时必需 |
| Redis | LiveKit 与 Egress 的任务协调 | 启用直播时必需 |
| LiveKit Egress | 录制及生成课堂 MP4 | 启用录播时必需 |
| LibreOffice、中文字体 | 将 PPT/PPTX 转成私有幻灯片预览 | 上传 Office 演示文稿时必需；PDF 可直接预览 |
| FFmpeg | ASR 音频格式转换和分段 | 启用语音识别时必需 |
| 阿里云百炼 API | AI 专家提问、点评、ASR、TTS、热点趋势 | 对应 AI 功能必需；其余系统可独立运行 |
| SMTP 服务 | 邮箱验证码登录与敏感操作验证 | 启用邮箱登录时必需 |
| HTTPS 反向代理及 TLS 证书 | 公网访问应用和 LiveKit WebSocket | 公网部署必需；本机回环访问不需要 |
| TURN 服务 | UDP 受限网络中的媒体中继 | 公网部署强烈建议，校园网验收需要 |
| Chrome/Edge 洛谷插件 | 使用用户已有洛谷登录态提交和读取评测结果 | 创建了洛谷桥接比赛时必需 |

## Mac 本机部署

本节对应 `scripts/live_local.py`，会启动应用、Redis、LiveKit 和 Egress。媒体端口只绑定到 `127.0.0.1`，只适合当前 Mac 上访问。

### 准备环境

安装 Python 3.12、Docker Desktop、FFmpeg 和 LibreOffice，启动 Docker Desktop。若要转换中文 PPT，确保系统安装了可用的中文字体。Docker Desktop 建议分配 4 GiB 内存；首次下载 LiveKit 镜像建议预留 10 GiB 磁盘空间。

在项目根目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
if [ ! -f config.toml ]; then cp config.example.toml config.toml; fi
chmod 600 config.toml
sh scripts/prepare_judge.sh
```

如需 AI 点评、ASR 或 TTS，在本机编辑被 Git 忽略的 `config.toml`，将 `[ai]`、`[asr]`、`[tts]` 中对应的 API Key 配好。三个模块可共用同一百炼 Key。启用邮箱验证码登录时，按[邮箱登录配置](email-login.md)补全 `[email_auth]` 并配置 SMTP 授权码。不要把密钥写入 `config.example.toml`、提交到 Git 或放进浏览器配置。

### 启动与登录

```sh
.venv/bin/python scripts/live_local.py start
.venv/bin/python scripts/live_local.py status
```

首次启动会生成 LiveKit API 凭据、写入本机私有目录 `data/live-deploy/`，配置 `config.toml` 的 `[live]`，启动 Redis、LiveKit、Egress，并在后台启动一个 Uvicorn worker。应用地址为 `http://127.0.0.1:8000/`，后台为 `http://127.0.0.1:8000/admin`。空数据库首次启动会创建 `root / root`；登录后先重置默认密码并创建普通用户。已有数据库不会被重置。

首次启动后检查媒体与应用状态：

```sh
.venv/bin/python scripts/live_local.py status
.venv/bin/python scripts/live_local.py logs
```

`status` 应显示应用 HTTP、LiveKit HTTP 可达，且 Egress、Redis 健康。再分别用两个浏览器账号实际验证加入课堂、麦克风/摄像头、屏幕共享、评论、资料下载、开始/停止录制及录播回放。健康检查只能证明进程可用，不能替代浏览器 WebRTC 验收。

上机页使用洛谷比赛时，下载并安装[浏览器插件](luogu-bridge.md)，在同一浏览器登录洛谷并回本站检测连接。浏览器插件只使用本机现有洛谷会话。

停止和重启：

```sh
.venv/bin/python scripts/live_local.py stop
.venv/bin/python scripts/live_local.py start
```

`stop` 会停止本脚本管理的应用及 `scu-live-local` 容器，不会关闭 Docker Desktop，也不会删除业务数据。如果 8000 端口已被其他 Uvicorn 进程占用，脚本会拒绝接管；需先按原启动方式停止该进程。不要在 `stop` 时仍有正在进行的课程。

### 本机配置与限制

应用配置统一保存在 `config.toml`。数据库默认为 `data/app.db`，录音默认在 `data/audio/`，演示文稿在 `data/presentations/`，直播资料与录播在 `data/live/`。`data/live-deploy/` 保存本机媒体服务凭据和启动日志。以上数据均为私有数据，不应移动到 `app/static/` 或公共 Web 目录。

本机直播脚本固定 LiveKit Server 1.13.11、Egress 1.15.0 和 Redis 7.4.8，并锁定镜像摘要。Egress 限制为 4 CPU、3 GiB 内存，适合单间课堂录制；这不是 50 人负载通过证明。屏幕共享默认 1080p/15 fps/3 Mbps，录播默认 1080p/30 fps/4500 kbps；详细参数见[直播课堂配置](live-classroom.md#应用配置)。

本机媒体使用回环网络、HTTP 和关闭 Chrome sandbox 的 Egress 配置。禁止将这些配置直接暴露到公网或用于不受信任的课堂。公开授课请按下面的公网部署章节及 LiveKit 官方文档另行配置。

## 公网 Linux 部署

公网部署适用于一个 Linux 主机上的单机试点。应用仍使用一个 Uvicorn worker、SQLite 和本地持久盘；不要通过多 worker 或多应用副本横向扩展。该版本没有提供公网 LiveKit/TURN 的自动安装器。管理员必须完成本节网络、证书、ICE、Egress sandbox 和持久卷配置后再开放服务。

### 规划主机与域名

建议使用提供 Python 3.12 的受支持 Linux x86-64 主机，配置固定公网 IPv4、SSD 持久盘、Docker Engine/Compose、Nginx、FFmpeg、LibreOffice 和中文字体。至少准备两个 DNS 名称：`app.example.org` 指向应用反向代理，`media.example.org` 指向 LiveKit 信令入口。正式使用前安装受信任的 TLS 证书。

防火墙仅允许 SSH 管理地址、TCP 80/443、LiveKit TCP 7881、LiveKit UDP 媒体端口范围和所需 TURN/TLS 端口。Redis、应用端口 8000、LiveKit API 端口 7880、Egress health 端口不得直接开放公网。具体 UDP 范围必须同时写入 LiveKit 配置、Docker 端口映射和云安全组；范围不一致会表现为信令已连接但没有音视频。

建议网络路径如下：

```text
浏览器 HTTPS/WSS -> Nginx -> Uvicorn 127.0.0.1:8000
浏览器 WSS      -> Nginx -> LiveKit 127.0.0.1:7880
浏览器 WebRTC   -> LiveKit TCP 7881 / UDP 50000-60000
限制网络用户    -> TURN/TLS（单独规划证书和监听端口）
LiveKit/Egress   -> 私有 Redis；Egress -> LiveKit；Egress -> 同一录播卷
```

LiveKit 建议按官方自托管说明配置公网 IP、TCP/UDP ICE、Redis 和 API 密钥；校园网和企业网需要 TURN/TLS。Egress 必须按对应版本的官方部署说明开启 Chrome sandbox，并配置所需容器权限和共享内存。不要复制本机 `enable_chrome_sandbox: false` 设定作为公网安全配置。

官方部署参考：[LiveKit 自托管](https://docs.livekit.io/home/self-hosting/)、[LiveKit 部署与网络](https://docs.livekit.io/home/self-hosting/deployment/)、[Egress 部署](https://docs.livekit.io/home/egress/deployment/)和[TURN 部署](https://docs.livekit.io/home/self-hosting/ingress-egress/)。上线时固定并验证 LiveKit Server、Egress、Redis 镜像版本，避免使用 `latest`。

下面是本系统单机媒体服务的配置起点。将其保存在权限受限的 `/etc/scu/livekit.yaml` 和 `/etc/scu/egress.yaml`，替换密钥并按实际公网网卡、云网络和官方 Egress sandbox 要求调整：

```yaml
# /etc/scu/livekit.yaml
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: true
redis:
  address: redis:6379
keys:
  scu-prod: REPLACE_WITH_RANDOM_SECRET
webhook:
  api_key: scu-prod
  urls:
    - https://app.example.org/api/live/webhook
logging:
  level: info
```

```yaml
# /etc/scu/egress.yaml
ws_url: ws://127.0.0.1:7880
redis:
  address: redis:6379
health_port: 9090
enable_chrome_sandbox: true
logging:
  level: info
```

同一个 API Key/Secret 也放入仅供 Compose 读取的 `/etc/scu/live.env`：

```sh
LIVEKIT_API_KEY=scu-prod
LIVEKIT_API_SECRET=REPLACE_WITH_RANDOM_SECRET
```

给配置和环境文件设置 `0600` 权限。`REPLACE_WITH_RANDOM_SECRET` 必须由密码生成器产生，并在 LiveKit 配置、Egress 环境和应用配置中保持完全一致。

按 Egress 1.15.0 官方说明下载对应版本的 Chrome sandbox seccomp profile，并限制为管理员可修改：

```sh
sudo curl -fsSL https://raw.githubusercontent.com/livekit/egress/v1.15.0/chrome-sandboxing-seccomp-profile.json -o /etc/scu/chrome-sandboxing-seccomp-profile.json
sudo chmod 600 /etc/scu/chrome-sandboxing-seccomp-profile.json
```

Compose 部署示例保存为 `/etc/scu/compose.yaml`：

```yaml
services:
  redis:
    image: redis:7.4.8-alpine
    restart: unless-stopped
    command: [redis-server, --save, "", --appendonly, "no"]
    healthcheck:
      test: [CMD, redis-cli, ping]
      interval: 5s
      timeout: 3s
      retries: 12

  livekit:
    image: livekit/livekit-server:v1.13.11
    restart: unless-stopped
    command: [--config, /etc/livekit.yaml]
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - 127.0.0.1:7880:7880
      - 127.0.0.1:9090:9090
      - 7881:7881
      - 50000-60000:50000-60000/udp
    volumes:
      - /etc/scu/livekit.yaml:/etc/livekit.yaml:ro

  egress:
    image: livekit/egress:v1.15.0
    restart: unless-stopped
    network_mode: service:livekit
    depends_on:
      livekit:
        condition: service_started
    env_file:
      - /etc/scu/live.env
    environment:
      EGRESS_CONFIG_FILE: /etc/egress.yaml
    volumes:
      - /etc/scu/egress.yaml:/etc/egress.yaml:ro
      - /srv/scu/data/live/recordings:/out
    shm_size: 1gb
    mem_limit: 3g
    cpus: 4
    security_opt:
      - seccomp=/etc/scu/chrome-sandboxing-seccomp-profile.json
    healthcheck:
      test: [CMD, curl, -fsS, http://127.0.0.1:9090/]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 10s
```

Redis 不发布宿主机端口。Egress 与 LiveKit 共用网络命名空间以便连接回环 WSS，录播目录映射到同一宿主持久卷。按 Egress 官方建议，为 `/srv/scu/data/live/recordings` 配置与 Egress 容器运行 UID/GID 对应的 ACL 或属组写权限，不要开放整个 `/srv/scu/data`。启动后检查该目录可由 Egress 新建文件，再由应用账号读取。保存后执行 `docker compose -f /etc/scu/compose.yaml config` 检查，再用 `docker compose -f /etc/scu/compose.yaml up -d` 启动服务。确认 Redis、LiveKit 和 Egress 健康后，再继续应用 webhook 和录制验收。

### 部署应用与评测器

创建独立服务账号及项目目录，将代码部署到固定版本目录。为上传目录、数据库、私钥和日志创建应用账号可读写的持久目录，并限制权限。不要将配置文件、数据库、录音或日志放入公开静态目录。

系统依赖可由发行版包管理器安装，Debian/Ubuntu 主机至少需要 Python 3.12、venv、Docker Engine/Compose、Nginx、FFmpeg、LibreOffice 和中文字体。Python 3.12 的获取方式及 Docker Engine 安装命令按主机发行版官方文档执行；生产主机不要安装 Docker Desktop。

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
chmod 600 config.toml
sh scripts/prepare_judge.sh
```

在 `config.toml` 中将数据库和私有文件放到代码目录以外的持久卷。示例：

```toml
[app]
database = "/srv/scu/data/app.db"
upload_dir = "/srv/scu/data/audio"

[security]
password_key_file = "/srv/scu/data/password-view.key"

[presentation]
directory = "/srv/scu/data/presentations"
```

公告图片保存在 `upload_dir/announcements`；面试录音等保存在 `upload_dir` 下的业务子目录。`[live].directory` 另设为 `/srv/scu/data/live`。确保应用账号可以读写这些目录，并让 Egress 的 `/out` 映射到 `/srv/scu/data/live/recordings`。第一次启动会自动执行 SQLite schema 迁移并初始化默认管理员 `root / root`；之后立即重置默认密码。以后版本升级前必须备份数据库及其密码查看密钥、所有私有数据目录，不能用新版本覆盖或丢弃旧数据库。

Docker 评测会从应用进程调用 Docker CLI。若在单机试点启用，应用服务账号必须访问 Docker socket（常见做法是加入 `docker` 组），这等同于授予近似 root 的宿主机权限；仅在可信单机试点使用。对公网运行不可信用户代码时，应把评测器迁到隔离的独立主机或受限判题服务，并限制网络、镜像来源、资源、并发和宿主目录挂载。

### 配置公网 LiveKit 与 Egress

为 LiveKit、Egress 和应用使用同一组专用 API Key/Secret。将密钥分别注入 LiveKit 服务配置、Egress 容器环境，以及应用服务环境变量，或为应用设置私有 JSON `credentials_file`。配置文件只能由对应服务账号读取，权限不宽于 `0600`；不得把真实密钥提交进仓库或复制到浏览器。

应用 `[live]` 至少填写以下值，其他参数按[直播课堂配置](live-classroom.md#应用配置)设置：

```toml
[live]
url = "wss://media.example.org"
api_url = "http://127.0.0.1:7880"
api_key_env = "LIVEKIT_API_KEY"
api_secret_env = "LIVEKIT_API_SECRET"
credentials_file = ""
directory = "/srv/scu/data/live"
recording_enabled = true
egress_directory = "/out"
```

`url` 是浏览器访问的 LiveKit 地址，必须是 HTTPS 站点可连接的 WSS。`api_url` 是应用服务访问 LiveKit HTTP API 的地址，可以使用本机回环地址。将 `[live].directory/recordings` 与 Egress 容器的 `/out` 映射到同一个宿主持久目录；应用与 Egress 都必须能写入。课程资料目录也必须持久化。验证 Egress 结束 webhook 能从 LiveKit 到达 `https://app.example.org/api/live/webhook`，Nginx 需原样转发请求正文及 `Authorization` 签名头。

应用配置中的 `recording_enabled=true` 只有在 LiveKit、Redis、Egress、签名 webhook 和共享卷均通过验收后才设置。否则录制接口会失败或显示未就绪，不能只凭容器启动状态判断录播可用。

### 配置应用服务与 HTTPS 代理

应用通过单 worker Uvicorn 监听回环地址。将下列内容保存为 systemd unit，并按实际代码目录、Linux 用户和环境文件路径替换：

```ini
[Unit]
Description=SCU Re-exam Simulator
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=scu
Group=scu
WorkingDirectory=/srv/scu/current
Environment=SCU_CONFIG=/etc/scu/config.toml
EnvironmentFile=-/etc/scu/app.env
ExecStart=/srv/scu/current/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`/etc/scu/app.env` 只放应用需要的密钥环境变量，例如 `LIVEKIT_API_KEY`、`LIVEKIT_API_SECRET`、`DASHSCOPE_API_KEY`、`ASR_API_KEY` 和 `SCU_SMTP_PASSWORD`。按使用功能添加，不需要的变量可省略；该文件不存在时 systemd 会忽略它。若使用该文件，设置为 `root:root` 所有且权限 `0600`；systemd 管理进程读取后再启动应用，禁止把环境变量打印到部署日志。`/etc/scu/config.toml` 需要可由应用服务账号读取，但只允许管理用户修改。systemd 启用服务后检查 `systemctl status` 和 `journalctl -u`，确认只运行一个 Uvicorn worker。

保存 unit 为 `/etc/systemd/system/scu-simulator.service` 后运行：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now scu-simulator.service
sudo systemctl status scu-simulator.service
```

Nginx 在 `http` 配置上下文中增加不含查询参数的日志格式，避免把录播票据写入访问日志：

```nginx
log_format scu_no_query '$remote_addr $request_method $uri $status $body_bytes_sent $request_time';
```

应用 HTTPS 虚拟主机示例：

```nginx
server {
    listen 443 ssl;
    server_name app.example.org;
    ssl_certificate /etc/letsencrypt/live/app.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.org/privkey.pem;
    access_log /var/log/nginx/scu-app.log scu_no_query;
    client_max_body_size 30m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_request_buffering off;
    }
}
```

视频回放支持 Range 请求，Nginx 默认代理会转发相关请求头；验收时仍须确认 `206 Partial Content` 和 `Content-Range`。设置上传大小时，应与 `config.toml` 中的 PPT、音频及直播资料限制一致。

LiveKit 信令域名的 Nginx 虚拟主机转发到 `127.0.0.1:7880`，开启 WebSocket Upgrade，并配置足够长的读写超时：

```nginx
server {
    listen 443 ssl;
    server_name media.example.org;
    ssl_certificate /etc/letsencrypt/live/media.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/media.example.org/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:7880;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

LiveKit TCP/UDP 媒体端口由浏览器直连，不经过普通 HTTP 代理；云安全组、主机防火墙和 LiveKit 的 ICE 配置必须一致。限制 UDP 的网络需要单独设置 TURN/TLS 并在浏览器侧验证候选地址。

配置文件写入后先运行 `sudo nginx -t`，再执行 `sudo systemctl reload nginx`。申请或更新 TLS 证书时确保 DNS 已指向服务器且 TCP 80/443 可达；证书续期应启用自动续期并监控失败状态。

### 外网验收

正式给学员使用前，至少完成：

1. 从非服务器网络打开 HTTPS 页面，登录普通用户并验证权限隔离。
2. 使用两个不同网络的浏览器加入同一课堂，验证麦克风、摄像头、屏幕共享、发言授权、评论和离开重连。
3. 在 UDP 可用网络和 TURN-only 网络分别验证媒体收发；浏览器 WebSocket 成功不代表 WebRTC 通道可达。
4. 主持人开始并停止 Egress 录制，确认 MP4 出现在共享持久卷、数据库状态变为可播放，学员可拖动播放且非成员无法访问。
5. 验证签名 webhook 拒绝无效签名，真实 Egress 事件可更新录制状态；停止 Egress 或断开共享卷时页面明确报错。
6. 上传 PPTX、PDF、直播资料和公告图片，重启应用后数据仍存在。
7. 验证 Docker 评测器在无网络容器中执行、超时后容器被清理；洛谷插件在 Chrome/Edge 与用户已登录的洛谷页面配合提交。
8. 评估目标课堂规模下 CPU、内存、网络、录播码率和磁盘增长。默认单机配置未证明 50 人并发能力。

## 日常运维

### 备份与恢复

备份必须包括 SQLite 数据库、数据库旁的 `password-view.key`、整个 `data/` 私有文件目录、运行配置、直播凭据、LiveKit 配置和生产 TLS/密钥管理材料。至少保留一份加密的异机备份。面试录音、PPT、公告图片、直播资料和录播不只存在于数据库中。

单机维护时先让主持人结束课堂并停止应用写入，再备份数据库与私有目录；恢复时先停止应用，恢复同一时间点的数据库、密钥和文件，校验目录权限，然后启动应用并抽查面试播放、PPT 展示、公告图片和录播 Range 回放。缺少 `password-view.key` 会导致无法查看旧账号密码原文；缺少媒体凭据会导致 LiveKit/Egress 无法相互认证。

### 升级

升级顺序：通知用户退出，结束直播并停止录制，备份所有数据；部署新代码并安装 `requirements.txt`；运行 `sh scripts/prepare_judge.sh` 检查或重建评测镜像；确认 `config.toml` 的路径和密钥未被覆盖；启动应用。数据库迁移在应用导入时自动执行，启动日志报迁移异常时不要重复清理或重建数据库，先恢复备份并检查迁移日志。最后按本手册验收登录、PPT、面试记录、上机、录播和权限。

### 日志与容量

Mac 查看服务状态和媒体日志：

```sh
.venv/bin/python scripts/live_local.py status
.venv/bin/python scripts/live_local.py logs
tail -n 200 data/live-deploy/app.log
```

Linux 查看应用和容器日志使用 `journalctl -u <应用服务名>` 与 `docker compose logs --tail=200 livekit egress redis`。定期监控 `data/` 可用空间、录播大小、Egress 失败率及 Redis/LiveKit/Egress 健康状态。MP4 是高码率视频文件，按课时估算存储增长并制定保留和异机备份策略；清理录播前要通过应用管理流程删除数据库记录，不能只删除文件。

## 故障排查

| 现象 | 检查项 |
| --- | --- |
| 页面无法打开 | 应用服务日志、8000 回环监听、Nginx 上游和 TLS 证书 |
| AI/语音功能提示未配置 | `config.toml` 模型地址、环境变量名称和服务账号可见的 API Key；不要把 Key 放入前端 |
| PPT 上传后无法预览 | `soffice` 路径、LibreOffice、中文字体、`fontconfig_file`、转换日志及私有目录权限 |
| Docker 评测按钮不可用 | Docker Engine、应用账号 Docker CLI/socket 权限、`scu-judge:1` 镜像和容器资源 |
| 直播服务未就绪 | LiveKit URL、API 凭据、应用到 LiveKit API 网络、LiveKit 健康状态 |
| 已连接但没有音视频 | ICE 公网地址、TCP/UDP 映射、云防火墙、安全组、校园网 UDP 和 TURN/TLS |
| 屏幕共享黑屏或卡顿 | Chrome/macOS 屏幕录制权限、浏览器采集源、上行网络、发送端与接收端轨道状态 |
| Egress 无法开始录制 | Redis、Egress 健康、密钥一致、可达的 LiveKit URL、容器 sandbox/权限、共享 `/out` 写权限和剩余磁盘 |
| 录播不可播放或进度拖动失败 | Egress 完成 webhook 签名、文件名与共享卷一致、应用可读文件、反向代理 Range 与票据日志策略 |
| 洛谷提交没有结果 | 浏览器插件版本、来源授权、洛谷登录标签页、验证码/交互验证和插件 Service Worker 诊断；见[桥接说明](luogu-bridge.md) |

## 相关文档

- [直播课堂配置、权限与验收](live-classroom.md)
- [洛谷浏览器插件安装和排查](luogu-bridge.md)
- [上机评测器准备](coding-catalog.md#评测部署)
- [邮箱验证码与 SMTP](email-login.md)
- [项目功能、快速启动和升级说明](../README.md)
