# Running Capacity Probe

这份文档对应脚本：

- [run_running_capacity_probe.py](/home/ubuntu/whz/infra/Concurrency/test1/run_running_capacity_probe.py)

它的目标不是测 burst create，而是更接近下面这个问题：

> 单台 `client` 服务器里，最终能同时稳定运行多少个 sandbox？

## 1. 测试思路

脚本按下面的方式工作：

1. 每隔 `10s` 发起 1 个新的 sandbox create
2. 每个 sandbox 创建成功后，先在 sandbox 内启动一个后台 `sleep` 进程
3. sandbox 在其生命周期内保持占位，脚本不再做周期性心跳检查
4. 每个 sandbox 在这段时间里持续占用运行资源
5. 一旦创建到某个序号开始失败，就停止继续追加新的 sandbox
6. 等第一个成功 sandbox 销毁，再额外等待 `5s`
7. 再次尝试创建 1 个 sandbox，观察它能否补位成功，并记录这个新 sandbox 的启动时间

这个脚本主要想回答两个问题：

- 第一次失败发生在第几个 sandbox？
- 最早创建的 sandbox 结束后，新的 sandbox 能不能成功补进来？

## 2. 为什么这样设计

这里测的不是：

- 瞬时 burst create
- `starting` 窗口

而是更偏向：

- 最终 running sandbox 容量

`starting=3` 只限制同一时刻处于启动中的 sandbox 数量，不等于最终同时运行数量。

所以这里采用：

- 错峰创建
- 长时间存活
- 首次失败后暂停继续加压
- 等旧 sandbox 释放后再补一个

这样更容易看清：

- 当前服务器最多能稳定留住多少个 sandbox
- 新 sandbox 是否依赖旧 sandbox 释放后才能创建成功

## 3. sandbox 内运行什么

默认保活命令不是前台长循环，而是后台 `sleep`：

- `nohup python3 -c "import time; time.sleep(HOLD_SECONDS)" &`

它会快速返回，不会占住一次长时间的 `commands.run()` 请求。

这样可以帮助确认：

- sandbox 不只是“创建成功一下”
- 而是在整个存活时间内有后台 `sleep` 占位

## 4. 推荐命令

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv run python test1/run_running_capacity_probe.py \
  --max-sandboxes 12 \
  --interval-seconds 10 \
  --sandbox-timeout 200 \
  --create-request-timeout 0 \
  --command-timeout 30 \
  --retry-after-release-seconds 5 \
  --output-json results/test1/001.json
```

如果你已经明确只想用某个模板，比如 `test1`：

```bash
uv run python test1/run_running_capacity_probe.py \
  --template-id test1 \
  --max-sandboxes 12 \
  --interval-seconds 10 \
  --sandbox-timeout 200 \
  --create-request-timeout 0 \
  --command-timeout 30 \
  --retry-after-release-seconds 5 \
  --output-json results/test1/002.json
```

注意：

- `--sandbox-timeout` 控制 sandbox 生命周期，也就是这次测试里单个 sandbox 的占位时长
- `--create-request-timeout` 控制 `Sandbox.create()` 这次 HTTP 请求本身能等多久
- `--command-timeout` 控制后台 `sleep` 启动命令这一次请求能跑多久

## 6. 时间轴输出

`summary.timeline` 会输出每个 sandbox 的关键时间点：

- `started_offset_seconds`
- `finished_offset_seconds`
- `create_seconds`

另外补位 sandbox 还会额外输出：

- `retry_create_seconds_after_first_release`
- `retry_started_offset_seconds`
- `retry_finished_offset_seconds`

## 5. 如何理解结果

重点看 `summary` 里的这些字段：

- `first_failure_index`
- `first_failure_error`
- `initial_success_count_before_failure`
- `max_simultaneous_running_estimate`
- `retry_attempted_after_first_release`
- `retry_success_after_first_release`

### 5.1 第一次失败

如果脚本第一次失败出现在：

- `first_failure_index = 6`

而此前有：

- `initial_success_count_before_failure = 5`

那么可以先粗略理解为：

- 当前大约能同时稳定运行 `5` 个 sandbox

### 5.2 等最早 sandbox 结束后的补位

如果：

- `retry_success_after_first_release = true`

那么通常说明：

- 新的 sandbox 很可能是等旧 sandbox 释放后才补位成功

如果是 `false`，说明：

- 即使最早一个 sandbox 结束后，新的也未必能立刻补进来

## 6. 一句话解释给别人听

你可以直接这样说：

> 我们不是在测瞬时启动并发，而是在测单节点最终能稳定运行多少个 sandbox。  
> 方法是每隔 10 秒创建 1 个 sandbox，让每个 sandbox 内持续运行 200 秒；创建到首次失败时停止继续加压，再等最早的 sandbox 结束后额外等待 5 秒，观察新的 sandbox 是否能补位成功。
