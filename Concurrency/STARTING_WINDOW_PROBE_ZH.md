# Starting Window Probe

这份文档对应脚本：

- [run_starting_window_probe.py](/home/ubuntu/whz/infra/Concurrency/run_starting_window_probe.py)

它的目标不是测“最终最多能同时运行多少个 sandbox”，而是验证下面这个现象：

> 单个 client 节点同时最多只能有少量 sandbox 处于 `starting` 状态。  
> 如果瞬时同时发起的 `Sandbox.create()` 太多，后面的请求可能会在 placement 阶段快速失败。

在你当前这套单 `client` 环境里，这个脚本主要用来验证：

- burst create 是否会撞到 `starting` 窗口
- 快速 `placement_failed` 是否出现
- “启动窗口限制” 和 “最终 running 容量” 不是一回事

## 1. 这个脚本测什么

脚本会同时发起一批 `Sandbox.create()` 请求：

- 默认 `--concurrency 6`
- 所有请求同时开始
- sandbox 创建成功后执行一个轻量命令
- 成功后再保留一段时间，避免太快释放资源

如果在这批请求里出现：

- 没有 `sandbox_id`
- `error_type = placement_failed`
- `create_seconds` 很短，例如 `<= 3s`

那么通常可以认为：

- 失败请求根本没进入真正的 sandbox 启动阶段
- 更像是 placement 发现当前 `client` 没有空余 `starting` 槽位

## 2. 什么时候适合用它

适合：

- 你想验证 `starting` 窗口是否会成为 burst create 的瓶颈
- 你想解释为什么同一台 `client` 不是只能运行 `3` 个 sandbox，但仍然会在 burst create 时失败

不适合：

- 测最终同时 running sandbox 的上限
- 测错峰启动后的稳定容量

要测最终 running 容量，更适合用：

- [run_staggered_concurrency_test.py](/home/ubuntu/whz/infra/Concurrency/run_staggered_concurrency_test.py)

## 3. 推荐命令

先确保 `Concurrency/.env` 里已经配置好：

- `E2B_DOMAIN`
- `E2B_API_KEY`
- `E2B_TEMPLATE_ID`

然后运行：

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv run python run_starting_window_probe.py \
  --concurrency 6 \
  --hold-seconds 120 \
  --timeout 180 \
  --output-json results/starting_window/001.json
```

如果你想把“快速失败”阈值调严一点：

```bash
uv run python run_starting_window_probe.py \
  --concurrency 6 \
  --hold-seconds 120 \
  --timeout 180 \
  --fast-failure-seconds 2 \
  --output-json results/starting_window/002.json
```

## 4. 怎么看结果

关注 `summary` 里的这些字段：

- `placement_failed_count`
- `fast_placement_failed_count`
- `timeout_count`
- `inferred_starting_window_pressure`
- `inferred_starting_window_size`

### 4.1 看到很多 fast placement failures

例如：

- `placement_failed_count > 0`
- `fast_placement_failed_count > 0`

这通常说明：

- 新请求在 placement 阶段就被挡住了
- 原因更像是当前 client 没有空余 `starting` 槽位

### 4.2 看到 timeout

这说明：

- placement 已经成功
- 但后面的 sandbox 创建太慢，没能在 `timeout` 内 ready

这不是同一个问题。

### 4.3 `inferred_starting_window_size`

这是一个辅助值，不是代码里的硬编码事实。

它只是告诉你：

- 这一轮 burst create 里，在出现快速 `placement_failed` 之前，成功创建了几个 sandbox

在单 client 环境里，如果这个值反复接近 `3`，就很像是撞到了当前 `starting` 窗口。

## 5. 一句话解释给别人听

你可以直接这样说：

> 这个脚本测的是“瞬时同时启动”的能力，不是最终运行容量。  
> 如果同时发起的 create 请求过多，而单节点没有足够的 `starting` 槽位，后面的请求会在 placement 阶段快速失败，常见表现是 `500: Failed to place sandbox`。

