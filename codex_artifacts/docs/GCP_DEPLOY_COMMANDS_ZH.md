# GCP 部署命令说明

这份文档说明当前仓库里常用的 GCP 部署命令分别做了什么、为什么要这么执行，以及它们在代码里是怎么实现的。

## 1. 整体结论

这套部署不是一个单体 `sh` 直接把所有事情硬编码做完，而是分成三层：

- 根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile)
- GCP Terraform 层 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile)
- 一键脚本 [`scripts/deploy-gcp.sh`](/home/ubuntu/whz/infra/scripts/deploy-gcp.sh)

可以把它理解成：

- 根目录 `Makefile` 负责统一入口
- `iac/provider-gcp/Makefile` 负责真正执行 Terraform / GCP 初始化
- `deploy-gcp.sh` 负责把整个流程串起来

## 2. 环境是怎么选中的

当前环境通过根目录的 [`.last_used_env`](/home/ubuntu/whz/infra/.last_used_env) 决定。  
根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile) 会读取：

- `.last_used_env`
- 对应的 `.env.<env>`

例如：

- `dev` 对应 [`.env.dev`](/home/ubuntu/whz/infra/.env.dev)
- `staging` 对应 `.env.staging`
- `prod` 对应 `.env.prod`

所以你修改服务器参数时，主入口就是 `.env.dev`。

---

## 3. `make switch-env ENV=dev`

### 命令含义

切换当前部署环境，让后续所有命令都基于 `dev` 环境运行。

### 实际做的事情

根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile) 里：

- 把 `dev` 写入 [`.last_used_env`](/home/ubuntu/whz/infra/.last_used_env)
- 让 `iac/provider-gcp` 重新执行 Terraform backend 切换

对应目标：

- [`Makefile`](/home/ubuntu/whz/infra/Makefile) 中的 `switch-env`
- [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 中的 `switch`

### 技术实现

本质上会触发：

```bash
terraform init -input=false -upgrade -reconfigure -backend-config=bucket=$(TERRAFORM_STATE_BUCKET)
```

也就是重新绑定 Terraform state bucket，确保当前环境的状态文件和变量上下文一致。

### 你要怎么理解

这个命令不是部署资源，而是“选环境 + 切换 Terraform backend”。

---

## 4. `make provider-login`

### 命令含义

登录 GCP，并配置 Docker / Terraform 访问 GCP 所需的认证。

### 实际做的事情

在 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 中，`provider-login` 会：

- 检查是否已有 `gcloud auth login`
- 设置当前 GCP project
- 配置 Docker 推送到 GCP Artifact Registry
- 检查是否已有 `application default credentials`

实际调用：

- `gcloud auth login`
- `gcloud config set project`
- `gcloud auth configure-docker`
- `gcloud auth application-default login`

### 技术作用

这里有两类身份：

- `gcloud` 用户登录
  - 给 Docker、Packer、CLI 用
- `application default credentials`
  - 给 Terraform provider 用

如果这一步没完成，后面很容易在：

- Terraform
- GCP bucket
- Secret Manager
- Artifact Registry

这些地方报认证错误。

---

## 5. `make init`

### 命令含义

初始化 GCP 基础设施和 Terraform 执行环境。

### 实际做的事情

根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile) 的 `init` 会先执行：

- [`scripts/confirm.sh`](/home/ubuntu/whz/infra/scripts/confirm.sh)  
  用来确认当前环境，防止误操作

然后进入 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 的 `init`，主要做这些事：

1. 创建 Terraform state bucket
2. 给 state bucket 开启 versioning
3. 配置 lifecycle rule，清理旧 state 对象
4. 执行 `terraform init`
5. 先 `apply -target=module.init`
6. 构建 Nomad cluster disk image
7. 配置 GCP Artifact Registry 的 Docker 登录

### 技术实现重点

它不是一次性把所有资源全建完，而是先只打 `module.init`：

```bash
terraform apply -target=module.init
```

原因是 `module.init` 负责准备很多“后续部署的前置条件”，例如：

- Secret Manager secret
- bucket
- 基础 API
- 一些 GCP 基础资源

然后它还会调用：

- [`nomad-cluster-disk-image`](/home/ubuntu/whz/infra/iac/provider-gcp/nomad-cluster-disk-image)

