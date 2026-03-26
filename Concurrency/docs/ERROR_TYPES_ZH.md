# Concurrency 错误类型说明

这份文档用于记录并发测试里最常见的几类错误，以及它们分别说明了哪个阶段出了问题。

当前建议按阶段来理解：

- placement 层：`api_limit`、`placement_failed`
- create/ready 层：`timeout`
- run 层：`command_failed`

## 1. `api_limit`

### 含义

请求在 API 的并发额度检查阶段就被拒绝了，还没进入 client / orchestrator 的实际启动流程。

### 典型表现

- HTTP 返回 `429`
- 没有 `sandbox_id`
- `command_seconds = 0`
- 很快失败，通常不到 1 秒

### 本质原因

- 当前 team 的并发 sandbox 数量已经达到上限
- API 在最前面的 team limit 检查就直接拒绝了请求

### 说明什么

这不是 client 容量问题，也不是 sandbox 启动慢，而是：

- team 配额先满了

---

## 2. `placement_failed`

### 含义

请求在 API 的 placement 阶段没能找到一个当前可接单的 client，所以没有进入真正的 sandbox 创建阶段。

### 典型表现

- 常见报错：`500: Failed to place sandbox`
- 没有 `sandbox_id`
- `command_seconds = 0`

### 两种常见形态

#### 快速失败

- 例如 `0.5s ~ 2s` 内失败

通常表示：

- API 很快就判断当前没有可用 client
- 唯一节点不在 `ready`
- 或 API 视角下该节点当前不可放置

#### 慢失败

- 例如接近 `60s` 才失败

通常表示：

- API 一直在尝试 placement
- 但在请求 deadline 内始终没等到可用节点

### 本质原因

常见原因包括：

- 当前没有 `ready` 的 client
- 单 client 的 orchestrator `starting` 槽位已满
- API 开启了 “too many starting” 过滤，把唯一节点排除了
- 节点状态还没收敛，API 暂时认为没有可用 node

### 说明什么

这不是 sandbox 启动后失败，而是：

- 请求根本没成功放到某台 client 上

---

## 3. `timeout`

### 含义

sandbox 已经进入创建流程，但在 ready 之前耗时过长，最终在 create 阶段超时。

### 典型表现

- 常见报错：`context deadline exceeded`
- 通常已经有 `sandbox_id`
- `command_seconds = 0`
- `create_seconds` 很长

### 本质原因

placement 已经成功，平台已经开始创建 sandbox，但创建链路中的某一步太慢，例如：

- microVM 启动
- rootfs / snapshot 恢复
- 网络准备
- envd 初始化
- ready check

### 说明什么

这不是“没地方放”，而是：

- 已经放进去了
- 但 sandbox 没能在时限内 ready

---

## 4. `command_failed`

### 含义

sandbox 已经创建成功并 ready，但执行测试命令时失败了。

### 典型表现

- 有 `sandbox_id`
- `command_seconds > 0`
- `exit_code != 0`
- 可能有 `stdout` / `stderr`

### 本质原因

常见原因包括：

- 命令本身写错
- sandbox 内运行环境不符合预期
- 资源紧张导致命令异常退出
- 网络 / IO / 内存压力影响运行期行为

### 说明什么

创建阶段已经成功，问题发生在：

- sandbox 运行期

---

## 快速判断规则

可以用下面这套规则快速判断失败发生在哪一层：

- 没有 `sandbox_id`，且报 `429`
  - `api_limit`
  - team 配额问题
- 没有 `sandbox_id`，且报 `500: Failed to place sandbox`
  - `placement_failed`
  - API 没找到可用 client
- 有 `sandbox_id`，但 `command_seconds = 0`
  - `timeout`
  - create / ready 阶段太慢
- 有 `sandbox_id`，且 `command_seconds > 0`
  - `command_failed`
  - 运行期命令失败

## 一句话总结

- `api_limit`：配额层拦截
- `placement_failed`：调度层失败
- `timeout`：创建层超时
- `command_failed`：运行层失败
