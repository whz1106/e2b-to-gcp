# Ubuntu 新服务器依赖安装说明

这份文档面向一台刚创建好的 Ubuntu 服务器，目标是安装这个项目开发和部署所需的基础软件，并解释每个软件在这个项目里的作用。

适用前提：

- 系统：`Ubuntu 22.04` 或 `Ubuntu 24.04`
- 当前用户有 `sudo` 权限
- 默认架构：`linux_amd64`

---

## 1. 这些软件分别是做什么的

### 1.1 `git`

`git` 是版本管理工具。

在这个项目里主要用于：

- 拉取仓库代码
- 查看代码历史
- 切换分支
- 提交你自己的修改

没有 `git`，你连项目代码都拿不到。

### 1.2 `make`

`make` 是任务编排工具，可以把一串复杂命令封装成简单命令。

在这个项目里大量使用了 `Makefile`，例如：

- `make init`
- `make build-and-upload`
- `make plan`
- `make apply`
- `make local-infra`

也就是说，这个项目很多开发、部署、测试动作，都是通过 `make` 触发的。

### 1.3 `curl`

`curl` 是命令行 HTTP 请求工具。

在这个项目里主要用于：

- 下载软件安装包
- 调试 HTTP 接口
- 验证服务是否健康
- 拉取远程脚本或元数据

例如安装 `gcloud CLI`、`Docker`、`Terraform` 时都需要 `curl`。

### 1.4 `unzip`

`unzip` 用于解压 `.zip` 文件。

在这个项目里主要用于：

- 解压 Terraform 二进制包
- 解压其他工具发布包

例如 `terraform 1.5.7` 官方发布文件就是 zip 包。

### 1.5 `jq`

`jq` 是命令行 JSON 处理工具。

在这个项目里主要用于：

- 处理接口返回的 JSON
- 分析部署输出
- 在 shell 脚本里提取字段

做云资源、API、自动化脚本时，`jq` 非常常用。

### 1.6 `docker`

`docker` 是容器运行和镜像构建工具。

你可以把它理解成：

- 用来打包应用运行环境
- 用来构建镜像
- 用来运行容器化服务

在这个项目里，`docker` 主要用于：

- 构建项目各服务的镜像
- 把镜像上传到云端镜像仓库
- 本地启动一部分依赖服务
- 支撑某些构建流程

比如文档里的：

- `make build-and-upload`
- `make local-infra`

这些动作背后通常都会依赖 Docker。

注意，`docker` 不是这个项目里真正跑沙箱虚机的核心技术。  
这个项目真正的沙箱底层是 `Firecracker microVM`。  
但是在开发、构建、打包、部署阶段，Docker 仍然是非常关键的工具。

### 1.7 `node` / `npm`

`node` 是 JavaScript 运行时，`npm` 是 Node.js 的包管理器。

在这个项目里主要用于：

- 运行部分脚本
- 安装前端或构建相关依赖
- 执行一些模板构建或辅助工具链

虽然这个仓库的核心服务大多是 Go 写的，但仍有一些脚本和工具依赖 Node 环境。

### 1.8 `go`

`go` 就是 Go 编程语言的编译器和工具链。

你说得对，它本质上就是这个项目主要使用的编程语言之一，而且是最核心的后端语言。

在这个项目里，很多关键服务都是 Go 写的，例如：

- API 服务
- orchestrator
- envd
- 各类工具命令

你安装 Go 之后，才能做这些事：

- 编译项目代码
- 运行 Go 服务
- 执行 `go test`
- 运行一些仓库里的脚本或命令

例如：

- `make build/api`
- `make build/orchestrator`
- `go test ./...`

这些都依赖 Go。

### 1.9 `packer`

`packer` 是 HashiCorp 的镜像构建工具。

你可以把它理解成：

- 自动构建机器镜像
- 把一台云主机的基础环境预先做进镜像里

在这个项目里，`packer` 主要用于：

- 构建某些部署节点的系统镜像
- 预装运行环境
- 让后续新节点启动时直接带着正确基础配置

特别是在云上部署一组机器时，Packer 常用于先做出标准镜像，再批量创建实例。

### 1.10 `terraform 1.5.7`

`Terraform` 是基础设施即代码工具，简称 IaC 工具。

它的作用不是写业务代码，而是“用代码定义云资源”。

你可以把它理解成：

- 用配置文件描述云上要创建什么资源
- 然后让 Terraform 去自动创建、更新、删除这些资源

在这个项目里，Terraform 是部署基础设施的核心工具。它会负责管理诸如：

- VPC / 子网 / 网络规则
- 虚拟机实例
- 磁盘
- 负载均衡
- DNS 相关资源
- GCS / S3 bucket
- Secret Manager
- 各种云侧基础设施

