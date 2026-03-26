# ClickHouse 与 Team Limits 说明

这份文档回答两个问题：

1. ClickHouse 服务器现在能不能先忽略
2. 如何查看和调整 team 的模板上限与 sandbox 上限

## 1. ClickHouse 现在能不能先忽略

可以。

在你当前这套 4 节点目标里，ClickHouse 可以先不部署。当前 `dev` 配置里已经写成：

- `CLICKHOUSE_CLUSTER_SIZE=0`

这表示：

- 不创建 ClickHouse 节点
- 不部署 ClickHouse 作业

这样做的影响主要是：

- 分析类数据会弱一些
- 某些 metrics / analytics / dashboard 能力不完整
- 但不影响你先部署核心 E2B 服务并测试 sandbox 并发

所以如果你当前目标是：

- 先把 E2B 跑起来
- 先测 sandbox 并发

那么 ClickHouse 完全可以暂时忽略。

## 2. Team 的模板上限和 sandbox 上限在哪里

这些不是在 `.env.dev` 配的，而是在数据库里的 team limits / tier 体系里控制的。

核心相关字段有：

- `concurrent_sandboxes`
- `concurrent_template_builds`
- `max_vcpu`
- `max_ram_mb`
- `disk_mb`
- `max_length_hours`

可以这样理解：

- `concurrent_sandboxes`
  - 一个 team 最多同时运行多少个 sandbox
- `concurrent_template_builds`
  - 一个 team 最多同时跑多少个模板构建
- `max_vcpu`
  - 模板/沙箱允许的最大 CPU
- `max_ram_mb`
  - 模板/沙箱允许的最大内存
- `disk_mb`
  - 模板/沙箱允许的最大磁盘
- `max_length_hours`
  - 单个 sandbox 最大持续时长

## 3. 代码里哪些地方会用到这些 limits

### 3.1 sandbox 并发上限

API 创建 sandbox 时会先检查 team 的并发限制：

- [`packages/api/internal/orchestrator/create_instance.go`](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/create_instance.go:100)

这里会读：

- `team.Limits.SandboxConcurrency`

如果超了，就直接返回 429。

### 3.2 模板 CPU / 内存上限

模板构建时会校验 CPU 和内存是否超过 team limit：

- [`packages/api/internal/team/limits.go`](/home/ubuntu/whz/infra/packages/api/internal/team/limits.go:10)

这里会检查：

- `MaxVcpu`
- `MaxRamMb`

### 3.3 team limits 实际从哪里读

team 的 limit 是从数据库查询里读出来的：

- [`packages/db/pkg/auth/queries/get_team.sql.go`](/home/ubuntu/whz/infra/packages/db/pkg/auth/queries/get_team.sql.go:15)

这里包含：

- `concurrent_sandboxes`
- `concurrent_template_builds`
- `max_vcpu`
- `max_ram_mb`
- `disk_mb`

## 4. 如何查看当前 team limit

最直接的方法就是查数据库。

### 4.1 查某个 team 当前绑定的 tier 和 limits

```sql
select
  t.id,
  t.name,
  t.slug,
  t.tier,
  tier.concurrent_instances as concurrent_sandboxes,
  tier.concurrent_template_builds,
  tier.max_vcpu,
  tier.max_ram_mb,
  tier.disk_mb,
  tier.max_length_hours
from public.teams t
join public.tiers tier on t.tier = tier.id
where t.slug = '你的-team-slug';
```

注意：

- 有些环境里实际 API 读的是叠加 addon 之后的结果
- 如果后续启用了 addons，最终值可能不只是 tier 原始值

### 4.2 查默认 tier 当前值

如果你当前团队用的是默认 `base_v1`，直接查：

```sql
select
  id,
  name,
  concurrent_instances as concurrent_sandboxes,
  concurrent_template_builds,
  max_vcpu,
  max_ram_mb,
  disk_mb,
  max_length_hours
from public.tiers
where id = 'base_v1';
```

## 5. 如何调整 team 的 sandbox 上限

如果你只是想快速改某个 team 的 tier 资源，最简单有两种方式。

### 方式 A：直接修改 tier

如果这个环境里只有你自己在用，直接改 tier 最省事。

例如把 `base_v1` 改大：

```sql
update public.tiers
set
  concurrent_instances = 100,
  concurrent_template_builds = 10,
  max_vcpu = 8,
  max_ram_mb = 8192,
  disk_mb = 20480,
  max_length_hours = 6
where id = 'base_v1';
```

这里的对应关系是：

- `concurrent_instances` = sandbox 并发上限
- `concurrent_template_builds` = 模板并发上限
- `max_vcpu` = 模板/沙箱 CPU 上限
- `max_ram_mb` = 模板/沙箱内存上限
- `disk_mb` = 模板/沙箱磁盘上限

### 方式 B：给某个 team 换 tier

如果你不想影响所有 `base_v1` 用户，可以新建一个 tier，然后把某个 team 指过去。

例如：

```sql
insert into public.tiers (
  id,
  name,
  vcpu,
  ram_mb,
  disk_mb,
  concurrent_instances,
  max_length_hours,
  concurrent_template_builds,
  max_vcpu,
  max_ram_mb
) values (
  'load_test_v1',
  'Load Test Tier',
  2,
  512,
  20480,
  100,
  6,
  10,
  8,
  8192
);
```

然后把 team 指到这个 tier：

```sql
update public.teams
set tier = 'load_test_v1'
where slug = '你的-team-slug';
```

这种方式更干净，适合压测环境。

## 6. 还有一个 addons 体系

如果后面你启用了 addons，那么 team 的最终 limits 还会叠加：

- `extra_concurrent_sandboxes`
- `extra_concurrent_template_builds`
- `extra_max_vcpu`
- `extra_max_ram_mb`
- `extra_disk_mb`

相关迁移在：

- [`packages/db/migrations/20251011200438_create_addons_table.sql`](/home/ubuntu/whz/infra/packages/db/migrations/20251011200438_create_addons_table.sql:11)

这意味着：

- `tiers` 是基础值
- `addons` 是附加值

不过如果你当前只是自己部署、自己压测，通常直接改 `tiers` 就够了。

## 7. 推荐你优先改哪些项

如果你的目标是压测 sandbox 并发，优先看这几个：

- `concurrent_instances`
- `max_vcpu`
- `max_ram_mb`
- `disk_mb`

如果你的目标是压测模板构建能力，再重点看：

- `concurrent_template_builds`

## 8. 推荐做法

如果你现在是自己部署、自己测试，建议这样做：

1. ClickHouse 先关闭
2. 新建一个专门的 `load_test_v1` tier
3. 把测试 team 指到这个 tier
4. 只调这个 team 的 limit，不去污染默认 tier

这样后面回滚也简单。

## 9. 当前结论

- ClickHouse 现在可以先忽略
- Team 模板上限和 sandbox 上限不在 `.env.dev`
- 它们在数据库的 `tiers` / `teams` / team limit 查询逻辑里
- 最简单的调整方法是直接改 `tiers`
- 更推荐的调整方法是新建一个专门给压测用的 tier
