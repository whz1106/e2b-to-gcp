# gcloud CLI 操作指令手册

这是一份面向日常使用的 `gcloud CLI` 中文速查手册。

适用场景：

- 登录和切换 GCP 项目
- 查看和操作 Compute Engine 虚拟机
- 管理 Cloud Storage
- 启用 GCP API
- 配置 Docker 连接 Artifact Registry
- 在服务器或部署环境中排查常见问题

说明：

- 这里优先放最常用命令
- 示例里的占位符需要替换成你自己的值
- 本手册偏实用，不追求覆盖全部子命令

---

## 1. 最常用命令速查

### 1.1 登录与认证

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth list
```

作用：

- `gcloud auth login`：登录你的 GCP 用户账号
- `gcloud auth application-default login`：生成 Application Default Credentials，很多 Terraform 和 SDK 会用到
- `gcloud auth list`：查看当前有哪些账号已登录

### 1.2 设置和查看当前项目

```bash
gcloud config set project <PROJECT_ID>
gcloud config get-value project
gcloud projects list
```

作用：

- 设置当前默认项目
- 查看当前默认项目
- 列出你可访问的项目

### 1.3 查看当前配置

```bash
gcloud config list
gcloud info
```

作用：

- `gcloud config list`：看当前 `account`、`project`、`region`、`zone` 等配置
- `gcloud info`：查看更完整的本地 gcloud 环境信息

### 1.4 查看虚拟机

```bash
gcloud compute instances list
gcloud compute instances list --zones=<ZONE>
```

作用：

- 查看当前项目下所有 Compute Engine 实例
- 或只看某个 zone 里的实例

### 1.5 SSH 进入虚拟机

```bash
gcloud compute ssh <INSTANCE_NAME> --zone=<ZONE>
```

作用：

- 直接 SSH 登录到指定 GCE 实例

### 1.6 查看存储桶

```bash
gcloud storage ls
gcloud storage ls gs://<BUCKET_NAME>
```

作用：

- 列出当前项目可见的 bucket
- 查看某个 bucket 里的对象

### 1.7 启用常用 API

```bash
gcloud services enable compute.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

作用：

- 给当前项目启用 GCP 服务 API

### 1.8 配置 Docker 连接 Google 镜像仓库

```bash
gcloud auth configure-docker
```

作用：

- 把 `gcloud` 注册成 Docker 的凭证助手
- 这样 Docker 才能推送和拉取 Google 的镜像仓库

在这个仓库里，这个命令很常用，因为构建并上传镜像时经常需要它。

---

## 2. `gcloud CLI` 到底是干什么的

`gcloud CLI` 是 Google Cloud 的官方命令行工具。

它的核心作用不是单纯“连接 GCP”，而是：

- 认证
- 配置当前项目
- 管理资源
- 调用 GCP 各类服务
- 作为很多自动化脚本的基础入口

你可以把它理解成：

- “你在命令行里操作 GCP 的总入口”

在这个仓库里，`gcloud CLI` 常用于：

- 登录 GCP
- 设置当前项目
- 生成 ADC 凭证
- 配置 Docker 登录 Google 镜像仓库
- 查看虚机、bucket、secret 等云资源

---

## 3. 登录、账号和认证

### 3.1 登录用户账号

```bash
gcloud auth login
```

用途：

- 用浏览器登录你的 Google 账号
- 给 `gcloud` 提供用户级访问凭证

适合场景：

- 你在自己的开发机或跳板机上操作 GCP

### 3.2 生成应用默认凭证 ADC

```bash
gcloud auth application-default login
```

用途：

- 生成 ADC 凭证
- Terraform、Go SDK、Python SDK、部分 Google 客户端库会自动读取它

在这个仓库里，如果你要让 Terraform 或一些上传脚本访问 GCP，这一步通常也要做。

### 3.3 查看已登录账号

```bash
gcloud auth list
```

### 3.4 切换当前使用账号

```bash
gcloud config set account <YOUR_EMAIL>
```

### 3.5 查看访问令牌

```bash
gcloud auth print-access-token
```

用途：

- 打印当前账号的访问令牌
- 某些调试或手工调用 API 时有用

---

## 4. 项目与配置管理

