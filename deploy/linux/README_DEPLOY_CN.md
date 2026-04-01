# 报价系统阿里云部署说明（Alibaba Cloud Linux 3）

## 1. 目标
- 在云服务器 `47.112.197.85` 上稳定运行当前系统
- 后续发版尽量一条命令完成

本方案默认：
- 系统代码在 Git 仓库中
- 服务由 `systemd` 托管
- `nginx` 反向代理到本机 `127.0.0.1:5173`
- 数据保存在服务器本地 SQLite（`sales.db`）

## 2. 首次部署
在本地执行（替换你的仓库地址）：

```bash
ssh root@47.112.197.85
```

进入服务器后执行：

```bash
# 例：先把代码上传到 /opt/sales-app/app（如果你已git仓库，可直接git clone）
mkdir -p /opt/sales-app
cd /opt/sales-app

# 假设已经把本项目放到 /opt/sales-app/app
cd /opt/sales-app/app
chmod +x deploy/linux/init_server.sh deploy/linux/release.sh deploy/linux/status.sh

# 初始化（把下面仓库地址换成你的）
sudo bash deploy/linux/init_server.sh https://github.com/your-org/your-repo.git main
```

完成后访问：
- `http://47.112.197.85/index.html`

## 3. 日常发版（简单）
每次发布只需要：

```bash
ssh root@47.112.197.85
cd /opt/sales-app/app
sudo bash deploy/linux/release.sh main
```

脚本能力：
- 拉取最新代码
- 重启服务
- 健康检查失败自动回滚到上一个版本

## 4. 运维常用命令
```bash
sudo bash /opt/sales-app/app/deploy/linux/status.sh
sudo systemctl restart sales-app
sudo journalctl -u sales-app -f
```

## 5. 重要数据路径
- 主数据库：`/opt/sales-app/app/sales.db`
- 名片图片：`/opt/sales-app/app/customer_cards/`
- 备份目录：`/opt/sales-app/app/backups/`

建议把以上目录定期做 ECS 快照或对象存储备份。

## 6. 安全建议（建议上线后补）
- 绑定域名并启用 HTTPS（`certbot`）
- 控制安全组仅开放 `80/443`（不要开放 5173）
- 限制 SSH 登录来源或改用堡垒机

## 7. GitHub Actions 自动发版（push main）
项目已内置工作流：
- `.github/workflows/deploy-ecs.yml`

每次 `push main` 会自动 SSH 到 ECS 并执行：
```bash
sudo bash deploy/linux/release.sh main
```

### 7.1 需要在 GitHub 仓库配置 Secrets
- `ECS_HOST`：`47.112.197.85`
- `ECS_USER`：用于登录服务器的用户（建议 `root` 或有 sudo 权限用户）
- `ECS_SSH_PRIVATE_KEY`：该用户对应私钥内容
- `ECS_KNOWN_HOSTS`：服务器 host key（`known_hosts` 一行或多行）

可在本地生成 `ECS_KNOWN_HOSTS`：
```bash
ssh-keyscan -H 47.112.197.85
```

### 7.2 sudo 免密建议
为了让工作流无交互执行，需要该用户对发版脚本免密 sudo。  
例如（按你实际用户调整）：
```bash
echo "root ALL=(ALL) NOPASSWD: /usr/bin/bash /opt/sales-app/app/deploy/linux/release.sh *" | sudo tee /etc/sudoers.d/sales-release
sudo chmod 440 /etc/sudoers.d/sales-release
```
