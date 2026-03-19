# 这个仓库如何在 GCP 上构建 E2B 架构

这份文档的目标不是复述命令，而是把这个仓库“到底在搭什么、怎么搭起来、各组件分别干什么”讲清楚。

如果你之前对这些概念不熟，这样理解最合适：

- 这个仓库不是单一应用
- 它是在云上搭一整套“可创建沙箱虚机”的平台
- 这个平台的名字就是 `E2B`
- 这个平台的用途是给 AI Agent / 代码执行场景提供隔离的运行环境

你可以把它理解成：

“用户发一个请求过来，平台在云上找机器，启动一个隔离的微型虚拟机，把命令放进去执行，再把结果返回。”

而这个仓库，负责把完成这件事所需的所有基础设施和服务都部署出来。

---

## 1. 先用一句话理解 E2B

E2B 是一套“云上的安全代码执行平台”。

它不是简单地在 Docker 里跑命令，而是更偏向：

- 用 `Firecracker microVM` 创建轻量虚拟机
- 在虚拟机里跑用户代码
- 提供文件读写、命令执行、进程管理等能力
- 对外暴露 API 和 SDK

所以它的核心不是“网页应用”，而是“沙箱基础设施平台”。

---

## 2. 这个仓库不是只部署一个服务，而是部署一整套系统

这个仓库里包含的，主要不是业务页面，而是这些东西：

- 云资源配置
- 容器镜像构建逻辑
- 基础服务部署逻辑
- 沙箱编排逻辑
- 模板构建逻辑
- 测试和验证脚本

所以它更像：

- “平台基础设施仓库”

而不是：

- “单个后端项目”

---

## 3. 整体架构先看大图

把这套系统先粗略拆成 6 层，会比较容易懂。

### 第 1 层：外部用户 / SDK

用户不会直接操作 Firecracker，也不会直接登录虚机。

用户通常做的是：

- 调用 E2B SDK
- 或者调用平台 API
- 请求创建一个 sandbox
- 在 sandbox 里执行命令

例如：

- 创建沙箱
- 上传文件
- 运行 Python 代码
- 读取输出
- 销毁沙箱

### 第 2 层：入口层

请求先进入口层，一般包括：

- 域名
- HTTPS
- 反向代理 / ingress

这部分的作用是：

- 把公网请求安全地引到平台内部服务
- 暴露例如 `api.xxx.com`、`nomad.xxx.com` 之类的入口

### 第 3 层：API 层

API 服务对外暴露平台能力。

它负责：

- 鉴权
- 校验 API key
- 管理用户 / team / 模板 / sandbox 元数据
- 接收创建 sandbox 的请求
- 调用 orchestrator 去真正启动沙箱

可以理解为：

- “平台大脑的业务入口”

### 第 4 层：编排层 orchestrator

这是整个系统最关键的部分之一。

它负责：

- 真正调度 sandbox 的启动和销毁
- 管理 Firecracker microVM
- 管理快照、模板、rootfs、内存镜像
- 管理网络、磁盘、挂载等细节

简单说：

- API 决定“要不要创建”
- orchestrator 决定“怎么创建”

### 第 5 层：沙箱虚机层

这一层是真正跑用户代码的地方。

这里不是普通进程隔离，而是：

- Firecracker microVM

可以把它理解成：

- 比传统虚拟机更轻量
- 比普通容器隔离更强

每个 sandbox 本质上是在一台宿主机上启动出来的一个轻量虚拟机实例。

### 第 6 层：虚机内部的 envd

`envd` 是跑在 sandbox 虚机内部的一个 daemon。

它负责：

- 文件操作
- 进程操作
- 命令执行
- 与外部 SDK / 控制面通信

你可以把它理解成：

- “沙箱内部的控制代理”

用户不是直接 ssh 进虚机，而是通过 envd 提供的接口来操作沙箱。

---

## 4. 用一条请求链路理解整套系统

假设用户要运行一段 Python 代码，链路大致是这样：

1. 用户通过 SDK 请求创建一个 sandbox
2. 请求先到 `API`
3. API 检查这个用户的 `API Key`、`Team`、`Template`
4. API 调用 `orchestrator`
5. orchestrator 在某台 GCP client 节点上准备 Firecracker 所需资源
6. orchestrator 基于模板或快照启动 microVM
7. 虚机内的 `envd` 启动并准备接受命令
8. 用户通过 SDK 调用 envd 执行文件/进程/命令操作
9. 执行结果返回给用户
10. 用户结束后，sandbox 被暂停、销毁或回收

这就是这套平台的核心闭环。

---

## 5. 这个仓库在 GCP 上到底搭了哪些东西

从“云上实际资源”的角度，这个仓库主要会搭这些内容。

### 5.1 网络和基础资源

Terraform 会在 GCP 上管理这些资源：

- VPC
- 子网
- 防火墙规则
- IP / 负载均衡相关资源
- DNS 相关资源
- 存储桶
- Secret Manager

这部分是“地基”。