### 4.1 列出项目

```bash
gcloud projects list
```

### 4.2 设置默认项目

```bash
gcloud config set project <PROJECT_ID>
```

### 4.3 查看当前项目

```bash
gcloud config get-value project
```

### 4.4 查看当前账号

```bash
gcloud config get-value account
```

### 4.5 设置默认区域和可用区

```bash
gcloud config set compute/region <REGION>
gcloud config set compute/zone <ZONE>
```

例如：

```bash
gcloud config set compute/region us-west1
gcloud config set compute/zone us-west1-a
```

### 4.6 查看所有当前配置

```bash
gcloud config list
```

---

## 5. Compute Engine 常用命令

### 5.1 查看所有虚拟机

```bash
gcloud compute instances list
```

### 5.2 查看指定 zone 的虚拟机

```bash
gcloud compute instances list --zones=<ZONE>
```

### 5.3 查看单台虚拟机详情

```bash
gcloud compute instances describe <INSTANCE_NAME> --zone=<ZONE>
```

### 5.4 SSH 登录虚拟机

```bash
gcloud compute ssh <INSTANCE_NAME> --zone=<ZONE>
```

### 5.5 拷贝本地文件到虚拟机

```bash
gcloud compute scp ./local-file <INSTANCE_NAME>:~/ --zone=<ZONE>
```

### 5.6 从虚拟机拷贝文件回本地

```bash
gcloud compute scp <INSTANCE_NAME>:~/remote-file ./ --zone=<ZONE>
```

### 5.7 启动虚拟机

```bash
gcloud compute instances start <INSTANCE_NAME> --zone=<ZONE>
```

### 5.8 停止虚拟机

```bash
gcloud compute instances stop <INSTANCE_NAME> --zone=<ZONE>
```

### 5.9 删除虚拟机

```bash
gcloud compute instances delete <INSTANCE_NAME> --zone=<ZONE>
```

注意：

- 删除前确认数据是否需要保留

### 5.10 查看实例组

```bash
gcloud compute instance-groups list
```

---

## 6. Cloud Storage 常用命令

新版本里推荐使用 `gcloud storage`。

### 6.1 查看所有 bucket

```bash
gcloud storage ls
```

### 6.2 查看 bucket 内容

```bash
gcloud storage ls gs://<BUCKET_NAME>
```

### 6.3 递归查看目录

```bash
gcloud storage ls --recursive gs://<BUCKET_NAME>/<PREFIX>
```

### 6.4 上传文件

```bash
gcloud storage cp ./local-file gs://<BUCKET_NAME>/
```

### 6.5 下载文件

```bash
gcloud storage cp gs://<BUCKET_NAME>/remote-file ./
```

### 6.6 递归上传目录

```bash
gcloud storage cp --recursive ./local-dir gs://<BUCKET_NAME>/
```

### 6.7 递归下载目录

```bash
gcloud storage cp --recursive gs://<BUCKET_NAME>/remote-dir ./
```

---

## 7. 启用和查看 GCP API

很多 GCP 服务在使用前都要先启用 API。

### 7.1 查看可用服务

```bash
gcloud services list --available
```

### 7.2 查看当前已启用服务

```bash
gcloud services list --enabled
```

### 7.3 启用一个或多个服务

```bash
gcloud services enable compute.googleapis.com
gcloud services enable secretmanager.googleapis.com artifactregistry.googleapis.com
```

### 7.4 禁用服务

```bash
gcloud services disable <SERVICE_NAME>
```

在这个 E2B 仓库里，常见需要启用的服务通常包括：

- `compute.googleapis.com`
- `artifactregistry.googleapis.com`
- `secretmanager.googleapis.com`
- `certificatemanager.googleapis.com`
- `monitoring.googleapis.com`
- `logging.googleapis.com`
- `file.googleapis.com`

---

## 8. Docker / Artifact Registry 常用命令

### 8.1 配置 Docker 凭证

```bash
gcloud auth configure-docker
```

如果你只想配置指定域名，也可以写成：

```bash
gcloud auth configure-docker us-west1-docker.pkg.dev
```

作用：

- 让本机 Docker 可以认证 Google 的镜像仓库

### 8.2 查看 Artifact Registry 仓库

