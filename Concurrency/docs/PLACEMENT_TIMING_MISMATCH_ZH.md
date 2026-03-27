# Placement 时序不一致问题说明

这份文档专门解释一个当前已经被多轮测试反复观察到的现象：

- `1s` 或 `2s` 间隔创建 sandbox 时，可以连续创建很多个
- `10s`、`20s`、`50s` 这类更慢的间隔下，却会更早出现 `Failed to place sandbox`

这件事非常反直觉，所以单独写成一份文档。

---

## 1. 先说结论

当前现象的本质不是：

- 测试脚本乱算
- 服务器真实容量忽高忽低
- `sandbox_timeout` 本身导致了“第 5 个一定失败”

更准确地说：

> 当前系统里，节点真实运行容量，与 API / placement 控制面看到的可放置容量，不是同一个实时值。

因此：

- 快节奏请求更容易在控制面状态还没完全收敛前，把更多 sandbox 连续放进去
- 慢节奏请求更容易吃到“更新后的保守判断”，所以更早失败

所以：

- 快节奏测试更接近真实 running capacity
- 慢节奏测试更接近当前控制面稳定允许的 create 容量

---

## 2. 为什么会困惑

用户最容易直觉上这样理解：

> 既然这台机器能同时跑很多 sandbox，那为什么我慢一点创建，反而更早失败？

或者：

> 如果 `2s` 间隔能到 `16`，那 `20s` 间隔为什么第 `5` 个就不行？

这个直觉之所以会被打破，是因为当前系统不是直接用“节点此刻真实还能不能跑”来决定 placement。

它实际使用的是几层状态混合后的结果。

---

## 3. 系统里实际有哪几层状态

当前至少存在 3 层会影响 create 是否成功。

在继续往下看之前，先明确一件事：

API 侧实际上维护着一份“node 资源/状态表”的缓存视图。这里说的“表”不是数据库表，而是 API 进程内存里对每个 client 节点保存的一组状态。

这份 node 表里当前主要有这些内容：

- `status`
  - 节点当前是否 `ready` / `unhealthy` / `connecting` / `draining`
  - 决定该 node 是否有资格参与 placement
- `labels`
  - 节点属性标签
  - 用于先筛选“哪些节点适合接这类请求”
- `machine info`
  - CPU 架构、family、model、flags 等硬件信息
  - 用于做 CPU/硬件兼容性判断
- `CpuAllocated`
  - API 当前认为这台 node 已经账面分配给 sandbox 的 CPU 总量
- `CpuCount`
  - 这台 client 节点的总 CPU 数
- `CpuPercent`
  - 这台主机当前真实 CPU 使用率
- `MemoryAllocatedBytes`
  - API 当前认为这台 node 已经账面分配出去的内存总量
- `MemoryUsedBytes`
  - 主机当前真实已使用内存
- `MemoryTotalBytes`
  - 主机总内存
- `SandboxCount`
  - 当前 node 上运行中的 sandbox 数量
- `HostDisks`
  - 主机磁盘使用信息
- `placement in-progress`
  - API 自己本地维护的、这个 node 上当前仍在 placement/create 流程中的请求数
  - 这一项不是 node sync 来的，而是 API 服务器即时维护的

这些内容并不是都以同样重要的方式参与 placement。

在当前代码里：

- 第一层最核心的硬过滤依据主要是：
  - `status`
  - `CpuAllocated`
  - `CpuCount`
- `labels` 和 `machine info`
  - 主要负责做候选节点筛选
- `CpuPercent`
  - 主要影响 score 排序
- `Memory*` 和 `SandboxCount`
  - 当前更多是资源/状态视图的一部分，并不是第一层最关键的硬限制
- `placement in-progress`
  - 是第二层的重要组成部分

### 3.1 第一层：API 侧缓存的 node metrics

API / placement 在决定“当前 node 能不能放新 sandbox”时，不是每次都去 node 上实时读取真相。

它会读取 API 侧已经缓存下来的 node metrics，例如：

- `CpuAllocated`
- `CpuCount`
- `SandboxCount`
- node `ready` 状态

这些值来自 node 的 `ServiceInfo()`，但不是每个请求实时拉取，而是定期同步到 API 本地。

当前同步周期在代码里是：

- [cache.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/cache.go)

```go
const cacheSyncTime = 20 * time.Second
```

也就是说：

- API 看到的 node 容量视图，默认有最多约 `20s` 的滞后风险

