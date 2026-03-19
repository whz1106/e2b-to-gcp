# Supabase Team Resource Update Guide

本文说明如何在**不重新部署 E2B 服务**的情况下，直接通过数据库调整模板构建资源大小。

如果你的 `POSTGRES_CONNECTION_STRING` 指向的是 Supabase 的 Postgres，那么这些 SQL 一般就是在 **Supabase SQL Editor** 里执行。

## 结论

是的，如果你现在用的是 Supabase 托管的 Postgres，那么这类修改通常直接去 **Supabase** 里执行就可以，不需要先重部署整套服务。

原因是：

- 模板构建资源来自数据库里的 `tier/team` 配置
- 当前库里关键字段是 `max_vcpu`、`max_ram_mb`、`disk_mb`
- 某个 `team` 下的 `api key` 会继承这个 `team` 当前绑定的 `tier`
- 后续新发起的 build 会读取新的数据库值

## 你要改的就是这 3 个参数

在 `public.tiers` 里：

- `max_vcpu`: CPU 核数上限
- `max_ram_mb`: 内存上限，单位 MB
- `disk_mb`: 磁盘，单位 MB

如果你只想让**某个 team 下的 api key** 生效，不要直接改全局默认 `base_v1`，而是：

1. 新建一个专用 `tier`
2. 给这个 `tier` 设置 `max_vcpu / max_ram_mb / disk_mb`
3. 把目标 `team` 切到这个 `tier`

这样该 `team` 下已有和新创建的 `api key` 都会走这个资源配置。

## 先确认当前配置

先在 Supabase SQL Editor 执行：

```sql
SELECT id, name, max_vcpu, max_ram_mb, disk_mb, concurrent_instances, concurrent_template_builds
FROM public.tiers
ORDER BY id;
```

如果你想确认某个 team 当前用的是哪个 tier：

```sql
SELECT t.id, t.name, t.email, t.tier, tr.disk_mb
FROM public.teams t
JOIN public.tiers tr ON tr.id = t.tier
ORDER BY t.created_at DESC;
```

## 方案 1：直接把 `base_v1` 改成 8192

适合场景：

- 你想让所有使用 `base_v1` 的 team 后续都拿到更大的 build 磁盘
- 你当前只是想快速跑通验证

在 Supabase 执行：

```sql
UPDATE public.tiers
SET disk_mb = 8192
WHERE id = 'base_v1';
```

验证：

```sql
SELECT id, name, disk_mb
FROM public.tiers
WHERE id = 'base_v1';
```

### 影响

- 所有绑定 `base_v1` 的 team 后续新 build 都会受影响
- 适合快速验证
- 不适合精细化运营

## 方案 2：新建一个专用 tier，只给特定 team 用

适合场景：

- 不想影响所有 `base_v1`
- 只想让某个测试 team / 客户 team 变大

### 第一步：创建新 tier

在 Supabase 执行：

```sql
INSERT INTO public.tiers (
    id,
    name,
    disk_mb,
    concurrent_instances,
    max_length_hours,
    max_vcpu,
    max_ram_mb,
    concurrent_template_builds
  )
  VALUES (
    'team_build_2c_1g_12g',
    'Team Build 2C 1G 12G',
    12288,
    20,
    24,
    2,
    1024,
    20
  );
```

如果你想自己定大小，直接改这 3 个值：

```sql
INSERT INTO public.tiers (
  id,
  name,
  disk_mb,
  concurrent_instances,
  max_vcpu,
  max_ram_mb,
  concurrent_template_builds
)
VALUES ('team_whz_v1', 'Team WHZ tier', 8192, 20, 2, 2048, 20);
```

这里表示：

- `max_vcpu = 2`
- `max_ram_mb = 2048`
- `disk_mb = 8192`

验证：

```sql
SELECT id, name, max_vcpu, max_ram_mb, disk_mb, concurrent_template_builds
FROM public.tiers
WHERE id = 'large_build_v1';
```

### 第二步：把指定 team 切到这个 tier

如果你知道 team id：

```sql
UPDATE public.teams
SET tier = 'large_build_v1'
WHERE id = '<your-team-id>';
```

如果你只知道邮箱：

```sql
UPDATE public.teams
SET tier = 'large_build_v1'
WHERE email = '<your-email>';
```

验证：

```sql
SELECT t.id, t.name, t.email, t.tier, tr.max_vcpu, tr.max_ram_mb, tr.disk_mb
FROM public.teams t
JOIN public.tiers tr ON tr.id = t.tier
WHERE t.email = '<your-email>';
```

## 最短操作

如果你的目标只是：

- 调整 `cpu / memory / disk`
- 只让某个 `team` 下的 `api key` 生效

那就只做这 3 步。

### 1. 创建一个专用 tier

```sql
INSERT INTO public.tiers (
  id,
  name,
  disk_mb,
  concurrent_instances,
  max_vcpu,
  max_ram_mb,
  concurrent_template_builds
)
VALUES ('team_whz_v1', 'Team WHZ tier', 8192, 20, 2, 2048, 20);
```

