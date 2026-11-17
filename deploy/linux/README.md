# 单机网站与 IP HTTPS 配置

这些配置用于 Ubuntu 24.04 上的单机网站；可选部署原生 LiveKit 与 Redis，Egress 录制需额外资源。应用运行在 `/srv/scu/current`，私有配置为 `/etc/scu/config.toml`，数据独立保存在 `/srv/scu/data`。Git 更新只更新代码，不能覆盖私有配置、数据库、音频和密码查看密钥。

`scu.service` 使用一个 Uvicorn worker，监听 `127.0.0.1:8000`，Nginx 对外提供 HTTP/HTTPS。首次空数据库生成的管理员为 `root / root`；已有数据库的账号不会重置。正式使用时通过后台更改默认密码。

## 应用配置与服务

先按[部署手册](../../docs/deployment.md)创建 `scu` 服务账号、安装 Python 3.12、Docker、FFmpeg、LibreOffice **及 libreoffice-impress**、中文字体和 Python 依赖。只有 LibreOffice 核心程序时，即使转换程序存在也无法加载 PPT/PPTX。

配置中的数据库、录音、演示文件和直播文件目录分别使用 `/srv/scu/data/app.db`、`/srv/scu/data/audio`、`/srv/scu/data/presentations`、`/srv/scu/data/live`。`presentation.converter` 使用 `/usr/bin/libreoffice`；API Key 和 SMTP 凭据保存在服务器私有配置，不提交到 Git。未部署直播时将 `live.url`、`live.api_url`、`live.credentials_file` 留空，`live.recording_enabled` 设为 `false`。

在仓库根目录以 root 安装服务：

```sh
install -d -o scu -g scu -m 0700 /srv/scu/data/judge-tmp
install -o root -g root -m 0644 deploy/linux/scu.service /etc/systemd/system/scu.service
systemctl daemon-reload
systemctl enable --now scu
```

服务启用 `PrivateTmp`，因此 `TMPDIR` 必须指向宿主机与 Docker 都能访问的 `/srv/scu/data/judge-tmp`。不要改回私有 `/tmp`，否则编译与样例运行的 Docker bind mount 会失败。`ReadWritePaths` 只允许应用写入私有数据目录。

## IP 证书与 Nginx

