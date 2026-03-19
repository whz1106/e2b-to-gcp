# E2B GCP 部署手册与实战记录

本文基于本次在 GCP 上实际完成的 self-hosted E2B 部署整理，目标不是复述官方文档，而是给出一份可以直接照着执行的实战版手册。

覆盖内容：

- 部署前提和软件安装
- GCP / Cloudflare 侧准备
- 实际部署顺序和命令
- 常见报错与处理办法
- 本次部署中涉及的代码改动
- 如果不改代码，哪些场景仍然可行，哪些场景会卡住

## 1. 本次部署结果

本次最终部署成功，最终状态如下：

- 环境：`dev`
- GCP Project：`prismshadow2`
- Region：`us-west1`
- Zone：`us-west1-a`
- Domain：`agentyard.top`
- Provider：`gcp`
- 部署日期：`2026-03-17`

最终验证结果：

- `https://nomad.agentyard.top` 返回 `307` 并跳转到 `/ui/`
- `https://api.agentyard.top/health` 返回 `200`
- `e2b-backend-api` 后端健康状态为 `HEALTHY`
- client 节点上 orchestrator 本地健康检查正常

## 2. 部署前提

### 2.1 机器要求

建议在一台 Linux 服务器上执行整套部署流程，原因是：

- Packer / Terraform / Docker / gcloud 组合在 Linux 服务器上最稳定
- 需要长时间运行构建和上传任务
- 这次实际部署也是在 Linux 服务器上完成的

### 2.2 必装软件

至少需要这些工具：

- `git`
- `make`
- `curl`
- `unzip`
- `jq`
- `docker`
- `node` / `npm`
- `go`
- `packer`
- `terraform` `1.5.7`
- `gcloud` CLI

建议版本：

- Terraform：`1.5.7`
- gcloud：最新版即可
- Docker：可正常 `docker build` / `docker push`
- Go：仓库要求版本附近即可，实际以项目能编译通过为准
- Node：支持仓库里脚本运行即可

### 2.3 一个可执行的安装思路

如果是 Ubuntu 机器，至少先保证这些基础命令可用：

```bash
sudo apt-get update
sudo apt-get install -y git make curl unzip jq
```

Docker、Go、Node、Terraform、Packer、gcloud 的安装方式可以按你自己习惯来，只要满足下面这些检查：

```bash
git --version
make --version
curl --version
jq --version
docker --version
go version
node --version
npm --version
terraform version
packer version
gcloud version
```

### 2.4 GCP 和 Cloudflare 前提

这部分你已经做过，所以这里只保留关键点。

GCP 至少需要：

- 一个可用 project
- 已启用计费
- 有足够 quota
- 当前操作者具备创建网络、实例、镜像、bucket、secret、load balancer 等权限
- `gcloud auth login` 和 `gcloud auth application-default login` 可用

Cloudflare 至少需要：

- 域名托管在 Cloudflare
- 有能改 DNS 的 API Token

### 2.5 环境文件

需要从模板准备出 `.env.dev`、`.env.staging` 或 `.env.prod` 之一。

本次部署实际使用的是：

- `.env.dev`

至少要保证这些值是正确的：

- `PROVIDER=gcp`
- `GCP_PROJECT_ID`
- `GCP_REGION`
- `GCP_ZONE`
- `DOMAIN_NAME`
- `POSTGRES_CONNECTION_STRING`
- `TERRAFORM_ENVIRONMENT`
- `PREFIX`

如果这些基础值不对，后面所有步骤都会偏掉。

## 3. 推荐的部署顺序

这部分按实际可执行顺序写，不按仓库章节顺序写。

### 3.1 切换环境

```bash
make switch-env ENV=dev
```

建议马上检查：

```bash
cat .last_used_env
```

应该看到：

```text
dev
```

### 3.2 登录 GCP

正常做法：

```bash
cd iac/provider-gcp
make provider-login
```

这一步会负责：

- 用户凭据登录
- 设置 gcloud project
- 配置 Artifact Registry Docker 登录
- 准备 ADC 给 Terraform 用

本次部署里，这一步涉及了一个代码修复，后面单独说明。

### 3.3 初始化 GCP 基础资源

```bash
cd /home/ubuntu/whz/infra/iac/provider-gcp
make init
```

如果第一次失败，直接再执行一次：

```bash
make init
```

这是有现实意义的，不是碰运气。原因是：

- 某些 GCP API 刚被启用时存在传播延迟
- Terraform 在第一次 apply `module.init` 时可能抢跑

### 3.4 同步 Secrets

```bash
make gcp-sync-secrets
```

