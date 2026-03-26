# E2B 并发测试中 burst 启动失败的原因说明

这份文档用于解释当前这套 self-hosted E2B 在并发测试中，为什么会出现下面这种现象：

- 有时候 `15` 个 sandbox 同时创建全部成功
- 有时候 `20` 个 sandbox 同时创建全部成功
- 有时候 `20` 个 sandbox 同时创建只成功一部分
- 有时候连续测试后，连 `2` 个并发都直接失败

核心结论先放前面：

> 当前失败的本质，不是虚拟机宕了，也不是 team 配额不够，而是单台 client 节点上的 `orchestrator` 对“同时处于 starting 状态的 sandbox 数量”有限制。瞬时并发创建请求过多时，会在 placement 阶段被拒绝。

---

## 1. 这次测试到底测的是什么

当前脚本：

- [run_concurrency_test.py](/home/ubuntu/whz/infra/Concurrency/run_concurrency_test.py)

默认测的是：

- 多个 `Sandbox.create()` 同时发起
- sandbox 创建成功后执行一条轻量 Python 命令
- 再保持一段时间

所以这类测试更准确地说是在测：

- **burst create concurrency**
- 也就是“瞬时同时启动”的并发能力

它不是在测：

- 错峰启动后最终同时运行多少个 sandbox

---

## 2. orchestrator 是什么

`orchestrator` 是这套 E2B 平台里真正负责启动和管理 sandbox 的核心服务。

可以把链路理解成：

1. 你的 Python 脚本调用 `Sandbox.create()`
2. API 收到请求
3. API 校验 team、API key、template
4. API 选择一个 client 节点
5. client 节点上的 `orchestrator` 真正启动 sandbox

所以：

- API 像前台接单
- orchestrator 像后厨开工
- client VM 是后厨所在的厨房

---

## 3. 这次失败不是谁拒绝了

对外你看到的是：

```text
500: Failed to place sandbox
```

但真正做出“拒绝”判断的不是 API 本身，而是：

- client 节点上的 `orchestrator`

流程是：

1. API 把请求发给 orchestrator
2. orchestrator 判断当前节点是否还能接新的 sandbox 启动
3. 如果不能，就返回 `ResourceExhausted`
4. API 因为没有别的 client 节点可换，最后对外包装成：
   - `500: Failed to place sandbox`

所以这类错误的本质是：

- **placement 阶段失败**
- **不是运行阶段失败**

---

## 4. “starting sandboxes” 限制到底是什么

当前代码里，单个 client 节点有一个写死的限制：

- `maxStartingInstancesPerNode = 3`

位置在：

- [sandboxes.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/sandboxes.go:45)
- [main.go](/home/ubuntu/whz/infra/packages/orchestrator/internal/server/main.go:85)

它的准确含义是：

> 单台 client 节点上，**同一时刻最多只允许 3 个 sandbox 处于 starting 状态。**

这里的 `starting` 指的是 sandbox 还在启动流程中，例如：

- 取模板
- 准备快照 / rootfs / memfile
- 分配网络
- 启动 microVM
- 等 ready check 通过

这个 `3` 不是：

- 最多只能运行 `3` 个 sandbox
- team 最多只能有 `3` 个 sandbox
- 这轮请求最多只能成功 `3` 个

它只是：

- 同一时刻最多只有 `3` 个 sandbox 能进入“启动中”

---

## 5. 为什么 15、20 有时候又能全部成功

因为这个 `3` 限制的是：

- **同时处于 starting 状态的数量**

而不是：

- **这一轮请求最终总共能成功多少个**

可以把它理解成一个只有 `3` 个位置的“启动窗口”：

1. 先进去 `3` 个 sandbox 开始启动
2. 其中一部分启动完成后，窗口空出来
3. 后面的请求再进来
4. 所以最终一整轮可能成功很多个，不止 `3`

所以：

- `15` 有可能最终全部成功
- `20` 也有可能最终全部成功

前提是：

- 后面的请求能在 deadline 之前等到启动窗口释放

---

## 6. 为什么同样是 20，有时全成功，有时只成功 13 个

这正是当前问题的本质。

当前波动来自这几个因素共同作用：

1. 单节点 `starting` 窗口只有 `3`
2. 每个 sandbox 的启动耗时不是固定的
3. 模板、缓存、系统状态、上一轮测试后的回收情况都会影响启动耗时
4. API/placement 不是无限等，而是在请求 deadline 内反复尝试

