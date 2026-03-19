# Self-Hosted E2B 使用手册

本文面向这套已经部署到 GCP 的 self-hosted E2B 集群，重点说明：

- 用户和团队是怎么来的
- `E2B_API_KEY` 如何生成
- `E2B_TEMPLATE_ID` / 模板如何获得
- 如何从本地 Mac 使用这套系统
- 这套系统当前最稳妥的实际使用方式

本文基于当前仓库中的部署文档、数据库 seed 脚本、API 处理逻辑，以及已经在集群上跑通的 smoke test 整理。

## 1. 先理解这套 self-hosted E2B 的使用模型

要使用这套 E2B 集群，至少需要这几样东西：

- 一个用户
- 一个团队 `team`
- 该团队名下的一个 API key，也就是 `E2B_API_KEY`
- 该团队可访问的一个模板，也就是 `template`

真正调用 SDK 创建 sandbox 时，至少要有：

- `domain`，例如 `agentyard.top`
- `api_key`
- `template_id` 或模板别名

例如 Python SDK 的典型调用形态是：

```python
from e2b import Sandbox

sandbox = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="base",
)
```

## 2. “注册用户”在 self-hosted 里是什么意思

这套系统里，“注册”分两种情况。

### 2.1 你有自托管 Dashboard + Supabase 登录链路

如果你额外部署了 E2B dashboard，并且配置了 Supabase JWT secrets，那么正常的用户注册/登录流程可以存在。

根据数据库迁移逻辑，`auth.users` 新增用户时会触发 `post_user_signup()`，自动做这些事：

- 创建默认 team
- 建立 `users_teams` 关系
- 创建默认 `team_api_keys`
- 创建默认 `access_tokens`

也就是说，如果你完整接上了 dashboard 和 Supabase 登录，理论上“注册”之后会自动拥有一个默认团队和默认 key/令牌。

这个结论来自：

- [self-host.md](/home/ubuntu/whz/infra/self-host.md)
- [20240605070918_refactor_triggers_and_policies.sql](/home/ubuntu/whz/infra/packages/db/migrations/20240605070918_refactor_triggers_and_policies.sql)

### 2.2 你没有自托管 Dashboard，或者不想走登录链路

这也是目前这套 GCP 集群最实用的方式。

此时“注册用户”本质上就是：

- 手动往数据库里 seed 一个用户
- 给它创建 team
- 给 team 创建 API key
- 然后直接用这个 API key 调 SDK

仓库里已经有官方 seed 脚本：

- [seed-db.go](/home/ubuntu/whz/infra/packages/db/scripts/seed/postgres/seed-db.go)

所以对于当前环境，最稳妥的理解是：

- 如果你没有 dashboard 登录入口，就不要纠结“注册页面”
- 直接用 seed 脚本初始化一个可用用户/团队/API key 即可

## 3. 如何生成 `E2B_API_KEY`

### 3.1 推荐方式：使用仓库自带的 seed 脚本

在服务器上执行：

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的 PostgreSQL 连接串' go run ./scripts/seed/postgres/seed-db.go
```

脚本会提示你输入邮箱，例如：

```text
Email: me@example.com
```

执行完成后，会打印类似信息：

```text
Team ID: ...
Access Token: sk_e2b_...
Team API Key: e2b_...
```

其中：

- `Team API Key` 就是你要的 `E2B_API_KEY`
- `Access Token` 更偏向用户令牌，不是创建 sandbox 的首选
- 你本地跑 SDK 时，优先用 `Team API Key`

### 3.2 这个脚本实际做了什么

`seed-db.go` 会：

- 在 `auth.users` 创建一个用户
- 在 `teams` 创建一个团队
- 在 `users_teams` 绑定用户和团队
- 在 `access_tokens` 创建访问令牌
- 在 `team_api_keys` 创建团队 API key

也就是说，这不是测试脚本在“乱写库”，而是这套系统目前一个明确可用的初始化入口。

参考：

- [seed-db.go](/home/ubuntu/whz/infra/packages/db/scripts/seed/postgres/seed-db.go)

### 3.3 通过 API 创建更多 API key

当你已经有登录态和团队上下文时，API 层本身支持创建更多 team API key。

仓库里对应处理逻辑在：

- [apikey.go](/home/ubuntu/whz/infra/packages/api/internal/handlers/apikey.go)
- [apikeys.go](/home/ubuntu/whz/infra/packages/api/internal/team/apikeys.go)

也就是说：

- 第一个可用 key 常常来自 seed 或注册触发器
- 之后你可以通过 API / dashboard 再创建新的 team API key

## 4. 如何获得 `E2B_TEMPLATE_ID`

`E2B_TEMPLATE_ID` 指的是你要拿来创建 sandbox 的模板。

它的来源通常有两种：

- 你自己 build 出来的模板
- 你团队下已有的模板别名，例如 `base`

### 4.1 推荐方式：你自己构建一个模板

这套集群当前最稳妥的路径，不是依赖某个“全局共享 base 模板”，而是：

- 用你自己的 team API key
- 为你自己的 team build 一个模板
- 再用该模板创建 sandbox

原因是我们在真实集群上验证过：

- 某些旧模板别名存在于数据库里
- 但它们属于其他历史 team
- 新生成的 team 用这些模板时会遇到 `403` 或 `404`

所以，“我自己 build 自己用”是最稳的方式。

### 4.2 通过仓库脚本构建 `base` 模板

仓库里自带了基础模板构建入口：

- [packages/shared/Makefile](/home/ubuntu/whz/infra/packages/shared/Makefile)
- [build.prod.ts](/home/ubuntu/whz/infra/packages/shared/scripts/build.prod.ts)

执行方式：

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY="你的 Team API Key" DOMAIN_NAME="agentyard.top" make build-base-template
```