第一层里最关键的实际判断是：

- 当前 node 是否 `ready`
- 当前控制面账面上已经分配了多少 CPU
- 这次新 sandbox 还要再申请多少 CPU

其中 `CanFit()` 的核心含义可以直接表述为：

> 当前已分配 CPU + 这次新请求 CPU，不能超过控制面允许的总 CPU 容量。

公式大意是：

```text
reserved + requested <= R * cpuCount
```

其中：

- `reserved = CpuAllocated`
- `requested = 这次 sandbox 请求的 CPU`
- `cpuCount = 这台 client 节点总 CPU 数`
- `R = overcommit ratio`

如果不满足这个条件，那么第一层就会认为：

- 当前这个 node 不应该继续放这个 sandbox

注意：

- 这表示控制面视角下“不应继续放”
- 不等于 node 实时真实“已经绝对跑不动”

这也是为什么第一层的上限可能明显低于 node 侧真实运行上限。

---

### 3.2 第二层：API 本地的 in-progress placement 状态

API 在 placement 时，不只看缓存指标，还会看自己本地记录的：

- 当前有多少个 sandbox 请求正在这个 node 上 placement / create 流程中

相关代码在：

- [placement_metrics.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/placement_metrics.go)

它会记录：

- `StartPlacing(...)`
- `InProgressCount()`

这个状态是即时变化的，不依赖 `20s` 同步周期。

这里要特别注意一个容易误解的点：

`placement in-progress` 不是：

- 当前有多少个 `running`
- 也不等于 node 真实 `starting` 数量

更准确地说，它表示：

- API 服务器自己当前记着的
- 某个 node 上仍在 placement/create 流程中的请求数

所以它和 `SandboxCount`、node 侧真实 `starting` 状态都不是同一个东西。

所以即使 node metrics 还没刷新，
API 也可能因为自己本地觉得：

- “这个 node 现在 placement 太多了”

从而更早跳过该 node。

---

### 3.3 第三层：node 侧真正的硬限制

就算 API 选中了一个 node，并发起 create，node 侧也还会自己做一次真正的硬限制判断。

node 侧会检查：

- 当前 running sandbox 是否超过上限
- 当前 starting sandbox 是否超过上限

相关代码在：

- [sandboxes.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/sandboxes.go)
- [main.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/main.go)

如果 node 当场认为：

- 现在不能接单

它会直接返回 `ResourceExhausted`，然后 API 最终也可能对外表现成：

- `Failed to place sandbox`

---

## 4. 真实 create 链路到底怎么走

下面按代码链路讲一次完整流程。

### 4.1 API 侧收到 create 请求

入口逻辑在：

- [create_instance.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/create_instance.go)

这里会调用：

- `placement.PlaceSandbox(...)`

---

### 4.2 placement 先选 node

代码在：

- [placement.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement.go)

placement 会先：

1. 从候选 node 中选一个
2. 再调用这个 node 去真正创建 sandbox

---

### 4.3 `chooseNode()` 时会先做本地过滤

代码在：

- [placement_best_of_K.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement_best_of_K.go)

这里会过滤 node，典型包括：

- node 是否 `ready`
- CPU 是否兼容
- label 是否兼容
- `CanFit`
- `TooManyStarting`

#### `CanFit`

`CanFit()` 会用：

- `node.Metrics().CpuAllocated`
- `node.Metrics().CpuCount`

来判断：

> API 当前认为这台 node 还能不能放新的 sandbox

注意：

- 这里用的是 API 本地缓存 metrics
- 不是 node 每次请求前的实时真相

#### `TooManyStarting`

如果这个逻辑开启，会读：

- `n.PlacementMetrics.InProgressCount()`

也就是 API 本地自己的 in-progress placement 计数。

---

### 4.4 如果 API 本地判断已经没有 node 可选

那么 placement 在 API 侧就会直接失败。

此时的失败是：

- API 自己觉得当前没有可放置 node

并不一定意味着：

- node 真实物理容量真的满了

---

### 4.5 如果 API 选中了 node

placement 会调用：

- `node.SandboxCreate(...)`

代码在：

- [sandbox_create.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/sandbox_create.go)

它本质上会通过 gRPC 调 node 侧的：

- `client.Sandbox.Create(...)`

---

### 4.6 node 侧真正执行 create

node 侧 create 在：

- [sandboxes.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/sandboxes.go)

