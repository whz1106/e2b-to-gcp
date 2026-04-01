# Supabase Team 资源与并发调整手册

这份文档把下面两类问题合并到一处：

- 如何直接在 Supabase 里调整某个 team 的 CPU、内存、磁盘、并发限制
- 哪些配置可以直接在 Supabase 改，哪些不应该误以为改数据库就会立即生效

适用前提：

- 你的 self-hosted E2B 元数据落在 Supabase Postgres
- 你有 Supabase SQL Editor 或等价数据库管理员权限

---

## 1. 先说结论

在当前这套 E2B 里，很多 **team 级别的资源上限** 都来自数据库，可以直接在 Supabase 调整。

最常见、最值得关注的字段有：

- `concurrent_instances`
  表示 team 的 sandbox 并发上限
- `concurrent_template_builds`
  表示 team 的模板构建并发上限
- `max_vcpu`
  表示 team 允许的单个模板/沙箱最大 CPU
- `max_ram_mb`
  表示 team 允许的单个模板/沙箱最大内存
- `disk_mb`
  表示 team 允许的单个模板/沙箱最大磁盘
- `max_length_hours`
  表示单个 sandbox 最大持续时长

这些值通常不是直接写在 `team_api_keys` 里，而是通过：

```text
team -> tier -> limits
```

来生效。

所以你最常做的不是“改 API key”，而是：

1. 查出 team 当前绑定哪个 `tier`
2. 决定是直接改这个 `tier`
3. 还是新建一个专用 `tier` 再把该 `team` 指过去

---

## 2. 哪些内容可以直接在 Supabase 改

### 2.1 可以直接改，而且通常会影响后续新请求

这类值适合直接在 Supabase 改：

- team 的 sandbox 并发上限
- team 的模板构建并发上限
- team 的最大 CPU
- team 的最大内存
- team 的最大磁盘
- team 的最大时长
- team 绑定的 `tier`

这些通常位于：

- `public.tiers`
- `public.teams`

### 2.2 可以查，但不建议把它当“资源限制主入口”

这类信息可以在 Supabase 查，但不是你日常改资源限制的主要入口：

- `team_api_keys`
- `envs`
- `env_aliases`
- `env_builds`

这些更适合：

- 查某个 team 有哪些 key
- 查模板属于哪个 team
- 查 build 是否成功

### 2.3 不要误以为在 Supabase 改了就能解决的内容

下面这些不是单靠改 Supabase 就能解决的：

- node 机器规格
- API placement 的 CPU overcommit 参数
- orchestrator 的 starting 并发窗口
- node metrics 同步周期
- Firecracker / orchestrator / envd 的运行时代码逻辑

这些属于代码、配置或基础设施层，而不是数据库层。

---

## 3. 先查当前 team 的资源配置

先查某个 team 当前绑定的 tier 和 limits：

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
  tr.disk_mb,
  tr.max_length_hours
from public.teams t
join public.tiers tr on tr.id = t.tier
where t.slug = '你的-team-slug';
```

如果你还不知道 team slug，也可以先列最近的 team：

```sql
select id, name, slug, tier, created_at
from public.teams
order by created_at desc
limit 50;
```

---

## 4. 直接修改一个已有 tier

如果这个环境里只有你自己在用，或者你确认该 tier 只服务少量测试 team，最快的做法是直接改 tier。

例如把某个 tier 改成：

- sandbox 并发 `100`
- 模板并发 `10`
- 最大 CPU `2`
- 最大内存 `2048 MB`
- 最大磁盘 `10240 MB`
- 最大时长 `6 小时`

```sql
update public.tiers
set
  concurrent_instances = 100,
  concurrent_template_builds = 10,
  max_vcpu = 2,
  max_ram_mb = 2048,
  disk_mb = 10240,
  max_length_hours = 6
where id = 'base_v1';
```

验证：

```sql
select
  id,
  name,
  concurrent_instances,
  concurrent_template_builds,
  max_vcpu,
  max_ram_mb,
  disk_mb,
  max_length_hours
from public.tiers
where id = 'base_v1';
```

### 这种方式的特点

- 优点：最快
- 风险：所有绑定这个 tier 的 team 都会受影响
- 适合：单人测试环境、临时验证

---

## 5. 给某个 team 单独提额

如果你不想影响所有 team，更推荐：

1. 新建一个专用 tier
2. 再把目标 team 切过去

### 5.1 新建专用 tier

下面是一个示例 tier：

- sandbox 并发 `100`
- 模板并发 `10`
- 最大 CPU `2`
- 最大内存 `2048 MB`
- 最大磁盘 `10240 MB`
- 最大时长 `6 小时`

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
  10240,
  100,
  6,
  10,
  2,
  2048
);
```

注意：

- `vcpu` / `ram_mb` 常是 tier 的基础规格字段
- `max_vcpu` / `max_ram_mb` / `disk_mb` 更接近你真正关心的上限控制
- 不同查询场景里你最应该盯的是：
  - `concurrent_instances`
  - `concurrent_template_builds`
  - `max_vcpu`
  - `max_ram_mb`
  - `disk_mb`

