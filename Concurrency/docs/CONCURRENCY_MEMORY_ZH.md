# Concurrency 持续记忆文档

这份文档用于给 Codex 在进入 `Concurrency/` 目录时快速恢复上下文。

目标不是写成长文档，而是把当前最重要的测试目标、目录约定、架构理解、已知结论和下一步动作集中到一份持续维护的 md 里。

当前维护原则：

- `Concurrency/` 目前只保留 `test1` 作为主要测试入口
- `results/` 和 `plots/` 保留作为历史结果
- 旧的 burst / staggered / starting-window 脚本已清理，不再作为当前主要入口

---

## 1. 当前目录约定

当前主要关注这些文件：

- [run_running_capacity_probe.py](/home/ubuntu/whz/infra/Concurrency/test1/run_running_capacity_probe.py)
- [render_probe_table.py](/home/ubuntu/whz/infra/Concurrency/test1/render_probe_table.py)
- [memory.md](/home/ubuntu/whz/infra/Concurrency/test1/memory.md)
- [RUNNING_CAPACITY_PROBE_ZH.md](/home/ubuntu/whz/infra/Concurrency/test1/RUNNING_CAPACITY_PROBE_ZH.md)
- [ERROR_TYPES_ZH.md](/home/ubuntu/whz/infra/Concurrency/docs/ERROR_TYPES_ZH.md)

保留目录：

- [test1](/home/ubuntu/whz/infra/Concurrency/test1)
- [results](/home/ubuntu/whz/infra/Concurrency/results)
- [plots](/home/ubuntu/whz/infra/Concurrency/plots)

环境文件：

- [Concurrency/.env](/home/ubuntu/whz/infra/Concurrency/.env)

依赖文件：

- [pyproject.toml](/home/ubuntu/whz/infra/Concurrency/pyproject.toml)
- [uv.lock](/home/ubuntu/whz/infra/Concurrency/uv.lock)

---

## 2. 当前测试目标

当前不是在测 burst create，也不是在测 starting window 本身。

当前主要问题是：

- 单节点最终能稳定同时运行多少个 sandbox
- 第一次 placement 失败发生在第几个 sandbox
- 当最早一个 sandbox 释放后，新的 sandbox 能否补位成功

所以当前主测试脚本是：

- [run_running_capacity_probe.py](/home/ubuntu/whz/infra/Concurrency/test1/run_running_capacity_probe.py)

它的核心行为：

1. 按固定间隔发起 sandbox create
2. 每个 sandbox 内启动后台 `sleep`
3. 让 sandbox 在整个生命周期里占位
4. 首次 create 失败后停止继续加压
5. 等最早成功的 sandbox 结束后，再额外等待固定秒数
6. 立刻发起补位 retry create

注意：

- 现在 retry 逻辑已经调整为先 retry create，再打印 running 数量
- 这样不会让 `Sandbox.list()` 拖慢 retry 发起时间

---

## 3. 推荐命令

### 3.1 标准一轮

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv run python test1/run_running_capacity_probe.py \
  --template-id test1 \
  --max-sandboxes 6 \
  --interval-seconds 10 \
  --sandbox-timeout 200 \
  --create-request-timeout 0 \
  --command-timeout 30 \
  --retry-after-release-seconds 5 \
  --output-json results/test1/xxx.json
```

### 3.2 如果怀疑有残留 sandbox

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv run python test1/run_running_capacity_probe.py \
  --template-id test1 \
  --max-sandboxes 6 \
  --interval-seconds 10 \
  --sandbox-timeout 200 \
  --create-request-timeout 0 \
  --command-timeout 30 \
  --retry-after-release-seconds 5 \
  --force-cleanup-before-start \
  --output-json results/test1/xxx.json
```

### 3.3 基于单个 JSON 渲染表格

```bash
cd /home/ubuntu/whz/infra/Concurrency
python3 test1/render_probe_table.py results/test1/017.json
```

---

## 4. 时间字段解释

`test1` 里最常见的时间字段是：

- `started`
- `create`
- `ready`
- `finished`

当前推荐重点关注：

- `started`
- `create`
- `finished`