这里会真的检查：

- `maxRunningSandboxesPerNode`
- `startingSandboxes.TryAcquire(1)`

所以即使 API 觉得“可以放”，
node 也可能当场说：

- “不行，我现在 starting 太多了”
- “不行，我 running 已经太多了”

---

### 4.7 最终错误为什么常常都看起来一样

API 最后对外很多情况都会收敛成：

- `500: Failed to place sandbox`

所以你在测试脚本里看到的：

- `placement_failed`

只是脚本根据错误字符串做的分类。

它并不表示：

- 错误一定只发生在 placement 最早阶段

而是表示：

- 最终被控制面统一包装成了 placement 类失败

---

## 5. 为什么不同间隔会得到不同结果

下面用真实节奏解释。

### 5.1 `1s` 或 `2s` 间隔

这类快节奏测试的特点是：

- 请求在很短时间内持续打入 API
- 很多 create 都发生在 API 侧 node metrics 下一次同步前

结果就是：

- API 还没完全更新到更保守的容量状态
- placement 会继续把更多 sandbox 放进去

因此：

- 快节奏测试更接近节点真实 running capacity

---

### 5.2 `10s`、`20s`、`50s` 间隔

这类慢节奏测试的特点是：

- 两次 create 之间，API 更有机会同步 node metrics
- 控制面状态更容易收敛
- placement 更容易在中途就开始保守拒绝

因此：

- 慢节奏测试更接近控制面稳定可创建边界

不是因为：

- 机器真实只能跑这么少

而是因为：

- 控制面更早觉得“不该再继续放”

---

## 6. 用真实例子解释

### 6.1 快节奏例子

如果：

- `interval = 1s`
- 第 `17` 个才第一次失败

那么说明：

- 在这轮快节奏里，系统至少允许前 `16` 个 sandbox 真实进入运行阶段

这更接近：

- 节点真实承载能力

---

### 6.2 慢节奏例子

如果：

- `interval = 20s`
- 第 `5` 个失败
- 第 1 个 sandbox 释放后，即使当前只剩 `3` 个 running，retry 仍然连续失败两次
- 直到十几秒后才终于补位成功

那么这说明：

- `Failed to place sandbox` 不是简单等于“当前 sandbox 数量已经达到硬上限”

因为：

- 如果硬上限真是 `4`
- 当运行中的数量从 `4` 降到 `3` 时
- 新 sandbox 理论上应该立刻可以补进去

但实际没有。

所以更合理的解释是：

- 控制面视角下的“可放置状态”恢复得比 node 真实 running 数下降更慢

---

### 6.3 `50s` 间隔例子

如果：

- `interval = 50s`
- 也是第 `5` 个失败
- 但第一个 sandbox 释放后，一次 retry 就成功

这说明：

- 慢节奏下第 `5` 个提前失败，并不是 `20s` 的偶发现象
- 控制面在较慢节奏下确实会稳定地把边界压在更低的位置
- 只是恢复时序有时更快，有时更慢

---

## 7. 所以到底有几个“上限”

当前至少有两个不同的“上限”。

### 7.1 真实运行上限

即：

> 这台 client 最终实际上能同时 running 多少个 sandbox

这更适合用：

- `1s`
- `2s`

这类快节奏测试去逼近。

---

### 7.2 控制面稳定可创建上限

即：

> 在当前架构下，控制面在较慢节奏请求里，稳定愿意继续 placement 到多少

这更适合用：

- `10s`
- `20s`
- `50s`

这类慢节奏测试去看。

---

## 8. 为什么改小 `cacheSyncTime` 不是根治

即使把：

```go
const cacheSyncTime = 20 * time.Second
```

改成：

- `5s`
- `2s`

它也只能缓解，不能根治。

因为问题不只是：

- node metrics 同步慢

还包括：

- API 自己本地维护一套 `PlacementMetrics.InProgressCount()`
- node 自己又有一套 `startingSandboxes`
- 错误最后又被统一包装成 `Failed to place sandbox`

所以真正的问题是：

- 容量视图不统一

而不是：

- 单个同步间隔太大

---

## 9. 最稳妥的对外说明

如果需要在会议或文档里说明，优先使用这段表述：