至少要保证这些 secret 有值：

- Cloudflare token
- Postgres connection string
- Supabase JWT secrets
- 其他你启用的可选项

### 3.5 构建并上传镜像和产物

```bash
make build-and-upload
```

### 3.6 拷贝公共 Firecracker 构件

```bash
make copy-public-builds
```

### 3.7 先部署基础设施，不带 jobs

```bash
make plan-without-jobs
make apply
```

### 3.8 再部署 Nomad jobs

```bash
make plan
make apply
```

### 3.9 初始化集群基础数据

官方建议部署后执行：

```bash
cd /home/ubuntu/whz/infra/packages/shared
make prep-cluster
```

这个命令会做两件事：

1. seed 基础用户 / team / API key
2. 构建基础 `base` 模板

如果你想更可控，也可以拆开执行：

先生成 team 和 API key：

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的连接串' go run ./scripts/seed/postgres/seed-db.go
```

再构建 base 模板：

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY='刚生成的 Team API Key' DOMAIN_NAME='agentyard.top' make build-base-template
```

## 4. 本次真实执行过的关键命令

本次实际部署中用到的主命令可以压缩成这一组：

```bash
make switch-env ENV=dev
cd iac/provider-gcp
make provider-login
make init
make gcp-sync-secrets
make build-and-upload
make copy-public-builds
make plan-without-jobs
make apply
make plan
make apply
```

部署完成后的验证命令：

```bash
curl -k -I https://nomad.agentyard.top
curl -k https://api.agentyard.top/health
gcloud compute backend-services get-health e2b-backend-api --global
gcloud compute backend-services get-health e2b-backend-nomad --global
gcloud compute instance-groups managed list
gcloud compute instances list --filter='name~^e2b-'
```

## 5. 常见问题与解决办法

这部分只写本次真实碰到的和高概率会碰到的。

### 5.1 `make provider-login` 卡在交互式登录

现象：

- 部署机已经配好了 `gcloud`
- 甚至已经有 ADC
- 但执行 `make provider-login` 仍然强制弹浏览器或进入交互式登录
- 在纯服务器环境会卡住

根因：

- 原始 `iac/provider-gcp/Makefile` 的 `provider-login` 无条件执行：
  - `gcloud auth login`
  - `gcloud auth application-default login`

影响：

- 在无人值守服务器上基本不可用
- 如果 SSH 断线、没有浏览器、没有 TTY 回显，会直接中断部署

解决：

- 已修改 [iac/provider-gcp/Makefile](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile)
- 现在逻辑是：
  - 如果已有活动账号，复用现有 `gcloud` 凭据
  - 如果 ADC 已可用，复用现有 ADC
  - 只有缺失时才触发交互式登录

### 5.2 `make init` 第一次失败

现象：

- `make init` 初次执行失败
- 重试第二次成功

根因：

- GCP API enable 完成后存在传播时间
- Terraform 初始化时会先碰到资源依赖未完全可用的窗口期

解决：

```bash
make init
make init
```

如果第二次还不行，再去看具体是哪一个 GCP API 没启好。

### 5.3 API 域名返回 `503 no healthy upstream`

现象：

- `https://api.agentyard.top` 返回 `503`
- GCP backend service 显示 `UNHEALTHY`

本次真实根因：

- API 容器本身起来了
- 但 API 依赖 orchestrator
- client 节点上的 orchestrator 在第一次启动时因为 `redis.service.consul` DNS 时序问题失败退出
- Nomad 没有自动把它恢复起来

处理流程：

1. 看 API 后端健康状态

```bash
gcloud compute backend-services get-health e2b-backend-api --global
```

2. SSH 到 API 节点，检查 API 容器状态

```bash
gcloud compute ssh <api-instance> --zone=us-west1-a
curl -i http://127.0.0.1:50001/health
sudo docker ps
sudo docker logs --tail=200 <api-container>
```

3. SSH 到 client 节点，检查 orchestrator

```bash
gcloud compute ssh <client-instance> --zone=us-west1-a
curl -i http://127.0.0.1:5008/health
sudo ss -ltnp | grep 5008
sudo tail -n 200 /opt/nomad/data/alloc/*/alloc/logs/start.stdout.0
sudo tail -n 200 /opt/nomad/data/alloc/*/alloc/logs/start.stderr.0
```

4. 如果 orchestrator 是失败退出且不重启，做 purge 后重新 apply

```bash
make plan
make apply
```

必要时先在 Nomad server 上执行：

```bash
nomad job stop -purge -yes orchestrator-dev
```

再回到 Terraform：

```bash
make plan
make apply
```