这个脚本会构建一个 alias 为 `base` 的模板。

实际使用时，你可以优先尝试：

```bash
export E2B_TEMPLATE_ID="base"
```

前提是：

- 这个 `base` 是你当前 team 自己创建的
- 你的 `E2B_API_KEY` 对它有访问权限

### 4.3 通过 Python SDK 直接构建临时模板

这也是我们 smoke test 最终采用的方式。

思路是：

- 先有可用 API key
- 用 Python SDK 调 `Template.build(...)`
- 构建完成后直接拿返回的 `template_id`
- 再创建 sandbox

这条路径不依赖数据库里是否已有可复用模板，最适合验证 self-hosted 集群是否真的能工作。

### 4.4 如果你使用 `e2b_code_interpreter`

如果你本地代码使用的是：

```python
from e2b_code_interpreter import Sandbox
```

那么不要默认把普通 `base` 模板直接当作 code interpreter 模板使用。

当前仓库里的默认 `base` 构建逻辑是：

- [packages/shared/scripts/template.ts](/home/ubuntu/whz/infra/packages/shared/scripts/template.ts)
- [packages/shared/scripts/build.prod.ts](/home/ubuntu/whz/infra/packages/shared/scripts/build.prod.ts)

它基于普通 `fromBaseImage()` 构建，更适合文件操作和命令执行。

如果你要让 `run_code()` 更稳定地工作，建议单独构建一个 code interpreter 模板：

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY="你的 Team API Key" DOMAIN_NAME="agentyard.top" make build-code-interpreter-template
```

这个入口会调用：

- [packages/shared/scripts/template.code-interpreter.ts](/home/ubuntu/whz/infra/packages/shared/scripts/template.code-interpreter.ts)
- [packages/shared/scripts/build.code-interpreter.ts](/home/ubuntu/whz/infra/packages/shared/scripts/build.code-interpreter.ts)

默认配置为：

- `alias=code-interpreter`
- `cpuCount=2`
- `memoryMB=1024`

如果你需要覆盖资源，可以在执行时追加：

```bash
TEMPLATE_CPU_COUNT=2 TEMPLATE_MEMORY_MB=2048
```

构建成功后会打印：

- `templateId`
- `buildId`
- `alias`

之后你本地可以优先使用：

```bash
export E2B_TEMPLATE_ID="code-interpreter"
```

或者直接使用输出里的真实 `templateId`。

## 5. 服务器管理员常用初始化流程

如果你是这套集群的管理员，推荐初始化顺序如下。

### 5.1 部署完成后先准备基础数据

官方文档里提到：

```bash
cd /home/ubuntu/whz/infra/packages/shared
make prep-cluster
```

这个命令会做两件事：

1. 调 `packages/db` 的 `seed-db`
2. 构建基础模板

参考：

- [self-host.md](/home/ubuntu/whz/infra/self-host.md)
- [packages/shared/Makefile](/home/ubuntu/whz/infra/packages/shared/Makefile)

### 5.2 更可控的做法

我更建议你拆开执行，因为这样更清楚每一步拿到了什么。

先创建用户/团队/API key：

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的 PostgreSQL 连接串' go run ./scripts/seed/postgres/seed-db.go
```

记下输出里的：

- `Team API Key`

然后 build 基础模板：

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY="刚刚输出的 Team API Key" DOMAIN_NAME="agentyard.top" make build-base-template
```

之后你就拥有了最基本的使用材料：

- `E2B_API_KEY`
- 一个你自己 team 下的 `base` 模板

## 6. 本地 Mac 如何使用这套系统

### 6.1 最小使用方式

适合你已经有：

- `E2B_API_KEY`
- 一个可访问的模板，例如 `base`

Python 例子：

```python
from e2b import Sandbox

sandbox = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="base",
    timeout=120,
)

