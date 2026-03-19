# Supabase 管理员查询手册

这份文档面向你当前这套 self-hosted E2B 的管理员，目标是回答这些问题：

- 现在数据库里有哪些模板
- 每个模板的 `template_id` 是什么
- 哪些 alias 指向哪些模板
- 模板属于哪个 team
- 模板最近一次 build 是否成功
- 当前有没有模板还在构建
- 某个 team 有哪些 API key

这份文档默认你使用的是：

- Supabase 提供的 PostgreSQL
- 并且你的 self-hosted E2B 元数据就是写在这套库里

也就是说，这里讲的“在 Supabase 里看”，本质上是：

- 在 Supabase 的 SQL Editor 里查数据库表

---

## 1. 先理解你在 Supabase 里看到的是什么

Supabase 在你这套 self-hosted E2B 里主要扮演：

- PostgreSQL 数据库提供方

所以你在 Supabase 里看到的不是某个单独的 E2B 后台界面，而是 E2B 实际落库的数据。

这些数据包括：

- 用户
- teams
- API key 元数据
- 模板
- 模板别名
- 模板 build 记录
- sandbox 相关信息

你最关心模板时，重点通常是这几张表：

- `public.envs`
- `public.env_aliases`
- `public.env_builds`
- `public.env_build_assignments`
- `public.active_template_builds`
- `public.teams`
- `public.team_api_keys`
- `public.users_teams`

---

## 2. 最重要的表分别是干什么的

### 2.1 `public.envs`

这是模板主表。

可以把它理解成：

- “模板本体”

这里一条记录通常就是一个模板。

重点字段：

- `id`
  - 模板 ID，也就是你平时说的 `template_id`
- `team_id`
  - 模板归属哪个 team
- `source`
  - 类型来源，常见是 `template` 或 `snapshot_template`
- `created_at`
  - 创建时间
- `build_count`
  - 构建过多少次
- `spawn_count`
  - 被启动过多少次
- `last_spawned_at`
  - 最近一次被用来启动 sandbox 的时间

### 2.2 `public.env_aliases`

这是模板别名表。

可以把它理解成：

- “模板的人类可读名字”

比如：

- `base`
- `code-interpreter`
- 你自己生成的 alias

重点字段：

- `alias`
  - 别名本身
- `env_id`
  - 指向的模板 ID
- `namespace`
  - 命名空间，通常和 team slug 有关
- `is_renamable`
  - 是否允许重命名

### 2.3 `public.env_builds`

这是模板构建记录表。

可以把它理解成：

- “每次 build 模板时的执行记录”

重点字段：

- `id`
  - build ID
- `env_id`
  - 对应哪个模板
- `status`
  - 当前状态
- `status_group`
  - 状态分组，通常更适合管理员判断 build 是否 ready / failed
- `start_cmd`
  - 模板启动命令
- `ready_cmd`
  - 模板 ready 检查命令
- `vcpu`
  - CPU 配置
- `ram_mb`
  - 内存配置
- `created_at`
  - build 开始时间
- `finished_at`
  - build 结束时间
- `envd_version`
  - envd 版本

### 2.4 `public.env_build_assignments`

这是模板和 build 的关联表。

可以把它理解成：

- “某个模板当前默认使用哪次 build”

重点字段：

- `env_id`
  - 模板 ID
- `build_id`
  - build ID
- `tag`
  - 常见会用 `default`

### 2.5 `public.active_template_builds`

这是“当前仍在构建中”的模板 build 跟踪表。

如果你怀疑 build 卡住，这张表很有用。

### 2.6 `public.teams`

这是 team 表。

你要看：

- 某个模板属于哪个 team
- 某个 key 属于哪个 team

最终都要落到这里。

重点字段：

- `id`
- `name`
- `slug`
- `email`
- `created_at`

### 2.7 `public.team_api_keys`

这是 team API key 表。

注意：

- 现在一般不会直接保留完整明文 key
- 更常见是 hash、prefix、mask 这些元数据

重点字段：

- `team_id`
- `name`
- `api_key_prefix`
- `api_key_mask_prefix`
- `api_key_mask_suffix`
- `created_at`

### 2.8 `public.users_teams`

这是用户和 team 的关系表。

当你要回答“某个用户属于哪个 team”时要看它。

---

## 3. 管理员最常用的查询

下面这些 SQL 都可以直接放到 Supabase SQL Editor 里执行。

---

## 4. 查看当前所有模板

这个查询适合回答：

- 目前总共有多少模板
- 每个模板的 `template_id` 是什么
- 属于哪个 team