这里通常会跑 `packer` 构建镜像，所以你之前看到的：

```bash
apt-get update
install ca-certificates curl
download docker gpg
```

那一段其实是正常的镜像构建过程，不一定是错误。

### 你要怎么理解

`make init` 负责把“Terraform 运行环境 + 基础 GCP 资源 + 基础镜像”准备好。  
它不是最终部署完成，但它是后面所有 `plan/apply` 的前提。

---

## 6. `make gcp-sync-secrets`

### 命令含义

把 `.env.dev` 中的配置同步到 GCP Secret Manager。

### 实际做的事情

执行的是：

- [`scripts/gcp-sync-secrets.sh`](/home/ubuntu/whz/infra/scripts/gcp-sync-secrets.sh)

这个脚本会读取：

- [`.env.dev`](/home/ubuntu/whz/infra/.env.dev)

然后把值写到 GCP Secret Manager 对应 secret version 中，例如：

- `postgres-connection-string`
- `cloudflare-api-token`
- `grafana-otlp-url`
- `grafana-username`
- `grafana-otel-collector-token`

### 技术作用

Terraform / Nomad 不会直接去读你的 `.env.dev` 文件；它们最终依赖的是 GCP Secret Manager 里的值。  
所以这一步是把“本地环境配置”变成“云上可读取的 secret”。

---

## 7. `make build-and-upload`

### 命令含义

构建 E2B 相关服务镜像，并上传到 GCP Artifact Registry。

### 实际做的事情

根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile) 里，这个目标会分别进入各个 package 执行构建，例如：

- `api`
- `client-proxy`
- `dashboard-api`
- `docker-reverse-proxy`
- `orchestrator`
- `template-manager`
- `envd`
- `clickhouse-migrator`

### 技术作用

后面 Nomad job 部署时，需要这些镜像已经存在于镜像仓库中。  
如果你跳过这一步，很多服务即使 Terraform 建好基础设施，也可能因为镜像不存在而起不来。

---

## 8. `make copy-public-builds`

### 命令含义

把官方公开提供的 Firecracker / kernel 构建产物复制到你自己的 GCP bucket。

### 实际做的事情

GCP 分支下执行的是：

```bash
gsutil cp -r gs://e2b-prod-public-builds/kernels/* gs://$(GCP_BUCKET_PREFIX)fc-kernels/
gsutil cp -r gs://e2b-prod-public-builds/firecrackers/* gs://$(GCP_BUCKET_PREFIX)fc-versions/
```

### 技术作用

E2B 的 sandbox 运行依赖这些 Firecracker / kernel 构件。  
这一步相当于把运行 sandbox 的底层二进制资产同步到你自己的存储中。

---

## 9. `make plan-without-jobs`

### 命令含义

先规划并部署“非 Nomad job”基础设施。

### 实际做的事情

在 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 中，这个命令会：

- 从 `main.tf` 中找出所有 module
- 排除 `module.nomad`
- 只对剩下的基础设施模块做 `terraform plan`

也就是先部署：

- 网络
- 负载均衡
- instance groups
- bucket
- disk
- 其他底层资源

但先不部署 Nomad 上的应用 job。

### 技术作用

这是两阶段部署的关键：

- 第一阶段：基础设施先起来
- 第二阶段：Nomad jobs 再部署

这样做的原因是：

- 先让 cluster、network、LB、instances 稳定
- 避免所有东西一次性上，失败时不容易定位问题

---

## 10. `make plan`

### 命令含义

生成当前 Terraform 变更计划，并保存为 `.tfplan.<env>` 文件。

### 实际做的事情

在 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 中，它会：

1. 先做 `terraform fmt -recursive`
2. 把 `.env.dev` 中的变量映射为 `TF_VAR_*`
3. 执行：

```bash
terraform plan -out=.tfplan.dev
```

### 技术实现重点

这里最关键的是 `tf_vars` 这组变量映射。  
也就是 `.env.dev` 中这些值：

- `SERVER_MACHINE_TYPE`
- `SERVER_CLUSTER_SIZE`
- `API_MACHINE_TYPE`
- `API_CLUSTER_SIZE`
- `BUILD_CLUSTERS_CONFIG`
- `CLIENT_CLUSTERS_CONFIG`