```bash
gcloud artifacts repositories list
```

### 8.3 查看指定区域的仓库

```bash
gcloud artifacts repositories list --location=<REGION>
```

### 8.4 查看某个仓库详情

```bash
gcloud artifacts repositories describe <REPO_NAME> --location=<REGION>
```

在这个仓库的部署过程中，构建镜像后上传到 Artifact Registry 往往依赖这一套认证流程。

---

## 9. Secret Manager 常用命令

### 9.1 查看 Secret 列表

```bash
gcloud secrets list
```

### 9.2 查看某个 Secret 详情

```bash
gcloud secrets describe <SECRET_NAME>
```

### 9.3 读取最新版本的 Secret

```bash
gcloud secrets versions access latest --secret=<SECRET_NAME>
```

### 9.4 创建 Secret

```bash
gcloud secrets create <SECRET_NAME> --replication-policy=automatic
```

### 9.5 添加一个新版本

```bash
printf 'my-secret-value' | gcloud secrets versions add <SECRET_NAME> --data-file=-
```

---

## 10. 服务账号常用命令

### 10.1 列出服务账号

```bash
gcloud iam service-accounts list
```

### 10.2 查看服务账号详情

```bash
gcloud iam service-accounts describe <SA_EMAIL>
```

### 10.3 创建服务账号

```bash
gcloud iam service-accounts create <NAME> --display-name="<DISPLAY_NAME>"
```

### 10.4 给项目授予角色

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:<SA_EMAIL>" \
  --role="roles/storage.admin"
```

---

## 11. 常用排查命令

### 11.1 查看当前账号、项目、区域

```bash
gcloud config list
```

### 11.2 查看是否拿到了 ADC

```bash
gcloud auth application-default print-access-token
```

如果能正常输出 token，说明 ADC 大概率可用。

### 11.3 查看命令帮助

```bash
gcloud help
gcloud compute instances --help
gcloud compute instances create --help
```

### 11.4 输出 JSON

```bash
gcloud compute instances list --format=json
```

### 11.5 只输出指定字段

```bash
gcloud compute instances list --format="table(name,zone,status)"
```

这个在写脚本或快速检查时很有用。

---

## 12. 在这个仓库里最可能用到的命令组合

如果你是在这个 `infra` 仓库里做 GCP 部署，最常见的一组命令通常是：

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
gcloud config set compute/region <REGION>
gcloud config set compute/zone <ZONE>
gcloud auth configure-docker
gcloud services list --enabled
```

如果你要排查机器和 bucket，常用补充命令是：

```bash
gcloud compute instances list
gcloud compute ssh <INSTANCE_NAME> --zone=<ZONE>
gcloud storage ls
gcloud storage ls gs://<BUCKET_NAME>
gcloud secrets list
```

---

## 13. 几个容易混淆的点

### 13.1 `gcloud auth login` 和 `gcloud auth application-default login` 不一样

- 前者主要给 `gcloud` 命令自己用
- 后者主要给依赖 ADC 的工具和代码用

很多时候两个都需要执行。

### 13.2 `gcloud auth configure-docker` 不是安装 Docker

这个命令只是：

- 配置 Docker 认证

它不能替代 Docker 安装本身。

### 13.3 `gcloud` 不等于 Terraform

- `gcloud`：操作和认证 GCP
- `Terraform`：定义和管理基础设施资源

它们经常一起出现，但不是同一个层面的工具。

---

## 14. 官方参考文档

以下是本手册主要参考的官方文档：

- Google Cloud CLI 安装与总文档：<https://cloud.google.com/sdk/docs/install-sdk>
- `gcloud auth login`：<https://docs.cloud.google.com/sdk/gcloud/reference/auth/login>
- `gcloud auth configure-docker`：<https://cloud.google.com/sdk/gcloud/reference/auth/configure-docker>
- `gcloud services`：<https://docs.cloud.google.com/sdk/gcloud/reference/services>
- `gcloud services enable`：<https://docs.cloud.google.com/sdk/gcloud/reference/services/enable>
- `gcloud compute instances list`：<https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/list>
- `gcloud storage ls`：<https://docs.cloud.google.com/sdk/gcloud/reference/storage/ls>