> 当前系统里，sandbox 的真实运行容量和 placement 控制面的可见容量不是同一个值。  
> client 节点实际上可以承载更多 running sandbox，但 API/orchestrator 的 placement 依赖周期同步的节点状态、本地 in-progress placement 状态以及 node 即时返回的限制，因此在不同创建节奏下会出现不同的可创建并发边界。  
> 所以 `10s`、`20s`、`50s` 这类慢节奏下较早失败，并不代表节点真实上限低，而代表控制面的容量视图存在滞后和保守偏差。

---

## 10. 当前最需要继续做什么

如果目标是：

### 10.1 搞清楚真实 running capacity

继续使用：

- `1s`
- `2s`

节奏往上压。

### 10.2 搞清楚稳定 placement 行为

继续对比：

- `10s`
- `20s`
- `50s`

看慢节奏下的稳定 create 边界。

### 10.3 从工程上根治

优先改这些方向：

- placement 不要只依赖缓存 node metrics
- API 和 node 统一 starting / capacity 口径
- placement 失败原因拆细，不再全部压成一个总错误
## 三层对“没位置了”的处理方式

当前普通 `sandbox create` 路径里，这三层默认都不是“等待位子释放后继续”，而是“跳过或直接失败返回”。

### 第一层：API 缓存资源视图

第一层发生在 API/placement 侧。它会基于 node 资源表做过滤，例如：

- `status` 不是 `ready`
- `CanFit()` 判断不通过
- labels 不匹配
- machine info 不兼容

这层的处理方式不是等待，而是：

- 直接跳过当前 node
- 尝试别的 node
- 如果没有可用 node，最终返回 placement 失败

### 第二层：API 本地 `placement in-progress`

第二层也是 API 侧过滤，不是等待。

当开启 `TooManyStarting` 时，placement 会检查：

```go
if n.PlacementMetrics.InProgressCount() > maxStartingInstancesPerNode {
    continue
}
```

当前阈值在 API placement 侧是：

```go
maxStartingInstancesPerNode = 3
```

也就是说：

- 某个 node 的 `placement in-progress` 太高时
- 这个 node 会被直接跳过
- 不会在 API 侧排队等待

### 第三层：node/client 侧真实硬限制

第三层在 node 侧 `Create(...)` 里执行，主要有两道限制：

1. `running` 上限
2. `starting` 上限

#### running 上限

node 会先读取：

- `maxRunningSandboxesPerNode`

再统计当前：

- `runningSandboxes := s.sandboxFactory.Sandboxes.Count()`

如果：

```go
runningSandboxes >= maxRunningSandboxesPerNode
```

就会直接返回：

```go
codes.ResourceExhausted
```

这不是等待，而是立刻失败。

这里要特别注意：

- 这个 `running` 上限不是按 CPU/内存动态计算出来的
- 它是 node 侧直接读取的一个 feature flag 整数值

代码位置：

- node 侧读取上限：`packages/orchestrator/internal/server/sandboxes.go`
- flag 默认值：`packages/shared/pkg/featureflags/flags.go`

默认定义是：

```go
MaxSandboxesPerNode = newIntFlag("max-sandboxes-per-node", 200)
```

也就是说，如果没有被别的配置覆盖，第三层默认的 `running` 数量硬上限是：

```text
200
```

因此第三层 `running` 限制的本质是：

> 当前 sandbox 数量是否已经达到配置上限

而不是：

> 当前 CPU/内存是否按某个公式算满了

这也解释了为什么当前并发测试里，真正挡住请求的往往不是第三层 `running=200`，而是前两层更早的 placement 过滤或第三层 `starting` 限制。

#### starting 上限

普通 create 路径里，node 用 semaphore 控制同时启动中的 sandbox 数量：

```go
acquired := s.startingSandboxes.TryAcquire(1)
if !acquired {
    return nil, status.Errorf(codes.ResourceExhausted, "too many sandboxes starting on this node, please retry")
}
defer s.startingSandboxes.Release(1)
```

这里的关键是：

- 用的是 `TryAcquire(1)`
- 不是阻塞等待

因此：

- 没抢到 starting 名额
- 也是直接失败返回

当前 node 侧默认 `starting` 并发阈值是：

```go
maxStartingInstancesPerNode = 3
```

### 结论

普通 sandbox create 这三层的默认行为可以概括成：

- 第一层：不合适就跳过 node
- 第二层：in-progress 太高就跳过 node
- 第三层：running 或 starting 达到上限就直接 `ResourceExhausted`

它们都不是“等待位子释放后自动继续”的排队模型。
