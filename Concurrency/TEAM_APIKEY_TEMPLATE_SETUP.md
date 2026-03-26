# Team / API Key / Template Setup

这份说明专门回答你这次并发测试前的第一个问题：

1. 如何生成新的 `team_id`
2. 如何拿到新的 `E2B_API_KEY`
3. 模板到底应该用什么

最容易混淆的一点先放前面：

- `base_v1` 是 `tier`
- `base` 才是模板 alias

也就是说：

- `base_v1` 决定这个 team 的资源上限
- `base` 决定创建 sandbox 时实际用哪个模板

它们不是一回事。

## 1. 你这次要的实际目标

为了做并发测试，你至少需要这三样：

- 一个新的 `team`
- 这个 team 下面的一把 `E2B_API_KEY`
- 这个 team 自己可访问的一个模板

最稳妥的路径是：

1. 用仓库自带 seed 脚本创建一个新 team
2. 让这个 team 的 tier 使用 `base_v1`
3. 用刚生成的 `E2B_API_KEY` 为这个 team 构建一个 alias 为 `base` 的模板
4. 并发测试时直接用这个 team 的 key 和这个 team 自己的模板

## 2. 如何生成新的 team 和 API key

仓库里已经有现成脚本：

- [seed-db.go](/home/ubuntu/whz/infra/packages/db/scripts/seed/postgres/seed-db.go)

这个脚本会自动做这些事：

- 创建一个新 `team_id`
- 创建一个新 user
- 绑定 `users_teams`
- 生成 `Access Token`
- 生成 `Team API Key`

默认情况下，它会把 team 的 `tier` 设成：

- `base_v1`

### 执行方式

先确认环境变量：

```bash
export POSTGRES_CONNECTION_STRING='你的 PostgreSQL 连接串'
export SEED_TEAM_TIER='base_v1'
postgresql://postgres.wseanpqgpdneqwcudlvl:whz1379274899@aws-1-ap-south-1.pooler.supabase.com:5432/postgres
```

然后执行：

```bash
cd /home/ubuntu/whz/infra/packages/db
go run ./scripts/seed/postgres/seed-db.go
```

脚本会提示你输入邮箱：

```text
Email: your-email@example.com
```

执行完成后会输出类似：

```text
Team ID: 12345678-1234-1234-1234-123456789abc
Team Tier: base_v1
Access Token: sk_e2b_xxx
Team API Key: e2b_xxx
```

这次并发测试最重要的是这两个：

- `Team ID`
- `Team API Key`

其中：

- `Team ID` 用来在 Supabase 里查这个 team 的配置
- `Team API Key` 用来创建模板、创建 sandbox

## 3. `base_v1` 和 `base` 的区别

这里一定要分清：

### `base_v1`

这是数据库里的 tier。

它控制的是：

- `concurrent_sandboxes`
- `concurrent_template_builds`
- `max_vcpu`
- `max_ram_mb`
- `disk_mb`

也就是“这个 team 最多能申请多大资源”。

### `base`

这是模板 alias。

它控制的是：

- sandbox 启动时用哪个模板

也就是说：

- `base_v1` 决定你最多能申请多少资源
- `base` 决定你实际拿哪个模板去起 sandbox

## 4. 如何给这个新 team 准备模板

只创建 team 和 key 还不够。

如果你直接拿一个“历史上别的 team 创建的 `base`”去用，可能会碰到：

- `403`
- `404`

更稳的做法是：

- 用你刚生成的这把 `E2B_API_KEY`
- 为这个 team 自己 build 一个 `base`

仓库里已经有现成命令：

- [packages/shared/Makefile](/home/ubuntu/whz/infra/packages/shared/Makefile)

执行：

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY='刚生成的 Team API Key' DOMAIN_NAME='agentyard.top' make build-base-template
```

这个命令会调用：

- [build.prod.ts](/home/ubuntu/whz/infra/packages/shared/scripts/build.prod.ts)

它会构建一个 alias 为：

- `base`

的模板。

所以并发测试时，你后面通常可以直接把 `E2B_TEMPLATE_ID=base` 写进 `Concurrency/.env`。

前提是：

- 这个 `base` 是你刚刚这个 team 自己创建的
- 你现在使用的 `E2B_API_KEY` 就是这个 team 的 key

如果你想更稳，也可以去后台或数据库里确认 `base` 对应的真实 `template_id`，然后直接填 `template_id`。

## 5. 推荐的最短流程

按你这次并发测试的目标，建议直接按下面做：

### 第一步：生成新 team 和新 key

```bash
cd /home/ubuntu/whz/infra/packages/db
export POSTGRES_CONNECTION_STRING='你的 PostgreSQL 连接串'
export SEED_TEAM_TIER='base_v1'
go run ./scripts/seed/postgres/seed-db.go
```

记下输出里的：

- `Team ID`
- `Team API Key`

### 第二步：给这个 team build 一个 `base`

```bash
cd /home/ubuntu/whz/infra/packages/shared
E2B_API_KEY='上一步输出的 Team API Key' DOMAIN_NAME='agentyard.top' make build-base-template
```

### 第三步：把并发测试目录的 `.env` 准备好

```bash
cat > /home/ubuntu/whz/infra/Concurrency/.env <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=上一步输出的_Team_API_Key
E2B_TEMPLATE_ID=base
EOF
```

### 第四步：开始并发测试

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv sync
uv run python run_concurrency_test.py --concurrency 2 --hold-seconds 120
```

## 6. 如何验证 team 和模板是否准备好了

### 查 team

如果你已经拿到了 `team_id`，可以去 Supabase 查：

```sql
select
  t.id,
  t.name,
  t.slug,
  t.tier,
  tr.concurrent_instances as concurrent_sandboxes,
  tr.concurrent_template_builds,
  tr.max_vcpu,
  tr.max_ram_mb,
  tr.disk_mb
from public.teams t
join public.tiers tr on tr.id = t.tier
where t.id = '你的-team-id';
```

### 查模板 alias

如果你刚 build 完 `base`，可以查：

```sql
select
  ea.alias,
  ea.env_id,
  e.team_id,
  e.created_at
from public.env_aliases ea
join public.envs e on e.id = ea.env_id
where ea.alias = 'base'
order by e.created_at desc;
```

然后确认：

- 这个 `base` 对应的 `team_id` 就是你刚生成的那个 team

## 7. 你这次测试最推荐的做法

不要复用历史 team，也不要直接赌数据库里某个旧 `base` 正好能用。

最稳的是：

1. 新建一个 team
2. 拿这个 team 的新 API key
3. 用这把 key build 这个 team 自己的 `base`
4. 用这把 key + 这个模板做并发测试

这样后面的所有问题都会更容易排查。