语义如下：

- `started`
  create 请求发出的偏移秒数

- `create`
  `Sandbox.create()` 请求总耗时

- `ready`
  `create + 启动后台 sleep 命令` 都完成后的时间点

- `finished`
  该 worker 生命周期结束的时间点

注意：

- `sandbox_timeout` 是从 create 发起时开始算
- 所以 `finished` 更接近 `started + sandbox_timeout`
- `run_window_s = finished - started`
  表示整个 worker 窗口长度，不是纯 ready 后运行时长

---

## 5. 当前架构理解

当前并发测试对应的创建链路，推荐这样理解：

1. API / orchestrator 接收创建请求
2. 做鉴权、参数校验、team 限额检查
3. 做 placement，选择目标 client
4. 目标 client 节点上的 orchestrator/runtime 真正启动 sandbox
5. Firecracker 与 envd 初始化完成后进入 `running`

关键区分：

- API 层 orchestrator
  负责接收请求、限额、placement、下发到节点

- client 节点上的 orchestrator/runtime
  负责准备资源、启动 Firecracker、等待 envd ready

`Failed to place sandbox` 的语义是：

- 创建请求到达服务端了
- 但在 placement 阶段没找到当前可接单的 client
- 所以 sandbox 没真正创建出来

这通常说明：

- 当前没有可放置容量
- 或调度器认为当前没有可用节点

---

## 6. 当前最重要的错误解释

失败先按下面几类理解：

- `api_limit`
  team 配额层被拦截

- `placement_failed`
  placement 阶段失败，没有找到可接单 client

- `timeout`
  placement 成功了，但 create/ready 太慢导致超时

- `command_failed`
  sandbox 已创建成功，但测试命令执行失败

详细说明见：

- [ERROR_TYPES_ZH.md](/home/ubuntu/whz/infra/Concurrency/docs/ERROR_TYPES_ZH.md)

---

## 7. 当前已知结论

### 7.1 旧结论

此前多轮测试曾观察到：

- 单节点稳定容量会波动
- 有时在 `4~5`
- 释放后也不一定立刻能补位

这个结论主要记录在：

- [memory.md](/home/ubuntu/whz/infra/Concurrency/test1/memory.md)

### 7.2 最新补充

最新一轮 `017.json` 使用参数：

- `max-sandboxes=6`
- `interval-seconds=2`
- `sandbox-timeout=200`

结果是：

- `6/6` 全部成功
- 没有出现 first failure
- 当前只能说明这轮环境下稳定 running capacity `>= 6`

这不应被解读为：

- “2 秒间隔一定比 10 秒更好”

更准确的解释是：

- 这轮环境下，`6` 个 sandbox 还没有触到容量边界
- 单次启动耗时本身很短，`2s` 也已经足够把 create 错开

因此后续要继续测上限，应继续升高：

- `max-sandboxes=8`
- 或 `max-sandboxes=10`

只有出现首次失败点，才能真正说这轮测到了边界。

### 7.3 关于“10 秒间隔失败、2 秒间隔成功”的当前判断

如果出现这种现象：

- `interval=10s` 时第 `6` 个左右就 `Failed to place sandbox`
- `interval=2s` 或 `1s` 时却能跑到 `10`、`16` 甚至更多

那么更合理的解释不是：

- 服务器真实只能跑 `5`

而是：

- 节点真实运行容量
- API 控制面当前看到的可放置容量

这两个值不是同一个值。

当前更稳妥的判断应是：

- 快间隔测试更接近真实 running capacity
- 慢间隔测试更接近当前 placement 逻辑在控制面视角下的稳定可创建上限

换句话说：

- `10s` 失败更像控制面提前拒绝
- `2s/1s` 成功更像节点真实还能继续承载

因此：

- `10s` 间隔下失败，不能直接当成节点物理上限
- 当前观察到的真实 running capacity 至少已经明显高于早期的 `4~5`

---

## 8. 当前问题本质

当前现象的本质不是：

- 测试脚本乱算
- 或服务器真实容量随机变化

更像是：