如果没有这些资源，后面的服务根本没地方跑。

### 5.2 计算节点

平台不是只需要一台 VM，而是一组有角色分工的机器。

通常会有：

- 控制节点
- API / ingress 节点
- client 节点
- build 节点
- 数据或监控相关节点

尤其是 client 节点最关键，因为它们负责真正运行 Firecracker microVM。

### 5.3 容器镜像仓库与构建产物

平台的多个服务会被构建成镜像或二进制，然后上传到云端。

这通常包括：

- API 镜像
- orchestrator 镜像
- client-proxy 镜像
- 其他辅助服务镜像

除此之外，还有一些不是普通镜像的构件：

- Firecracker 相关构件
- kernel
- rootfs
- 模板构建产物
- sandbox snapshot / build 数据

这些会存到存储桶或其他云端位置。

### 5.4 平台服务

部署上去之后，运行的不只是一个 API。

通常会有这些服务：

- API
- orchestrator
- client-proxy
- 日志 / 指标 / 监控组件
- 数据库相关作业
- 模板构建相关作业

这就是为什么这个仓库看起来会比普通后端仓库复杂很多。

---

## 6. 为什么这里要用 Terraform

`Terraform` 是这套系统的基础设施总控。

它解决的问题是：

- GCP 资源很多，而且互相关联
- 手工点控制台很容易错
- 以后还要重复部署、更新、回滚、迁移环境

所以仓库里用 Terraform 把这些都写成配置。

这样做的好处是：

- 环境可重复
- 资源关系清晰
- 变更可预览
- 多人协作更稳定

你可以把 Terraform 理解为：

- “负责把云上的房子、道路、水电先建好”

而不是负责具体住进去的人怎么生活。

---

## 7. 为什么这里还需要 Docker

很多人第一次看这种仓库时会疑惑：

- “既然最终跑的是 Firecracker，为什么还需要 Docker？”

答案是：

- Firecracker 是沙箱运行时
- Docker 是构建和交付工具

Docker 在这个仓库里主要用于：

- 构建服务镜像
- 运行本地依赖
- 支撑某些构建流程
- 将服务发布到云上的镜像仓库

也就是说：

- Docker 不等于 sandbox
- 但没有 Docker，很多服务镜像根本构建不出来

所以你之前碰到“服务器没管理员权限，Docker 装不上”这个问题，会直接影响整个仓库的构建和部署。

因为：

- 安装 Docker 需要系统级权限
- 配置 Docker daemon 需要系统级权限
- 把用户加入 docker 组也需要系统级权限

没有管理员权限时，Docker 这一步往往就会卡死。

---

## 8. 为什么这里要用 gcloud CLI

如果把 Terraform 看成“定义资源”的工具，那 `gcloud CLI` 就更像：

- “进入 GCP 环境并完成认证与操作的命令行入口”

它主要做这些事：

- 登录 GCP
- 设置当前 project
- 获取应用默认凭证
- 配置镜像仓库认证
- 做一些 GCP 资源相关调试

在这个仓库里，如果你要部署到 GCP，`gcloud CLI` 基本是绕不过去的。

---

## 9. 为什么这里还需要 Packer

`Packer` 是做机器镜像的。

它不是构建 Docker 镜像，而是构建“云主机镜像”。

适合的场景是：

- 你希望一台新机器启动时，就已经自带一整套基础环境

例如：

- 某些运行节点需要特定系统配置
- 某些组件需要预装依赖
- 需要统一镜像标准，方便批量起机器

所以它更像：

- “先把标准操作系统模板做好”

而 Docker 更像：

- “把应用打包成镜像”

两者不是一个层次。

---

## 10. 这个仓库在 GCP 上的部署顺序是什么

如果从实际执行顺序来理解，通常是下面这几步。

### 第一步：准备环境变量

先准备 `.env.dev`、`.env.staging` 或 `.env.prod`。

里面会有：

- GCP project
- 区域 / 可用区
- 域名
- PostgreSQL 连接串
- 各种前缀、密钥、配置项

这一步的作用是：

- 告诉整套系统“你要部署到哪里”

### 第二步：登录 GCP

通过 `gcloud` 完成：

- 账号登录
- 项目选择
- 应用默认凭证

这一步是为了让 Terraform、构建脚本、上传脚本后面都能访问 GCP。

### 第三步：初始化基础设施

执行：

- `make init`

它会开始让 Terraform 创建基础资源。

可以理解为：

- 先把云上的网络、桶、密钥容器、基础机器等准备出来

### 第四步：同步 Secrets

执行类似：

- `make gcp-sync-secrets`

把 `.env` 里的关键值同步到 GCP Secret Manager，例如：

- Cloudflare token
- Postgres 连接串
- Supabase JWT secret

这一步是为了让云上的服务启动时可以安全读到敏感配置。

### 第五步：构建并上传项目产物

执行：

- `make build-and-upload`

这一步通常会：

- 编译项目服务
- 构建镜像
- 上传镜像或二进制产物