已验证公网 IP `123.57.76.66` 可签发 Let’s Encrypt `shortlived` 证书，Certbot 5.10.0 支持 `--ip-address`。证书有效期短，必须配置自动续期。Certbot 官方说明见 [Certbot 使用文档](https://eff-certbot.readthedocs.io/en/stable/using.html)，可用证书配置由 [ACME directory](https://acme-v02.api.letsencrypt.org/directory) 公布。其他 IP 部署时替换命令中的地址，并允许公网 TCP 80 和 443 访问；应用 8000 端口保持回环监听。

先装 HTTP 配置以提供 ACME 验证文件，保留原站点备份但不要放在 Nginx 的 `sites-enabled` 中，否则仍会加载：

```sh
python3.12 -m venv /opt/scu-certbot
/opt/scu-certbot/bin/pip install 'certbot==5.10.0'
install -d -m 0755 /var/www/letsencrypt
install -m 0644 deploy/linux/scu-app.conf /etc/nginx/sites-available/scu-app
ln -sfn /etc/nginx/sites-available/scu-app /etc/nginx/sites-enabled/scu-app
nginx -t
systemctl reload nginx
```

确认 `sites-enabled` 没有第二个默认站点后签发证书。以下命令注册无邮箱通知的 ACME 账户，证书故障需通过服务日志与监控发现：

```sh
/opt/scu-certbot/bin/certbot certonly --webroot --webroot-path /var/www/letsencrypt \
  --ip-address 123.57.76.66 --preferred-profile shortlived \
  --cert-name scu-ip --agree-tos --register-unsafely-without-email --non-interactive \
  --config-dir /etc/letsencrypt-scu --work-dir /var/lib/letsencrypt-scu \
  --logs-dir /var/log/letsencrypt-scu
install -m 0644 deploy/linux/scu-app-https.conf /etc/nginx/sites-available/scu-app
nginx -t
systemctl reload nginx
install -m 0644 deploy/linux/scu-certbot-renew.service /etc/systemd/system/scu-certbot-renew.service
install -m 0644 deploy/linux/scu-certbot-renew.timer /etc/systemd/system/scu-certbot-renew.timer
systemctl daemon-reload
systemctl enable --now scu-certbot-renew.timer
```

定时器每六小时检查续期，成功续期后重载 Nginx；webroot 验证无需停服。证书位于 `/etc/letsencrypt-scu/live/scu-ip/`。验收必须在证书校验开启时运行：

```sh
curl -I https://123.57.76.66/
/opt/scu-certbot/bin/certbot renew --dry-run --config-dir /etc/letsencrypt-scu \
  --work-dir /var/lib/letsencrypt-scu --logs-dir /var/log/letsencrypt-scu
systemctl status scu scu-certbot-renew.timer --no-pager
```

后台系统设置中的洛谷插件网站来源设置为 `https://123.57.76.66`，重新下载插件后才会使用此来源，不能保留开发地址 `http://127.0.0.1:8000`。

## 隔离样例评测

默认在项目根目录运行 `sh scripts/prepare_judge.sh`。服务器访问 Docker Hub 或 Alpine 官方软件源超时时，可使用网络可达的可信镜像源取得 `python:3.12-alpine`，并使用 `judge.Dockerfile` 将 Alpine 软件源改为阿里云镜像；不需要修改应用代码：

```sh
docker pull docker.m.daocloud.io/library/python:3.12-alpine
docker tag docker.m.daocloud.io/library/python:3.12-alpine python:3.12-alpine
docker build -t scu-judge:1 -f deploy/linux/judge.Dockerfile judge
```

应以 `scu` 用户实际运行 C++11、C、Python 3 样例，并验证 PPT 转换。镜像可见、进程 active 和首页 HTTP 200 不能代替这些功能验收。网站部署不代表公网直播、真实 ASR/TTS 调用或多人负载已通过验收。

## 公网直播媒体服务

本机 Docker Compose 配置不适用于这台 1 GB 内存的公网机。可从 LiveKit 官方 [v1.13.11 Linux release](https://github.com/livekit/livekit/releases/tag/v1.13.11) 安装原生 SFU，Redis 只绑定回环地址；应用连接 `127.0.0.1:7880`，浏览器走现有 IP TLS 证书和 Nginx `/livekit/` WebSocket 路径。先校验 release checksum，再把 `livekit-server`、`configure_live.py`、`scu-livekit.service` 和 `renew_live_tls.sh` 放到服务器 `/tmp/`，以 root 执行：

```sh
printf '1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb  livekit_1.13.11_linux_amd64.tar.gz\n' | sha256sum -c -
tar -xzf livekit_1.13.11_linux_amd64.tar.gz livekit-server
install -o root -g root -m 0755 livekit-server /usr/local/bin/livekit-server
python3 configure_live.py --public-ip 123.57.76.66
```

脚本生成 `/etc/scu-live/` 下的随机 API 密钥，配置 `scu-livekit.service`、Redis、Nginx 反代与证书续期钩子，并更新应用 `[live]` 配置。它不会启用录制。阿里云安全组和主机防火墙须开放 TCP 7881、5349，UDP 7882 和 UDP 30000–30100；应用端口 7880 与 Redis 6379 只允许回环访问。未开放媒体端口时，网页和 HTTPS 信令可能正常，但音视频无法连通。登录两种外网浏览器真实验证发布、接收与 TURN 网络前，不要把 HTTP 200 或服务 active 视为课堂媒体可用。

服务器可用内存不足 400 MiB、只有 2 vCPU，未在该机器上部署 Egress。开启合成 MP4 录制需另配 Egress、至少约 4 GiB 可用内存、足够 CPU 和持久共享录制卷；启用前完成录制/回放验收。查看状态使用 `systemctl status scu-livekit redis-server scu nginx --no-pager` 与 `journalctl -u scu-livekit -n 80 --no-pager`。

## 更新与排查

```sh
git -C /srv/scu/current pull --ff-only origin codex/initial-system
systemctl restart scu
systemctl status scu --no-pager
journalctl -u scu -n 80 --no-pager
journalctl -u scu-certbot-renew -n 40 --no-pager
```

更新前备份 SQLite 数据库、私有配置及文件目录。应用使用后台数据库设置保存模型配置与插件来源；后续部署不要重新复制开发数据库或覆盖服务器配置。