```sql
select
  e.id as template_id,
  e.team_id,
  e.source,
  e.created_at,
  e.build_count,
  e.spawn_count,
  e.last_spawned_at
from public.envs e
where e.source in ('template', 'snapshot_template')
order by e.created_at desc;
```

你看这条结果时，重点关注：

- `template_id`
- `team_id`
- `source`
- `spawn_count`

如果一个模板：

- `spawn_count > 0`

说明它至少被实际用来启动过 sandbox。

---

## 5. 查看模板 alias 和对应的模板 ID

这个查询最适合回答：

- `base` 对应哪个模板
- `code-interpreter` 对应哪个模板
- 某个 alias 属于哪个 team

```sql
select
  ea.alias,
  ea.namespace,
  ea.env_id as template_id,
  ea.is_renamable,
  e.team_id,
  e.created_at
from public.env_aliases ea
join public.envs e on e.id = ea.env_id
where e.source in ('template', 'snapshot_template')
order by e.created_at desc, ea.alias asc;
```

你看这条结果时，重点关注：

- `alias`
- `namespace`
- `template_id`
- `team_id`

实际管理员常见用途：

- 确认 `base` 是否真的存在
- 确认 `base` 属于哪个 team
- 确认你当前构建出来的新 alias 指向哪个模板

---

## 6. 查看每个模板最新一次 build 状态

这是管理员最值得保留的一条 SQL。

它适合回答：

- 模板最近一次 build 成功没有
- build 用了多少 CPU / 内存
- `start_cmd` / `ready_cmd` 是什么

```sql
select
  e.id as template_id,
  e.team_id,
  ba.build_id,
  b.status,
  b.status_group,
  b.vcpu,
  b.ram_mb,
  b.start_cmd,
  b.ready_cmd,
  b.created_at,
  b.finished_at
from public.envs e
left join lateral (
  select *
  from public.env_build_assignments ba
  where ba.env_id = e.id and ba.tag = 'default'
  order by ba.created_at desc
  limit 1
) ba on true
left join public.env_builds b on b.id = ba.build_id
where e.source = 'template'
order by e.created_at desc;
```

重点关注：

- `status_group`
  - 一眼判断是不是 ready / failed
- `vcpu`
- `ram_mb`
- `start_cmd`
- `ready_cmd`

这条对排查这种问题特别有用：

- 为什么模板 build 成功但 `run_code()` 不工作
- 为什么 `49999` 没起来
- 现在模板到底是普通模板还是 code interpreter 模板

---

## 7. 查看某个 team 下有哪些模板

把 `<TEAM_ID>` 换成真实 team ID：

```sql
select
  e.id as template_id,
  e.created_at,
  e.build_count,
  e.spawn_count,
  array_remove(array_agg(ea.alias), null) as aliases
from public.envs e
left join public.env_aliases ea on ea.env_id = e.id
where e.team_id = '<TEAM_ID>'
  and e.source = 'template'
group by e.id, e.created_at, e.build_count, e.spawn_count
order by e.created_at desc;
```

这个查询适合回答：

- 某个 team 现在名下到底有哪些模板
- 每个模板有几个 alias

如果你是管理员，想确认：

- 某个 API key 对应 team 能不能访问某个模板

这条查询很有价值。

---

## 8. 查看当前有哪些模板 build 还在进行中

```sql
select
  build_id,
  team_id,
  template_id,
  created_at
from public.active_template_builds
order by created_at desc;
```

这个查询适合回答：

- 当前是否还有 build 没结束
- 哪个 team 正在 build
- 哪个模板构建卡住了

如果你怀疑：

- 模板 build 一直不返回
- 某个构建流程好像卡死了

先查这张表。

---

## 9. 查看 team 和 API key 的关系

```sql
select
  t.id as team_id,
  t.name,
  t.slug,
  k.name as api_key_name,
  k.api_key_prefix,
  k.api_key_mask_prefix,
  k.api_key_mask_suffix,
  k.created_at
from public.teams t
left join public.team_api_keys k on k.team_id = t.id
order by t.created_at desc, k.created_at desc;
```

这条适合回答：

- 某个 team 有没有 API key
- 一共有几把 key
- 哪把 key 大概是什么时候创建的

注意：

- 你通常看不到完整原始 API key
- 只能看到 prefix、mask、名称等元数据

这不是 bug，而是安全设计。

---

## 10. 查看某个用户属于哪些 team