- 控制面 placement 使用了一份会滞后刷新的容量视图
- client 节点本身则持有更接近真实的运行状态

### 8.1 真实容量和控制面容量不是同一个数

当前系统里至少存在两套“容量真相”：

1. 节点真实状态
   - client 上已经跑了多少 sandbox
   - 当前真实资源还剩多少
   - 节点还能不能再接新的 sandbox

2. API / placement 侧看到的状态
   - 通过定期同步得到的 node metrics
   - API 本地记录的 in-progress placement 状态
   - placement 算法基于这些数据做保守过滤

这两者目前没有完全统一成一个实时真相源。

### 8.2 为什么慢节奏反而更早失败

当前 API 侧 placement 的关键路径是：

- placement 会读取 node metrics 做 `CanFit`
- node metrics 通过定期 `ServiceInfo` 同步进入 API
- 同步周期默认是 `20s`

所以：

- 间隔 `10s`
  - 两次请求之间更容易撞上 metrics 刷新
  - API 更可能读到“更新后的保守状态”
  - placement 更早拒绝

- 间隔 `2s` / `1s`
  - 请求跑得比 metrics 刷新更快
  - API 仍在用偏旧的容量视图
  - 更容易连续放进去更多 sandbox

因此这类现象本质上是：

- placement 的状态时序问题
- 而不是单纯的物理机绝对资源问题

### 8.3 为什么改小 `cacheSyncTime` 不是根治

即使把同步周期从 `20s` 改成 `5s`、`2s`，也只能缓解，不能根治。

原因：

- 它仍然是定期轮询，不是实时推送
- placement 仍然依赖缓存过来的指标
- API 侧还有独立的 `PlacementMetrics.InProgressCount()`
- node 侧真正的 `starting` 限制又是另一套状态

所以改小同步周期只能：

- 减少滞后

但不能解决：

- API 容量视图和 node 真实容量视图不一致

---

## 9. 根因链路对应代码

当前这条问题链路，建议优先看这些文件：

### 9.1 API 侧 placement

- [placement.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement.go)
- [placement_best_of_K.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement_best_of_K.go)

关键点：

- `PlaceSandbox()` 会在 API 侧选 node，然后调用 node 的 `SandboxCreate`
- `BestOfK.CanFit()` 会使用缓存指标 `CpuAllocated` 做过滤
- `TooManyStarting` 逻辑会读取 API 本地维护的 `PlacementMetrics.InProgressCount()`

### 9.2 API 侧 node metrics 与同步

- [cache.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/cache.go)
- [sync.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/sync.go)
- [metrics.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/metrics.go)
- [placement_metrics.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/placement_metrics.go)

关键点：

- `cacheSyncTime = 20s`
- `node.Sync()` 通过 gRPC `ServiceInfo()` 拉取 node 状态
- `UpdateMetricsFromServiceInfoResponse()` 把 node 指标写入 API 本地缓存
- `PlacementMetrics` 是 API 本地自己维护的“正在 placement 中”的计数

### 9.3 node 侧真实指标来源

- [service_info.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/service/service_info.go)

关键点：

- node 的 `ServiceInfo()` 会实时遍历当前 sandbox map
- `MetricCpuAllocated`
- `MetricSandboxesRunning`

这些值比 API 缓存更接近 node 当前真实状态。

### 9.4 node 侧真正的 starting / running 限制

- [main.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/main.go)
- [sandboxes.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/sandboxes.go)

关键点：

- node 侧用 `startingSandboxes` 信号量限制同时启动数
- 还会检查 `maxRunningSandboxesPerNode`
- 这才是 node 本地真正执行时的硬限制

---

## 10. 如果要根治，优先该改哪些模块

### 10.1 第一优先级：让 placement 更接近 node 实时真相

目标：

- placement 不要只依赖 `20s` 一次的缓存指标

优先考虑：

- placement 前增加更实时的 node 容量检查
- 或由 node 直接回答“当前是否还能接这个 sandbox”

可涉及模块：

- [placement.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement.go)
- [placement_best_of_K.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement_best_of_K.go)
- [service_info.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/service/service_info.go)

