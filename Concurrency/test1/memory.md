# Test1 Memory

这份文件用于记录 `Concurrency/test1` 目录下并发测试脚本的使用方式、参数语义、维护注意点，以及当前已经得到的经验结论。

核心脚本：

- [run_running_capacity_probe.py](/home/ubuntu/whz/infra/Concurrency/test1/run_running_capacity_probe.py)

现有说明文档：

- [RUNNING_CAPACITY_PROBE_ZH.md](/home/ubuntu/whz/infra/Concurrency/test1/RUNNING_CAPACITY_PROBE_ZH.md)

## 1. 这个脚本测什么

这个脚本测的不是 burst create，也不是 `starting` 窗口本身，而是：

- 单节点最终能稳定同时运行多少个 sandbox
- 当首次失败发生后，等第一个成功 sandbox 销毁，再补一个新的 sandbox，是否能成功
- 从旧 sandbox 释放到新 sandbox 成功 ready，中间间隔了多久

测试方法是：

1. 每隔固定秒数发起一个新的 sandbox create
2. 每个 sandbox 内启动一个后台 `sleep`
3. sandbox 在整个生命周期内保持占位
4. 首次 create 失败后，停止继续追加新的 sandbox
5. 等第一个成功 sandbox 结束，再按固定重试间隔去补位
6. 记录补位尝试次数、创建耗时、成功时间点

## 2. 环境与默认行为

脚本默认从下面两个文件加载环境变量：

- [Concurrency/.env](/home/ubuntu/whz/infra/Concurrency/.env)
- [Concurrency/.env.local](/home/ubuntu/whz/infra/Concurrency/.env.local)

需要的核心变量：

- `E2B_DOMAIN`
- `E2B_API_KEY`
- `E2B_TEMPLATE_ID`

如果命令行传了 `--template-id`，会覆盖 `E2B_TEMPLATE_ID`。

## 3. 关键参数说明

### 3.1 容量探测参数

- `--max-sandboxes`
  最多尝试创建多少个 sandbox。
  常用值：`6`

- `--interval-seconds`
  初始阶段两个 sandbox create 之间的间隔。
  当前常用值：`10`

- `--retry-after-release-seconds`
  首次失败后，等第一个成功 sandbox 结束，再额外等待多少秒后重试补位。
  当前常用值：`5`

### 3.2 sandbox 生命周期相关

- `--sandbox-timeout`
  这是最重要的参数之一。
  它不是 create 请求超时，而是 **sandbox 生命周期**。
  sandbox 会从 create 请求发出开始算，存活这么多秒。
  当前建议值：`200`

### 3.3 请求相关 timeout

- `--create-request-timeout`
  控制 `Sandbox.create()` 这个 HTTP 请求本身最多等多久。
  `0` 表示不限制。
  当前建议值：`0`

- `--command-timeout`
  控制在 sandbox 里执行“启动后台 sleep”这条命令的请求超时。
  不是 `sleep` 本身持续多久。
  当前建议值：`30`

## 4. 当前推荐命令

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

## 5. 终端会打印什么

### 5.1 初始阶段

- `[SUBMIT]`
  某个 worker 开始提交 create 请求

- `[OK]`
  某个 sandbox 成功创建并成功启动后台 `sleep`

- `[FAIL] phase=initial:create`
  初始 create 阶段失败，通常是 `placement_failed`

- `[FIRST_FAILURE]`
  第一次失败的 worker，会额外汇总打印一次

### 5.2 等待释放与补位阶段

- `[WAITING]`
  表示脚本现在阻塞等待某个已成功 sandbox 对应的 future 结束

- `[WAIT_RELEASE]`
  表示已经确定要等哪个 sandbox 结束，以及结束后再等待几秒再重试

- `[RUNNING]`
  每次补位重试前都会打印当前 `Sandbox.list()` 看到的 running 数量和 sandbox_id 列表

- `[RETRY]`
  表示第几次补位重试开始

- `[RETRY_SUCCESS]`
  表示第几次重试成功，以及：
  - 从第一个成功 sandbox 结束，到新 sandbox ready 间隔了多久
  - 新 sandbox 的 create 耗时是多少

## 6. 终端时间字段说明

