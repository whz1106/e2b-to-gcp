# Team Disk Limit Update Guide

本文说明如何在这个仓库对应的 E2B 自托管系统里调整模板构建的磁盘大小，重点覆盖两种场景：

- 方式 2：调整某个已有 `tier`
- 方式 3：给某个已有 `team` 单独提额

## 背景

当前实现里，模板构建使用的磁盘额度本质上来自团队限制 `Team.Limits.DiskMb`。

关键代码路径：

- `TeamLimits.DiskMb` 定义：
  `packages/auth/pkg/types/limits.go`
- API 注册 build 时写入磁盘额度：
  `packages/api/internal/template/register_build.go`
- 新用户创建默认 team 时会绑定默认 tier：
  `packages/db/migrations/20231220094836_create_triggers_and_policies.sql`

可以把数据流理解成：

`user -> team -> tier/addon -> disk_mb -> template build`

## 方式 2：调整某个已有 tier

适用场景：

- 你希望某一类团队统一变大
- 你希望该 tier 下所有 team 后续新建 build 都拿到更大的磁盘

### 原理

团队的配额不是直接写死在代码里，而是从数据库里查出来的。  
如果某个 team 绑定的 tier 是 `base_v1`，那么把 `public.tiers.disk_mb` 调大后，这个 tier 下的团队后续发起的新 build 就会继承新的值。

### 直接改数据库

如果你只想立刻生效，最直接的是执行 SQL：

```sql
UPDATE public.tiers
SET disk_mb = 8192
WHERE id = 'base_v1';
```

如果你想查看当前值：

```sql
SELECT id, name, vcpu, ram_mb, disk_mb
FROM public.tiers
ORDER BY id;
```

### 建议做法

- 如果这是长期默认策略，应该通过 migration 管理
- 如果只是临时调试，也可以先直接更新数据库

### 影响范围

- 会影响所有绑定这个 tier 的 team
- 一般只影响后续新建的 build
- 已经在数据库里注册完成、已经进入执行流程的旧 build 不会自动回写成新值

### 风险

- 影响面比较大
- 如果很多 team 都共用这个 tier，成本会上升
- 需要确认底层 GCP 节点和构建节点磁盘也能承载更大的构建空间

## 方式 3：给某个 team 单独提额

适用场景：

- 不想影响所有团队
- 只想给某个客户、某个内部 team 或某个测试 team 增加构建磁盘

### 原理

从 migration 可以看到系统已经有 addons 机制：

- `packages/db/migrations/20251011200438_create_addons_table.sql`

这个机制里存在 `extra_disk_mb`，说明设计上支持在 tier 基础上给团队追加磁盘额度，而不是只能改全局 tier。

### 推荐做法

如果你们当前数据库已经跑到了 addons 相关 migration，优先走“附加额度”方案，而不是直接改基础 tier。

先确认相关表和视图是否已经存在：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name ILIKE '%addon%';
```

再查看当前 team 的限制来源：

```sql
SELECT t.id, t.name, t.tier
FROM public.teams t
ORDER BY t.created_at DESC;
```

如果 addons 机制已经可用，思路通常是：

- 找到目标 `team_id`
- 给该 team 增加 `extra_disk_mb`
- 最终生效值变成 `tier.disk_mb + extra_disk_mb`

### 如果 addons 机制还没接入你的运行环境

可以先用更直接的办法：

- 新建一个专用 tier，比如 `large_build_v1`
- 把它的 `disk_mb` 设大
- 只让目标 team 切换到这个 tier

示例：

```sql
INSERT INTO public.tiers (id, name, vcpu, ram_mb, disk_mb, concurrent_instances)
VALUES ('large_build_v1', 'Large build tier', 2, 512, 8192, 20);

UPDATE public.teams
SET tier = 'large_build_v1'
WHERE id = '<your-team-id>';
```

### 查看某个 team 当前实际 tier

```sql
SELECT t.id, t.name, t.tier, tr.disk_mb
FROM public.teams t
JOIN public.tiers tr ON tr.id = t.tier
WHERE t.id = '<your-team-id>';
```

## 选型建议

- 想改默认值：改 `tier`
- 想只影响一个 team：优先用 `addon` 或“单独 tier”
- 不建议频繁改 migration 来做运营配置

更稳妥的做法是：

- migration 只负责系统默认值
- 生产上的个别提额通过 SQL 或后台管理流程做

## 生效时机

这类改动通常对“后续新发起的 build”生效。  
已经开始执行的 build，一般不会自动继承新额度。

## 最小操作建议

如果你后面只是想给一个 team 提大 build 磁盘，优先顺序建议是：

1. 先查这个 team 当前 tier
2. 如果只改一个 team，优先单独 tier 或 addon
3. 如果所有新团队都应该更大，再改默认 tier