### 5.4 `api` 不是 `200`，但也不是 `503`

如果根路径：

```bash
curl -I https://api.agentyard.top
```

返回 `404`，不要立刻认为挂了。

在这套架构里：

- `404` 往往说明 LB 已经把流量正确转发到了健康 API
- `503` 才更像后端不可用

更准确的检查方式应该是：

```bash
curl https://api.agentyard.top/health
```

### 5.5 模板存在但新 team 用不了

现象：

- 数据库里看得到模板 alias，比如 `base`
- 但新生成 team 用这个模板创建 sandbox 时返回 `403` 或 `404`

原因：

- 模板和 team 是有权限边界的
- 旧 alias 可能属于历史 team
- 新 team 不自动拥有它的访问权限

解决：

- 不要假设“数据库里有 `base` 就人人都能用”
- 最稳妥方式是用当前 team 自己 build 一个模板再使用

## 6. 本次部署中改了哪些代码

本次部署只改了一个会影响部署流畅性的代码点。

修改文件：

- [iac/provider-gcp/Makefile](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile)

修改位置：

- `provider-login`

修改前的核心逻辑：

```make
gcloud --quiet auth login
gcloud config set project "$(GCP_PROJECT_ID)"
gcloud --quiet auth configure-docker "$(GCP_REGION)-docker.pkg.dev"
gcloud --quiet auth application-default login
```

修改后的核心逻辑：

- 已有活动 `gcloud` 账号则直接复用
- 已有可用 ADC 则直接复用
- 只有凭据缺失时才执行交互式登录

对应 diff：

```diff
-	gcloud --quiet auth login
+	@if gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then \
+		echo "Using existing gcloud user credentials"; \
+	else \
+		gcloud --quiet auth login; \
+	fi
 	gcloud config set project "$(GCP_PROJECT_ID)"
 	gcloud --quiet auth configure-docker "$(GCP_REGION)-docker.pkg.dev"
-	gcloud --quiet auth application-default login
+	@if gcloud auth application-default print-access-token >/dev/null 2>&1; then \
+		echo "Using existing application default credentials"; \
+	else \
+		gcloud --quiet auth application-default login; \
+	fi
```

## 7. 如果不改代码，可不可行

这个问题要分场景说。

### 7.1 在本地有浏览器、愿意每次交互登录

可行。

如果你是在自己的桌面机器上操作，并且：

- 能打开浏览器
- 愿意执行 `gcloud auth login`
- 愿意执行 `gcloud auth application-default login`

那么即使不改 `provider-login`，理论上也能继续部署。

也就是说：

- 原代码不是“逻辑错误到完全不能部署”
- 它更像“对服务器部署场景不友好”

### 7.2 在远程 Linux 服务器、无浏览器、想无人值守

基本不可行，或者说非常不稳。

原因：

- 原 `provider-login` 强制走交互式登录
- 会忽略你已经存在的有效 `gcloud` 凭据和 ADC
- 在 SSH 会话、无浏览器或断线情况下很容易直接卡死

本次部署就是这个场景，所以这处代码修改对“服务器上稳定部署”来说是必须的。

### 7.3 这次另一个故障是否需要改代码

另一个实际问题是 orchestrator 首次启动时因为 Consul / Redis DNS 时序失败。

这次没有改代码解决它，而是通过运维手段恢复：

- purge 失败 job
- 重新 apply

所以结论是：

- `provider-login` 的改动是部署层面建议保留的代码修复
- orchestrator 的故障本次没有形成代码补丁，只形成了排障流程

## 8. 我建议你保留的部署文档用法

实际再次部署时，我建议这样执行：

1. 检查工具链和 `.env.dev`
2. `make switch-env ENV=dev`
3. 进入 `iac/provider-gcp`
4. `make provider-login`
5. `make init`
6. `make gcp-sync-secrets`
7. `make build-and-upload`
8. `make copy-public-builds`
9. `make plan-without-jobs && make apply`
10. `make plan && make apply`
11. 验证 `nomad`、`api/health`
12. 若需初始化使用数据，执行 `make prep-cluster`
13. 最后用 sandbox smoke test 做端到端验收

## 9. 最终建议

如果你以后还会在服务器上重复部署这套系统，我建议：

- 保留 [iac/provider-gcp/Makefile](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 的 `provider-login` 修复
- 把本文作为主部署手册使用
- 每次部署后都补跑一次 sandbox 端到端 smoke test，而不是只看 `health`

本次部署证明：

- 基础设施可以成功拉起
- API / Nomad 可以对外工作
- 真实 sandbox 生命周期也已经通过 Python smoke test 验证