result = sandbox.commands.run("python3 -c \"print('hello from sandbox')\"")
print(result.stdout)

sandbox.kill()
```

### 6.2 文件操作例子

```python
from e2b import Sandbox

sandbox = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="base",
)

sandbox.files.write("/tmp/demo/hello.txt", "hello\n")
print(sandbox.files.read("/tmp/demo/hello.txt"))
print([entry.name for entry in sandbox.files.list("/tmp/demo")])

sandbox.kill()
```

### 6.3 构建模板再创建 sandbox

```python
from e2b import Sandbox, Template

template = (
    Template()
    .from_ubuntu_image("22.04")
    .apt_install(["python3", "curl"])
    .set_start_cmd("sleep infinity", "python3 --version")
)

build = Template.build(
    template,
    name="my-template",
    api_key="e2b_xxx",
    domain="agentyard.top",
    cpu_count=2,
    memory_mb=1024,
)

print(build.template_id)

sandbox = Sandbox.create(
    template=build.template_id,
    api_key="e2b_xxx",
    domain="agentyard.top",
)

print(sandbox.get_info())
sandbox.kill()
```

## 7. 针对这套 GCP 集群，推荐的实际使用策略

对于当前这套环境，我建议你遵循下面的策略。

### 7.1 管理员初始化

管理员在服务器上先做一次：

1. seed 一个用户/团队/API key
2. 用这个 key build 一个 `base` 模板

### 7.2 日常开发验证

如果只是验证集群是否健康可用，优先用完整 smoke：

- [smoke_full.py](/home/ubuntu/whz/infra/tests/integration/gcp-selfhost-smoke/mac-local-kit/smoke_full.py)

它会：

- 创建临时用户/团队/API key
- 动态 build 模板
- 创建 sandbox
- 验证文件、命令、网络、后台进程、销毁

这是最接近“真实端到端可用性”的验证方式。

### 7.3 给本地开发者使用

如果你想给自己或团队成员一个稳定入口，最实用的方式是：

- 先为某个正式 team 生成稳定 `E2B_API_KEY`
- 再为这个 team 构建一个固定可用的 `base`
- 本地 SDK 调用统一写：

```bash
export E2B_DOMAIN="agentyard.top"
export E2B_API_KEY="e2b_xxx"
export E2B_TEMPLATE_ID="base"
```

这样大家的本地代码会最简单。

但前提仍然是：

- 这个 `base` 确实属于该 team
- 没有被删掉
- 你的 key 对它有权限

## 8. 推荐你优先使用哪条路径

如果你的目标是“尽快把这套 self-hosted E2B 用起来”，建议这样选：

### 路径 A：最快开始用

1. 在服务器上运行 `seed-db.go`
2. 拿到 `Team API Key`
3. 在服务器上运行 `make build-base-template`
4. 本地 Mac 用 `E2B_API_KEY + template=base` 调 SDK

适合：

- 你要长期手工使用一套固定 team
- 你想要最像正式生产使用方式的体验

### 路径 B：最快验证整套架构

1. 在本地或服务器运行 `smoke_full.py`
2. 让它自动 seed 临时团队
3. 让它自动 build 临时模板
4. 自动创建和销毁 sandbox

适合：

- 你先要确认这套部署真的能工作
- 你不想手工管理 key 和模板

## 9. 一组可直接执行的命令

### 9.1 在服务器上生成 API key

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的 PostgreSQL 连接串' go run ./scripts/seed/postgres/seed-db.go
```

### 9.2 在服务器上构建 base 模板

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY='上一步输出的 Team API Key' DOMAIN_NAME='agentyard.top' make build-base-template
```

### 9.3 在本地 Mac 跑最小调用

```bash
cd tests/integration/gcp-selfhost-smoke/mac-local-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export E2B_DOMAIN='agentyard.top'
export E2B_API_KEY='你的 Team API Key'
export E2B_TEMPLATE_ID='base'

python smoke_basic.py
```

### 9.4 在本地 Mac 跑完整链路验证

```bash
cd tests/integration/gcp-selfhost-smoke/mac-local-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cat > .env.local <<'EOF'
DOMAIN_NAME=agentyard.top
POSTGRES_CONNECTION_STRING=postgresql://...
EOF

python smoke_full.py
```

## 10. 最后的判断标准

如果你只是问“这套系统怎么真正开始用”，答案很简单：

- 没有 dashboard 登录链路时，用 `seed-db.go` 生成你的第一把 `E2B_API_KEY`
- 然后用这个 key build 一个属于你 team 的模板
- 之后本地 SDK 就能正常创建 sandbox

如果你只是问“怎样最快验证服务没问题”，那就不要手动折腾 `E2B_TEMPLATE_ID`：

- 直接跑 `smoke_full.py`
- 这是当前这套 GCP self-hosted E2B 最稳定的验证路径