每个 `[OK]` / `[FAIL]` 里都会打印：

- `create`
  `Sandbox.create(...)` 耗时

- `command`
  在 sandbox 内启动后台 `sleep` 这条命令的耗时
  不是 `sleep` 本身持续了多久

- `timeline.started`
  该 sandbox 的 create 请求发起时间，按整轮测试开始后的偏移秒数表示

- `timeline.ready`
  该 sandbox create 完成并且后台 `sleep` 启动完成的时间

- `timeline.finished`
  该 sandbox 对应 worker 结束的时间

`finished - started` 就是这个 sandbox 从开始到结束所经历的总时长。

## 7. JSON 结果里重点看什么

输出文件在 `--output-json` 指定的路径。

`summary` 里最重要的字段：

- `first_failure_index`
- `first_failure_error`
- `stable_running_capacity_estimate`
- `first_placement_failure_index`
- `retry_attempt_count_after_first_release`
- `retry_success_after_first_release`
- `retry_create_seconds_after_first_release`
- `retry_started_offset_seconds`
- `retry_finished_offset_seconds`

`summary.timeline` 里重要字段：

- `started_offset_seconds`
- `ready_offset_seconds`
- `finished_offset_seconds`
- `create_seconds`

## 8. 当前已观察到的现象

这套测试已经多次观察到：

- 单节点稳定同时运行容量不是完全固定
- 有时稳定容量是 `4`
- 有时稳定容量是 `5`
- 即使旧 sandbox 已销毁，新 sandbox 也不一定立刻能补进去
- 经常要再等若干秒，甚至再多次重试，placement 才会成功

因此当前更稳妥的表达是：

- 单节点稳定 running capacity 大概率在 `4~5` 之间波动
- `5` 不是每次都稳定

## 9. 维护注意点

### 9.1 不要把几个 timeout 混在一起

一定要分清：

- `sandbox_timeout`
  sandbox 生命周期

- `create_request_timeout`
  create 请求本身超时

- `command_timeout`
  启动后台 `sleep` 的命令请求超时

### 9.2 不要再恢复旧的前台长循环命令

之前试过让 `commands.run()` 前台跑长时间循环，这会和 SDK 的命令连接超时混在一起，导致误判。

当前方案是：

- sandbox 内只启动后台 `sleep`
- 不再用前台长命令占住请求

### 9.3 如果再次怀疑“上一轮没清干净”

先看两处：

- 开头是不是 `precheck: environment is clean`
- 重试前 `[RUNNING]` 打印出的数量和 sandbox_id

如果开头已经 clean，而重试前 running 数量也在下降，那通常更像是：

- 资源释放延迟
- placement 可用状态恢复慢

而不一定是脚本残留

### 9.4 当前脚本的一个已知偏差

“第一个 sandbox 结束后多久新 sandbox 能起”这个时间，脚本已经可以测，但还不是最理想的精确实现。
因为它当前是在主线程回收结果和等待 future 的过程中再进入补位逻辑，所以补位开始时机可能比理论最早时间稍晚。

这不影响“能不能补进去”的结论，但会影响“绝对延迟秒数”的精确度。

## 10. 如果服务器断掉，接手时优先做什么

1. 先读这份文件
2. 读取完这份文件后，先建立两个 subagent：
   - 一个用于代码编写
   - 一个用于代码审查
2. 再读 [RUNNING_CAPACITY_PROBE_ZH.md](/home/ubuntu/whz/infra/Concurrency/test1/RUNNING_CAPACITY_PROBE_ZH.md)
3. 确认 `Concurrency/.env` 里的 `E2B_DOMAIN / E2B_API_KEY / E2B_TEMPLATE_ID`
4. 用推荐命令先跑一轮 `max-sandboxes=6`
5. 对比 `stable_running_capacity_estimate`
6. 再看 `retry_attempt_count_after_first_release` 和 `timeline`

## 11. 当前已建立的 subagent

为了后续继续处理这套测试，当前线程已经建立了两个 subagent：

- 代码编写：`Helmholtz`
- 代码审查：`McClintock`

后续如果继续修改 `test1` 目录下的脚本或文档，可以继续复用这两个 agent 的职责分工。