### 2. 把目标 team 切过去

如果你知道 team 邮箱：

```sql
UPDATE public.teams
SET tier = 'team_whz_v1'
WHERE email = '<your-email>';
```

如果你知道 team id：

```sql
UPDATE public.teams
SET tier = 'team_whz_v1'
WHERE id = '<your-team-id>';
```

### 3. 验证

```sql
SELECT t.id, t.name, t.email, t.tier, tr.max_vcpu, tr.max_ram_mb, tr.disk_mb
FROM public.teams t
JOIN public.tiers tr ON tr.id = t.tier
WHERE t.email = '<your-email>';
```

查出来如果是：

- `tier = team_whz_v1`
- `max_vcpu = 2`
- `max_ram_mb = 2048`
- `disk_mb = 8192`

那这个 `team` 下的 `api key` 后续新发起的 build 就会用这组配置。

## 这和 API key 的关系

- `api key` 本身不存 `max_vcpu / max_ram_mb / disk_mb`
- `api key` 只是归属某个 `team`
- 真正的资源值看该 `team` 当前绑定的 `tier`

所以你不用去改 key，本质上是改：

`team -> tier -> max_vcpu/max_ram_mb/disk_mb`

## 方案 3：配合 `seed-db.go` 使用

当前脚本：

[seed-db.go](/home/ubuntu/whz/infra/packages/db/scripts/seed/postgres/seed-db.go)

现在这个脚本已经支持通过环境变量指定 `tier`：

- `SEED_TEAM_TIER`

这样你可以直接基于你刚创建的新 tier 来生成：

- `team`
- `access token`
- `team api key`

### 先确认你的 tier 已存在

例如你刚创建的是：

- `team_build_2c_1g_12g`

先在 Supabase 验证：

```sql
SELECT id, name, max_vcpu, max_ram_mb, disk_mb
FROM public.tiers
WHERE id = 'team_build_2c_1g_12g';
```

### 用这个 tier 创建 team 和 key

执行：

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的连接串' \
SEED_TEAM_TIER='team_build_2c_1g_12g' \
go run ./scripts/seed/postgres/seed-db.go
```

脚本会提示你输入邮箱，然后输出：

- `Team ID`
- `Team Tier`
- `Access Token`
- `Team API Key`

这里的 `Team API Key` 就是你后面给 E2B SDK 用的 `api_key`。

### 运行完成后验证

```sql
SELECT t.id, t.email, t.tier, tr.max_vcpu, tr.max_ram_mb, tr.disk_mb
FROM public.teams t
JOIN public.tiers tr ON tr.id = t.tier
WHERE t.email = '<seed 时输入的邮箱>';
```

如果结果是：

- `tier = team_build_2c_1g_12g`
- `max_vcpu = 2`
- `max_ram_mb = 1024`
- `disk_mb = 12288`

那说明这个 team 创建成功了，而且它下面生成的 `Team API Key` 已经会走这组资源限制。

### 最短结论

1. 先在 Supabase 建好你的专用 `tier`
2. 再执行：

```bash
POSTGRES_CONNECTION_STRING='你的连接串' \
SEED_TEAM_TIER='你的-tier-id' \
go run ./scripts/seed/postgres/seed-db.go
```

3. 脚本打印出来的 `Team API Key` 直接拿去用

### 兼容旧用法

如果你不传 `SEED_TEAM_TIER`，脚本默认还是：

- `base_v1`

所以分两种用法：

### 用法 A：先改 `base_v1`

如果你先在 Supabase 里把 `base_v1.disk_mb` 改成 `8192`，那么再运行：

```bash
cd /home/ubuntu/whz/infra/packages/db
POSTGRES_CONNECTION_STRING='你的连接串' go run ./scripts/seed/postgres/seed-db.go
```

新建出来的 team 会自动拿到 `8192`。

### 用法 B：不改 `base_v1`，改成专用 tier

你可以先在 Supabase 里创建 `large_build_v1`，然后：

1. 先正常运行 `seed-db.go`
2. 再在 Supabase 中执行：

```sql
UPDATE public.teams
SET tier = 'large_build_v1'
WHERE email = '<seed 时输入的邮箱>';
```

这样不用改代码，也能让这个 seed 出来的 team 用更大的 build 磁盘。

## 推荐方案

如果你现在只是为了避免重部署、尽快验证：

### 最简单

直接在 Supabase 执行：

```sql
UPDATE public.tiers
SET disk_mb = 8192
WHERE id = 'base_v1';
```

然后再跑 `seed-db.go`。

### 更稳妥

创建 `large_build_v1`，只让目标 team 使用它，不影响所有默认 team。

## 注意事项

- 这类修改通常对**后续新建的 build** 生效
- 已经开始执行的旧 build，一般不会自动变更
- 如果你改的是 `base_v1`，影响范围会比较大
- 如果你们后面要做运营化管理，建议长期使用“专用 tier”而不是频繁改默认 tier