```sql
select
  u.id as user_id,
  u.email,
  ut.team_id,
  ut.is_default,
  t.name as team_name,
  t.slug as team_slug
from auth.users u
join public.users_teams ut on ut.user_id = u.id
join public.teams t on t.id = ut.team_id
order by u.email, ut.is_default desc;
```

适合回答：

- 某个用户当前属于哪些 team
- 哪个是默认 team

---

## 11. 只看最近新建的模板

如果你刚刚 build 了模板，最想马上确认新模板 ID，可以直接用：

```sql
select
  e.id as template_id,
  e.team_id,
  e.created_at,
  ea.alias
from public.envs e
left join public.env_aliases ea on ea.env_id = e.id
where e.source = 'template'
order by e.created_at desc
limit 20;
```

适合这种场景：

- 你刚跑完 `Template.build(...)`
- 想在 Supabase 里确认模板已经落库

---

## 12. 只看最近的 build 记录

```sql
select
  b.id as build_id,
  b.env_id as template_id,
  b.status,
  b.status_group,
  b.vcpu,
  b.ram_mb,
  b.start_cmd,
  b.ready_cmd,
  b.created_at,
  b.finished_at
from public.env_builds b
order by b.created_at desc
limit 50;
```

适合这种场景：

- 你刚跑了模板 build
- 想看最近 build 的状态变化

---

## 13. 如果你要查某个具体模板的详细情况

把 `<TEMPLATE_ID>` 替换掉：

```sql
select
  e.id as template_id,
  e.team_id,
  e.source,
  e.created_at,
  e.build_count,
  e.spawn_count,
  e.last_spawned_at,
  array_remove(array_agg(ea.alias), null) as aliases
from public.envs e
left join public.env_aliases ea on ea.env_id = e.id
where e.id = '<TEMPLATE_ID>'
group by
  e.id,
  e.team_id,
  e.source,
  e.created_at,
  e.build_count,
  e.spawn_count,
  e.last_spawned_at;
```

如果你还要看它对应的 build：

```sql
select
  b.id as build_id,
  b.env_id as template_id,
  b.status,
  b.status_group,
  b.vcpu,
  b.ram_mb,
  b.start_cmd,
  b.ready_cmd,
  b.created_at,
  b.finished_at
from public.env_builds b
where b.env_id = '<TEMPLATE_ID>'
order by b.created_at desc;
```

---

## 14. 作为管理员，你最值得长期看的字段

如果你不想一开始就被表结构淹没，优先关注这些字段：

### 模板层

- `envs.id`
- `envs.team_id`
- `envs.created_at`
- `envs.spawn_count`
- `envs.last_spawned_at`

### alias 层

- `env_aliases.alias`
- `env_aliases.namespace`
- `env_aliases.env_id`

### build 层

- `env_builds.id`
- `env_builds.status_group`
- `env_builds.vcpu`
- `env_builds.ram_mb`
- `env_builds.start_cmd`
- `env_builds.ready_cmd`

### team / key 层

- `teams.id`
- `teams.name`
- `teams.slug`
- `team_api_keys.api_key_prefix`
- `team_api_keys.api_key_mask_suffix`

---

## 15. 最推荐你先保存的 3 条 SQL

如果你只想先用最少的 SQL 管理这套系统，先保存下面 3 条。

### 15.1 看模板和 ID

```sql
select
  e.id as template_id,
  e.team_id,
  e.created_at
from public.envs e
where e.source = 'template'
order by e.created_at desc;
```

### 15.2 看 alias 对应哪个模板

```sql
select
  ea.alias,
  ea.namespace,
  ea.env_id as template_id
from public.env_aliases ea
order by ea.alias asc;
```

### 15.3 看模板 build 是否成功

```sql
select
  b.id as build_id,
  b.env_id as template_id,
  b.status_group,
  b.vcpu,
  b.ram_mb,
  b.start_cmd,
  b.ready_cmd,
  b.created_at
from public.env_builds b
order by b.created_at desc
limit 50;
```

---

## 16. 最后怎么理解这些信息

如果把管理员工作压缩成最简单的一句话：

你主要是在 Supabase 里看三层信息：

- 模板本体：`envs`
- 模板名字：`env_aliases`
- 模板构建结果：`env_builds`

再加上 team 和 key 关系：

- `teams`
- `team_api_keys`

这样你就能回答大部分问题：

- 现在有几个模板
- 这些模板 ID 分别是什么
- `base` 到底指向谁
- 哪个 team 拥有哪个模板
- 最近 build 成功还是失败
- 当前有没有 build 卡住