所以：

- 如果这一轮里，后续请求都能在 deadline 内轮到启动窗口
  - 可能 `20/20` 全成功
- 如果其中部分请求在 deadline 内始终没等到空位
  - 可能变成 `19/20`
  - 或 `13/20`

所以更准确的说法是：

> 这不是固定容量上限，而是“启动窗口限制 + 启动耗时波动 + 请求 deadline”共同造成的结果波动。

---

## 7. 为什么有时候连续测试后，连 2 并发都失败

这不表示：

- 单机的并发能力只有 `1`
- 或 `2` 也超过了机器极限

而是表示：

> 在你发起这两个请求的那个时刻，这台 client 节点从调度器视角看，已经没有可用的启动槽位了。

这种情况的特征通常是：

- 很快失败，例如 `0.3s ~ 0.8s`
- 没有 `sandbox_id`
- `command_seconds = 0`
- 全部是：
  - `placement_failed`
  - `500: Failed to place sandbox`

这说明请求根本没进入真正启动阶段，而是在 placement 阶段就被挡住了。

最常见原因是：

- 前一轮测试后的启动窗口还没释放完
- 上一波请求刚结束，调度状态还没收敛
- 当前节点仍被视为“没有可用 starting 槽位”

---

## 8. CPU 只有 12%，为什么 15/20 还是会失败

因为当前碰到的瓶颈不是：

- CPU
- 内存
- 磁盘

而是：

- **启动阶段并发限制**

所以：

- CPU 利用率低
- 内存利用率不高

并不能说明：

- `15` 或 `20` 的瞬时启动一定会成功

当前更准确的理解是：

- **稳定运行上限** 可能还没到
- 但 **同时启动上限** 已经先撞到 orchestrator 的 starting 限流了

---

## 9. 这和 team 并发上限是不是一回事

不是一回事。

当前至少有两层限制：

### 9.1 Team 配额限制

例如：

- `concurrent_sandboxes = 20`

这表示：

- 这个 team 最多允许同时拥有多少个 sandbox

### 9.2 Client 节点启动限制

例如：

- `maxStartingInstancesPerNode = 3`

这表示：

- 单台 client 节点同一时刻最多允许多少个 sandbox 进入启动流程

所以：

- team 设成 `20`
- 并不等于单台 client 能稳定瞬时启动 `20`

---

## 10. API key 和这个问题有没有关系

同一个 team 下的 API key 共享同一套 team 限额。

也就是说：

- 同 team 下换不同 API key
- 不会改变这个问题

当前问题的关键不在 API key，而在：

- 这个 key 所属的 team
- 这个 team 的 tier
- 单台 client 的 orchestrator 启动并发限制

---

## 11. 这个问题要怎么解释给别人

最推荐的一段话是：

> 当前并发测试失败，不是因为 VM 宕了，也不是因为 team 配额不够，而是因为单台 client 节点上的 orchestrator 对“同时处于 starting 状态的 sandbox 数量”有限制，当前代码里这个值是 3。15 或 20 个 sandbox 同时创建时，部分请求会在启动窗口和请求 deadline 的竞争中失败。由于环境里只有 1 台 client，API 无法把失败请求分流到别的节点，所以最终对外表现为 `500: Failed to place sandbox`。

更短版：

> 失败的本质不是资源硬打满，而是单节点启动并发限流。

---

## 12. 当前结论应该怎么写

如果你要写测试结论，建议这样表述：

1. 当前轻量脚本测试的是 **burst create concurrency**
2. 当前环境只有 `1` 台 client
3. 单节点 orchestrator 对 `starting sandboxes` 有限制，当前值是 `3`
4. 因此 `15/20` 这种瞬时同时创建会出现波动
5. 这不代表最终稳定运行并发上限只有 `3`
6. 也不代表机器 CPU/内存已经耗尽
7. 当前反映的是：
   - **瞬时启动并发能力**
   - 而不是最终稳定承载能力

---

## 13. 下一步应该怎么测

如果你要继续测更贴近真实业务的并发，建议分成两类：

### 13.1 Burst 并发

- 所有请求同时打出去
- 继续测“启动风暴上限”

### 13.2 Steady 并发

- 请求错峰启动
- 最终让很多 sandbox 同时在线
- 测“稳定运行并发能力”

也就是说：

- `burst` 测的是“同一时刻启动能力”
- `steady` 测的是“最终同时运行能力”

两者都属于并发测试，只是关注点不同。