这个仓库本身就是一个 infra 仓库，所以 Terraform 非常关键。

常见动作：

- `make init`
- `make plan`
- `make apply`

可以简单理解为：

- `init`：初始化 Terraform 运行环境
- `plan`：预览将要创建或修改哪些云资源
- `apply`：真正执行变更

为什么这里强调 `1.5.7`？

因为这个项目文档明确要求 Terraform `1.5.x`，并特别指出推荐 `1.5.7`。所以这里不是随便装最新版，而是固定到项目要求的版本。

### 1.11 `gcloud CLI`

`gcloud CLI` 是 Google Cloud 的命令行工具。

你理解成“用于连接 GCP”是对的，但还可以更准确一点：

它不仅是“连接”，更是“认证、配置、操作 GCP 资源”的统一命令行入口。

在这个项目里，`gcloud CLI` 主要用于：

- 登录 GCP 账号
- 设置当前 GCP project
- 获取应用默认凭证
- 配置 Docker 登录 Artifact Registry
- 执行一些 GCP 资源相关操作

例如常见命令：

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <project-id>
```

这个项目如果部署在 GCP 上，`gcloud CLI` 几乎是必装的。  
因为 Terraform、构建上传、镜像仓库认证、调试云资源，很多地方都会用到它。

---

## 2. 新建 Ubuntu 服务器后的安装命令

下面是一套比较直接、适合新机器初始化的安装流程。

## 2.1 安装基础工具

```bash
sudo apt-get update
sudo apt-get install -y \
  git \
  make \
  curl \
  unzip \
  jq \
  ca-certificates \
  gnupg \
  lsb-release \
  apt-transport-https \
  software-properties-common
```

## 2.2 安装 Docker

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$USER"
```

执行完后，建议重新登录一次终端，否则当前用户可能还不能直接执行 `docker` 命令。

## 2.3 安装 Node.js 和 npm

这里使用 NodeSource 的 LTS 版本安装方式：

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
```

## 2.4 安装 Go

这里按仓库上下文使用 `Go 1.25.4`：

```bash
GO_VERSION=1.25.4
curl -LO "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf "go${GO_VERSION}.linux-amd64.tar.gz"
echo 'export PATH=/usr/local/go/bin:$PATH' >> ~/.bashrc
export PATH=/usr/local/go/bin:$PATH
rm -f "go${GO_VERSION}.linux-amd64.tar.gz"
```

如果你后面开了新 shell，`go` 命令会通过 `~/.bashrc` 自动生效。

## 2.5 安装 Packer

```bash
curl -fsSL https://apt.releases.hashicorp.com/gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release) main" | \
sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update
sudo apt-get install -y packer
```

## 2.6 安装 Terraform 1.5.7

这个项目要求固定版本 `1.5.7`，所以这里直接安装官方发布的对应版本：

```bash
TERRAFORM_VERSION=1.5.7
curl -LO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
sudo install -m 0755 terraform /usr/local/bin/terraform
rm -f terraform "terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
```

## 2.7 安装 gcloud CLI

```bash
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" | \
  sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
sudo apt-get update
sudo apt-get install -y google-cloud-cli
```

---

## 3. 安装完成后如何验证

执行下面这些命令，确认工具都已安装成功：

```bash
git --version
make --version
curl --version
unzip -v
jq --version
docker --version
node --version
npm --version
go version
packer version
terraform version
gcloud version
```

---

## 4. 安装完成后的推荐初始化动作

### 4.1 让 Docker 普通用户可用

如果执行 `docker ps` 仍然提示权限不足，退出当前登录会话，然后重新登录一次。

### 4.2 初始化 gcloud 登录

如果你后面要部署到 GCP，至少先执行：

```bash
gcloud auth login
gcloud auth application-default login
```

如果你已经知道自己的项目 ID，也可以接着执行：

```bash
gcloud config set project <你的GCP项目ID>
```

### 4.3 拉取仓库

```bash
git clone <你的仓库地址>
cd infra
```

---

## 5. 一句话理解这几个最关键工具

- `go`：这是项目主要后端语言的编译器和工具链，用来编译、运行、测试 Go 代码。
- `docker`：用来构建镜像和运行容器，主要服务于本地依赖、镜像构建、上传部署。
- `gcloud CLI`：Google Cloud 的命令行管理工具，用来认证、设置项目、操作 GCP 资源。
- `terraform`：基础设施即代码工具，用配置文件来创建和管理 GCP / AWS 等云资源。

---

## 6. 参考来源

- Google Cloud CLI 安装文档：<https://cloud.google.com/sdk/docs/install-sdk>
- Terraform 版本说明：<https://developer.hashicorp.com/terraform/tutorials/configuration-language/versions>
- Terraform 1.5.7 发布包：<https://releases.hashicorp.com/terraform/1.5.7/>