### 10.2 第二优先级：统一 API 侧和 node 侧的 starting 口径

当前问题：

- API 看 `PlacementMetrics.InProgressCount()`
- node 看 `startingSandboxes`

这两者不是同一个源。

改造方向：

- 尽量不要让 API 自己猜 starting 状态
- 改成 node 暴露实时 starting 数或实时可接单状态

可涉及模块：

- [placement_metrics.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/nodemanager/placement_metrics.go)
- [main.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/main.go)
- [sandboxes.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/sandboxes.go)

### 10.3 第三优先级：把 placement 失败原因拆细

当前对外几乎都压成：

- `Failed to place sandbox`

这会导致运维时无法一眼知道问题属于哪一层。

改造方向：

- 拆出：
  - `no_node_ready`
  - `node_canfit_rejected`
  - `node_starting_limit_rejected`
  - `node_running_limit_rejected`
  - `placement_timeout`

可涉及模块：

- [create_instance.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/create_instance.go)
- [placement.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/placement/placement.go)

### 10.4 第四优先级：再考虑缩短 sync 周期

这一步是缓解项，不是根治项。

可做：

- 把 `cacheSyncTime` 从 `20s` 调小
- 或做成配置 / feature flag

可涉及模块：

- [cache.go](/home/ubuntu/whz/infra/packages/api/internal/orchestrator/cache.go)

---

## 11. 目前最稳妥的表达方式

当前如果要对别人说明，应优先使用这段表述：

> 当前系统里，sandbox 的真实运行容量和 placement 控制面的可见容量不是同一个值。  
> client 节点实际上可以承载更多 running sandbox，但 API/orchestrator 的 placement 依赖周期同步的节点状态和保守的可放置判断，因此在某些创建节奏下会提前拒绝请求。  
> 所以 `10s` 间隔时较早失败，并不代表节点真实上限低，而代表控制面的容量视图存在滞后和保守偏差。

---

## 12. 当前维护注意点

### 8.1 不要混淆三种 timeout

- `sandbox_timeout`
  sandbox 生命周期

- `create_request_timeout`
  `Sandbox.create()` HTTP 请求超时

- `command_timeout`
  启动后台 `sleep` 的命令请求超时

### 8.2 不要把 `ready` 当成唯一主字段

对结果说明来说，通常保留：

- `started`
- `create`
- `finished`

就足够了。

`ready` 是派生字段，只有在需要分析“真正 ready 时刻”时再强调。

### 8.3 如果要精简表格

最适合肉眼读的列通常是：

- `index`
- `phase`
- `success`
- `sandbox_id`
- `started_s`
- `create_s`
- `finished_s`
- `error_type`
- `error_message`

### 8.4 如果结果看起来波动，不要急着下结论

当前容量测试是经验性探测，不是理论上限证明。

所以：

- 一轮 `5`
- 一轮 `6`

并不矛盾。

更稳妥的说法应始终是：

- 当前观察到的稳定区间
- 而不是“绝对上限已完全确定”

---

## 13. 接手时第一动作

如果 Codex 重新接手这块内容，建议按这个顺序恢复上下文：

1. 先读本文件
2. 再读 [memory.md](/home/ubuntu/whz/infra/Concurrency/test1/memory.md)
3. 再读 [RUNNING_CAPACITY_PROBE_ZH.md](/home/ubuntu/whz/infra/Concurrency/test1/RUNNING_CAPACITY_PROBE_ZH.md)
4. 确认 [Concurrency/.env](/home/ubuntu/whz/infra/Concurrency/.env) 中的：
   - `E2B_DOMAIN`
   - `E2B_API_KEY`
   - `E2B_TEMPLATE_ID`
5. 先看最近一次 `results/test1/*.json`
6. 如需继续压测，再跑一轮新结果

---

## 14. 后续维护方式

这份文档应该持续更新，但只保留高价值信息：

- 当前目录策略
- 当前主入口脚本
- 当前关键架构理解
- 当前最新可复用结论
- 当前推荐命令

不保留低价值信息：

- 过长的过程聊天记录
- 临时推测但未验证的说法
- 已删除脚本的详细说明