### 5.2 把 team 切到新 tier

```sql
update public.teams
set tier = 'load_test_v1'
where slug = '你的-team-slug';
```

### 5.3 验证 team 已切换成功

```sql
select
  t.id,
  t.name,
  t.slug,
  t.tier,
  tr.concurrent_instances,
  tr.concurrent_template_builds,
  tr.max_vcpu,
  tr.max_ram_mb,
  tr.disk_mb,
  tr.max_length_hours
from public.teams t
join public.tiers tr on tr.id = t.tier
where t.slug = '你的-team-slug';
```

### 这种方式的特点

- 优点：影响范围小
- 风险：几乎只影响目标 team
- 适合：压测 team、内部专用 team、客户专属 team

---

## 6. 如果你只想改磁盘

如果你当前主要卡在模板或沙箱磁盘不够，例如想把磁盘改到 `10 GB`，本质上改的是：

- `disk_mb = 10240`

例如：

```sql
update public.tiers
set disk_mb = 10240
where id = 'base_v1';
```

如果只想给某个 team 生效，不要直接改公共 tier，优先给它新建专用 tier。

---

## 7. 如何查某个 team 有哪些 API key

如果你想查 team 和 API key 的关系，可以执行：

```sql
select
  t.id as team_id,
  t.name as team_name,
  t.slug,
  k.id as key_id,
  k.name as key_name,
  k.created_at
from public.teams t
join public.team_api_keys k on k.team_id = t.id
where t.slug = '你的-team-slug'
order by k.created_at desc;
```

注意：

- API key 本身不是资源限制主入口
- 一般不要指望“改 key 就能改 CPU / 内存 / 磁盘”
- 真正生效的还是 team 绑定的 tier / limits

---

## 8. 如何查模板属于哪个 team，以及模板 build 情况

如果你要确认模板归属和最近 build 情况：

```sql
select
  e.id as template_id,
  e.team_id,
  a.alias,
  b.id as build_id,
  b.status,
  b.created_at
from public.envs e
left join public.env_aliases a on a.env_id = e.id
left join public.env_builds b on b.env_id = e.id
where e.team_id = '你的-team-id'
order by b.created_at desc nulls last;
```

这类查询适合：

- 查这个 team 到底有哪些模板
- 看 alias 指向哪个 template
- 看 build 是否成功

但它不是改 team limits 的入口。

---

## 9. 哪些调整改完后通常直接生效

通常下面这些数据库修改，会影响后续新的请求：

- 调整 `concurrent_instances`
- 调整 `concurrent_template_builds`
- 调整 `max_vcpu`
- 调整 `max_ram_mb`
- 调整 `disk_mb`
- 把 team 切到新的 tier

更稳妥的理解是：

- 对“后续新发起”的 sandbox / build 最相关
- 不要默认认为已经在运行中的旧 sandbox 会自动变规格
- 不要默认认为已经注册完成的旧 build 会自动回写成新值

---

## 10. 哪些事情需要改代码或基础设施，不是改 Supabase

如果你的目标是进一步提升整体并发、placement 稳定性或单机承载能力，下面这些通常不是改 Supabase：

- API placement 的 CPU overcommit 比例 `R`
- orchestrator 的 `maxStartingInstancesPerNode`
- node metrics 同步周期
- client VM 的机器规格
- API / orchestrator / envd 的行为逻辑

这些要么在代码里，要么在 feature flag，要么在云资源配置里。

所以不要把“team limit 不够”和“node 真正扛不住”混在一起。

---

## 11. 推荐操作策略

如果你只是临时验证：

- 直接改一个测试 tier
- 或直接改 `base_v1`

如果你要做正式压测或长期使用：

- 新建专用 tier
- 把目标 team 切到这个 tier
- 不要污染默认 tier

如果你的目标是大规模并发：

- 先在 Supabase 把 team limits 放开
- 再单独评估 node 规格、placement、starting 限制和 orchestrator 行为

---

## 12. 最小操作清单

如果你现在就要给某个 team 调整 CPU / 内存 / 磁盘 / 并发，最短流程是：

1. 查 team 当前 tier
2. 决定是直接改 tier 还是新建专用 tier
3. 修改：
   - `concurrent_instances`
   - `concurrent_template_builds`
   - `max_vcpu`
   - `max_ram_mb`
   - `disk_mb`
   - `max_length_hours`
4. 验证查询结果
5. 再发起新的 sandbox / template build 验证是否按新限制生效

如果你只需要一个典型的“1 CPU / 1024 MB / 10 GB”规格，至少要保证：

- `max_vcpu >= 1`
- `max_ram_mb >= 1024`
- `disk_mb >= 10240`

如果你还希望更高并发，再额外提高：

- `concurrent_instances`
- `concurrent_template_builds`