会被转成：

- `TF_VAR_server_machine_type`
- `TF_VAR_server_cluster_size`
- `TF_VAR_api_machine_type`
- `TF_VAR_api_cluster_size`
- `TF_VAR_build_clusters_config`
- `TF_VAR_client_clusters_config`

最终被 Terraform 的 variables 读取。

### 你要怎么理解

`make plan` 不会真正修改云上资源，它只是：

- 读取当前 state
- 读取当前 `.env.dev`
- 计算“将要发生什么”
- 把结果保存成 `.tfplan.dev`

---

## 11. `make apply`

### 命令含义

执行上一步 `make plan` 生成的 Terraform 计划。

### 实际做的事情

根目录 [`Makefile`](/home/ubuntu/whz/infra/Makefile) 会先调用：

- [`scripts/confirm.sh`](/home/ubuntu/whz/infra/scripts/confirm.sh)

然后进入 [`iac/provider-gcp/Makefile`](/home/ubuntu/whz/infra/iac/provider-gcp/Makefile) 的 `apply`：

```bash
terraform apply .tfplan.dev
```

执行完成后，它会删除：

- `.tfplan.dev`

### 为什么你会遇到 `Saved plan is stale`

这是因为：

- `plan` 是根据旧 state 生成的
- 中间如果有一次失败的 apply 或别人改了 state
- 原来的 `.tfplan.dev` 就失效了

这时要重新：

```bash
make plan
make apply
```

### 你要怎么理解

`apply` 本身不重新计算变更，它只是执行已有计划。  
所以它依赖 `plan` 必须是最新的。

---

## 12. `./scripts/deploy-gcp.sh dev`

### 命令含义

这是“一键部署 GCP”的总脚本。

### 实际做的事情

[`scripts/deploy-gcp.sh`](/home/ubuntu/whz/infra/scripts/deploy-gcp.sh) 会按顺序执行：

1. `make switch-env ENV=dev`
2. `make provider-login`
3. `make init`
4. `scripts/gcp-sync-secrets.sh dev`
5. `make build-and-upload`
6. `make copy-public-builds`
7. `make plan-without-jobs`
8. `make apply`
9. `make plan`
10. `make apply`

### 技术作用

它其实就是把文档里的人工步骤串起来，不是新的部署逻辑。  
它适合第一次完整部署，或者你已经确认所有配置都正确，想按标准流程一次跑完。

### 可选跳过项

这个脚本支持通过环境变量跳过部分步骤：

- `SKIP_SECRET_SYNC=true`
- `SKIP_BUILD=true`
- `SKIP_PUBLIC_BUILDS=true`

例如：

```bash
SKIP_BUILD=true ./scripts/deploy-gcp.sh dev
```

---

## 13. 推荐理解方式

你可以把这些命令分成 4 类：

### A. 环境切换类

- `make switch-env ENV=dev`

作用：
- 选择部署环境
- 切换 Terraform backend

### B. 初始化类

- `make provider-login`
- `make init`
- `make gcp-sync-secrets`

作用：
- 登录云账号
- 初始化 Terraform 和 GCP 基础资源
- 同步 secrets

### C. 构建类

- `make build-and-upload`
- `make copy-public-builds`

作用：
- 上传业务镜像
- 准备 Firecracker / kernel 构件

### D. 部署类

- `make plan-without-jobs`
- `make apply`
- `make plan`
- `make apply`

作用：
- 先上基础设施
- 再上 Nomad jobs

---

## 14. 你现在最常用的实际顺序

如果是手工一步步部署，最常见顺序就是：

```bash
make switch-env ENV=dev
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

如果中间 `apply` 失败了：

- 不要直接继续 `make apply`
- 先重新 `make plan`
- 再 `make apply`

因为旧 plan 很可能已经失效。

---

## 15. 你最需要记住的几个点

- `.env.dev` 决定的是部署参数，不是数据库里的 team limits
- `make plan` 只生成计划，不真正改资源
- `make apply` 只执行计划文件，不重新计算
- `Saved plan is stale` 说明要重新 `plan`
- `deploy-gcp.sh` 只是把标准步骤串起来
- `plan-without-jobs -> apply -> plan -> apply` 是这套仓库当前的标准两阶段部署方式