这一步高度依赖：

- Docker
- Go
- gcloud

### 第六步：上传公共 Firecracker 构件

执行：

- `make copy-public-builds`

这一步主要处理：

- kernel
- rootfs
- Firecracker 版本相关构件

因为后面的 sandbox 启动需要这些底层材料。

### 第七步：先部署基础设施，不部署 jobs

通常会先：

- `make plan-without-jobs`
- `make apply`

目的很简单：

- 先让基础云资源稳定起来
- 不要一上来就把全部运行服务一起打上去

### 第八步：再部署 jobs

然后再：

- `make plan`
- `make apply`

这一轮会把平台服务真正部署上去。

例如：

- API
- orchestrator
- proxy
- 监控或其他后台作业

### 第九步：初始化集群内数据

最后还需要准备平台内部数据，例如：

- 初始用户
- team
- API key
- base template

这一步如果不做，服务虽然“活着”，但用户未必真的能用。

---

## 11. 部署完成后，平台是怎么真正工作的

部署完成不代表“已经自动有用户和模板可用”。

通常你还需要具备这些东西：

- 用户
- team
- API key
- template

然后用户才能：

- 用 SDK 连到你的域名
- 带着 API key 发请求
- 指定模板创建 sandbox

这也是为什么部署文档和使用文档是两回事：

- 部署文档解决“平台怎么搭起来”
- 使用文档解决“搭完后怎么真正创建 sandbox”

---

## 12. 这个仓库最容易让人混淆的几个概念

### 12.1 Docker 和 Firecracker 不是一回事

- Docker：构建和运行容器
- Firecracker：运行轻量虚拟机

在这个项目里：

- Docker 更偏构建与交付
- Firecracker 才是 sandbox 的核心运行时

### 12.2 API 和 orchestrator 不是一回事

- API：对外提供业务接口
- orchestrator：真正调度和管理沙箱

API 更像前台，orchestrator 更像后厨。

### 12.3 模板和 sandbox 不是一回事

- 模板：预先准备好的基础运行环境
- sandbox：基于模板启动出来的实际运行实例

可以类比为：

- 模板像虚机快照 / 母版
- sandbox 像从母版复制出来的运行实例

### 12.4 Terraform 和 gcloud 也不是一回事

- Terraform：定义和管理资源
- gcloud：认证、配置、直接操作 GCP

Terraform 负责“资源应该长什么样”，  
gcloud 负责“你如何进入和操作 GCP 环境”。

---

## 13. 为什么没有管理员权限时，最容易卡在 Docker

你之前提到的痛点，其实非常典型。

Docker 在 Linux 上通常需要这些权限：

- 往 `/etc/apt/` 写软件源
- 安装系统软件包
- 启动 `docker` 服务
- 修改用户组

这些几乎都需要 `sudo`。

所以如果你在一台新服务器上：

- 没有 root
- 没有 sudo
- 不能改 systemd

那你通常就会卡在：

- Docker 装不了
- Docker daemon 起不来
- 当前用户不能无 sudo 使用 docker

而一旦 Docker 卡住，后面通常还会连锁影响：

- 镜像构建
- 镜像上传
- 本地依赖运行
- 某些 make 流程

所以这不是你单独某一步做错了，而是权限前提不满足。

---

## 14. 用最直白的话总结这个仓库

如果只用一句最朴素的话来概括：

这个仓库是在 GCP 上搭一整套“可以安全创建和管理代码执行沙箱”的云平台。

它做的不是：

- 单独部署一个 Web 服务

它做的是：

- 建基础云资源
- 建机器和网络
- 构建和上传服务镜像
- 部署 API 和 orchestrator
- 准备 Firecracker 运行环境
- 让用户最终能通过 SDK 创建 sandbox

---

## 15. 如果你要继续往下理解，推荐按这个顺序读

### 先读这几份

- `README.md`
- `self-host.md`
- `DEPLOYMENT_SUMMARY_GCP_E2B.md`
- `SELF_HOSTED_E2B_USAGE_GUIDE_ZH.md`

### 再看这几个模块

- `packages/orchestrator/README.md`
- `packages/envd/README.md`
- `tests/integration/gcp-selfhost-smoke/README.md`

### 最后再去看源码

优先看：

- `packages/api`
- `packages/orchestrator`
- `packages/envd`
- `iac/provider-gcp`

---

## 16. 你可以先把它类比成什么

如果现在还觉得抽象，可以先这样类比：

- `Terraform`：施工队，先把园区、水电、道路、楼建好
- `gcloud CLI`：你进入园区、办证、配置权限的工具
- `Docker`：把每个服务打包成标准货箱
- `Nomad`：把这些货箱安排到不同机器上运行
- `API`：前台接待
- `orchestrator`：调度中心
- `Firecracker`：真正的独立小房间
- `envd`：房间里的服务员
- `template`：样板房
- `sandbox`：实际分配给用户住的房间

这样理解之后，这个仓库的大部分概念就会顺很多。
