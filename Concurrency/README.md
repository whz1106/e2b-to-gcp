# Sandbox Concurrency Test

这个目录用于本次 sandbox 并发测试，默认面向你当前的单机 `client` 环境：

- `client` 数量：`1`
- 机型：`n2-standard-2`
- 规格：`2 vCPU / 8 GB RAM`
- boot disk：`80 GB`
- data disk：`~50 GB`

这次测试的目标不是一次性打满生产能力，而是先测清楚：

1. 当前 team 的并发额度是否已经放开
2. 单台 `client` 在轻量负载下大概能承受多少个 sandbox
3. 当并发继续升高时，失败是来自 team 限额、API、还是 `client` 容量

## 文件说明

- `run_concurrency_test.py`
  - 并发创建 sandbox
  - 在每个 sandbox 中执行一个轻量命令
  - 持有一段时间，模拟真实占用
  - 输出汇总结果和失败详情
- `TEAM_APIKEY_TEMPLATE_SETUP.md`
  - 说明如何生成新的 `team_id`
  - 说明如何拿到新的 `E2B_API_KEY`
  - 说明 `base_v1` 和 `base` 的区别
  - 说明如何给新 team 准备可用模板
- `run_concurrency_profile_test.py`
  - 在并发创建 sandbox 的同时执行更接近真实情况的 workload
  - 支持 `light`、`cpu`、`memory`、`io`、`network`、`mixed`
  - 输出结构和轻量脚本一致风格的 JSON
- `run_staggered_concurrency_test.py`
  - 按固定时间间隔逐个创建 sandbox
  - 用来测试错峰启动和批次间隔对成功率的影响
  - 默认可直接用于“每 10 秒创建 1 个 sandbox”的场景
  - 支持 create 失败后每隔固定时间重试，并记录成功前的运行中 sandbox 数量变化
- `plot_results.py`
  - 读取 `results/` 下的 JSON 结果
  - 输出汇总 CSV、Markdown 表格和 PNG 图表

## 目录整理

为了便于后续继续扩展测试，新增了按场景划分的入口目录：

```text
scenarios/
  burst/
    run.py
    plot.py
  staggered/
    run.py
    plot.py
  profile/
    run.py
    plot.py
```

说明：

- `run.py` 是该场景的测试入口
- `plot.py` 是该场景的绘图入口
- 根目录下原有脚本仍然保留，作为共享实现和兼容入口

## 环境准备

建议用 `uv` 管理这个目录下的 Python 环境和依赖：

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv sync
```

准备当前目录下的 `.env` 文件。脚本会默认先读取 `.env`：

```bash
cat > /home/ubuntu/whz/infra/Concurrency/.env <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=你的_team_api_key
E2B_TEMPLATE_ID=你的_template_id
EOF
```

之后直接运行测试脚本即可，不需要每次手动 `export` 这三个变量。

默认情况下，测试脚本会在开始前检查当前 team 下是否还有运行中的 sandbox：

- 最多等待 `240s`
- 每 `10s` 轮询一次
- 确认环境清空后才开始正式测试

如果你希望脚本在开始前主动清理残留 sandbox，可以额外传：

```bash
--force-cleanup-before-start
```

## 测试原则

这次建议只测 sandbox 并发，不测 template build 并发。

所以：

- 所有请求都使用同一个已经可用的 `template_id`
- 不要一边 build template 一边做并发测试
- 每轮测试后先看结果，再决定是否继续升高并发

## 推荐测试流程

建议把所有测试结果按“测试主题 / profile-并发 / 序号”来组织，例如：

```bash
mkdir -p /home/ubuntu/whz/infra/Concurrency/results/test_base/light-2
mkdir -p /home/ubuntu/whz/infra/Concurrency/results/test_base/light-5
mkdir -p /home/ubuntu/whz/infra/Concurrency/results/test_base/light-10
```

推荐目录结构：

```text
results/
  test_base/
    light-2/
      001.json
      002.json
    light-5/
      001.json
    light-10/
      001.json
    light-15/
      001.json
    light-20/
      001.json
```

如果后面做复杂 workload，也保持同样思路：

```text
results/
  test_base/
    cpu-5/
      001.json
    memory-5/
      001.json
    mixed-10/
      001.json
```

### 第 1 轮：2 并发

```bash
cd /home/ubuntu/whz/infra/Concurrency
uv run python run_concurrency_test.py \
  --concurrency 2 \
  --hold-seconds 120 \
  --timeout 300 \
  --output-json results/test_base/light-2/001.json
```

关注点：

- 是否全部创建成功
- sandbox 内轻量命令是否都成功
- 平均创建时长是否正常

### 第 2 轮：5 并发

```bash
uv run python run_concurrency_test.py \
  --concurrency 5 \
  --hold-seconds 180 \
  --timeout 300 \
  --output-json results/test_base/light-5/001.json
```

如果 2 并发稳定，再升到 5。

### 第 3 轮：10 并发

```bash
uv run python run_concurrency_test.py \
  --concurrency 10 \
  --hold-seconds 180 \
  --timeout 300 \
  --output-json results/test_base/light-10/001.json
```

如果 5 并发还稳定，再试 10。

### 第 4 轮：15 或 20 并发

```bash
uv run python run_concurrency_test.py \
  --concurrency 15 \
  --hold-seconds 180 \
  --timeout 300 \
  --output-json results/test_base/light-15/001.json

uv run python run_concurrency_test.py \
  --concurrency 20 \
  --hold-seconds 180 \
  --timeout 300 \
  --output-json results/test_base/light-20/001.json
```

这一轮才接近你当前单机上限的探索区间。

### 错峰测试：每 10 秒创建 1 个

```bash
uv run python run_staggered_concurrency_test.py \
  --count 10 \
  --interval-seconds 10 \
  --hold-seconds 180 \
  --timeout 200 \
  --retry-on-create-failure \
  --retry-interval-seconds 2 \
  --output-json results/test_base/staggered-1x10s/001.json
```

这个脚本适合用来观察：

- 前一批请求是否已经被系统消化
- 批次间隔对成功率的影响
- 错峰启动时的稳定创建能力

如果要继续逼近“当前服务器能同时存在多少个 sandbox”，建议直接开启 create 重试：

```bash
uv run python run_staggered_concurrency_test.py \
  --count 30 \
  --interval-seconds 10 \
  --hold-seconds 300 \
  --timeout 200 \
  --retry-on-create-failure \
  --retry-interval-seconds 2 \
  --pause-scheduling-on-create-failure \
  --stop-scheduling-on-terminal-create-error \
  --output-json results/test_base/staggered-retry-1x10s/001.json
```

这个模式会把后面的 worker 调度压住，直到当前这个 create 失败中的 worker 最终成功或最终失败。它更适合用来逼近“当前同时能存在几个 sandbox”的上限，而不是单纯看一次性并发创建吞吐。

这个模式会把下面这些信息写进 JSON 结果里：

- `first_failure_running_count`
- `last_observed_running_count_before_success`
- `retry_running_count_min`
- `retry_running_count_max`
- `success_after_running_count_drop`
- `retry_observations`

其中 `success_after_running_count_drop=true` 可以用来辅助判断：新的 sandbox 是否更像是在旧 sandbox 销毁、运行中数量下降之后才终于创建成功。

如果你只是想让脚本在 create 失败后继续重试，但不想暂停后续 worker，可以不加 `--pause-scheduling-on-create-failure`。

如果你想给重试设置硬上限，可以再加 `--retry-max-seconds`；默认 `0` 表示不限时长。

当前脚本会优先把 `placement_failed`、`api_limit`、`timeout`、部分 `500/server_error` 这类更像容量/调度问题的 create 错误当作可重试错误；像 `404/not_found` 这类更像终态异常的错误不会继续重试。

如果你加上 `--stop-scheduling-on-terminal-create-error`，一旦出现这种非容量型 create 错误，后面的 worker 就不会继续提交，这样结果会更干净。

## 如何理解结果

### 情况 1：报 `429`

这通常说明不是机器先满，而是 team 并发额度先拦住了。

### 情况 2：创建明显变慢、部分超时、失败不是 `429`

这通常更像是：

- 单台 `client` 容量开始紧张
- 调度变慢
- sandbox 启动时间变长

### 情况 3：sandbox 创建成功，但命令执行慢或失败

这说明机器已经能开起来这些 sandbox，但运行期资源开始紧张。

## 关于“暂停”是否占资源

对这次测试，统一按这个原则理解：

- sandbox 只要还没结束或销毁，就默认它还占资源
- 不要把“暂停”理解成“完全不占宿主机资源”

所以脚本默认在测试结束后会自动清理 sandbox，避免残留占用。

## 推荐命令

默认轻量命令：

```bash
python3 -c "print('concurrency-ok')"
```

如果你想改成更轻或更重的命令，可以传：

```bash
uv run python run_concurrency_test.py \
  --concurrency 5 \
  --hold-seconds 180 \
  --command "python3 -c \"print('hello')\""
```

## 保留 sandbox 方便排查

如果你想保留成功创建的 sandbox，不要自动清理：

```bash
uv run python run_concurrency_test.py --concurrency 5 --hold-seconds 180 --no-cleanup
```

## 建议的起步结论标准

你可以按这个标准记结果：

- `2` 并发稳定：说明基础链路正常
- `5` 并发稳定：说明单机轻量负载具备初步并发能力
- `10` 并发稳定：说明当前单机 client 已经有一定可用性
- `15+` 开始失败或明显变慢：大概率接近你当前单机配置上限

## 下一步怎么做

如果单机测试完成后你要扩大能力，再做这两件事：

1. 把 `CLIENT_CLUSTERS_CONFIG` 的 `cluster_size` 和 `autoscaler.size_max` 调大
2. 重复同样的脚本，对比单机和多机的结果差异

## 第二阶段：复杂 workload 测试

当第一阶段轻量并发测试完成后，可以继续用第二个脚本做更接近真实情况的 sandbox 测试：

- `light`
- `cpu`
- `memory`
- `io`
- `network`
- `mixed`

### CPU 型

```bash
uv run python run_concurrency_profile_test.py \
  --profile cpu \
  --concurrency 5 \
  --hold-seconds 120 \
  --timeout 300 \
  --output-json results/test_base/cpu-5/001.json
```

### 内存型

```bash
uv run python run_concurrency_profile_test.py \
  --profile memory \
  --concurrency 5 \
  --hold-seconds 120 \
  --timeout 300 \
  --memory-mb 256 \
  --output-json results/test_base/memory-5/001.json
```

### I/O 型

```bash
uv run python run_concurrency_profile_test.py \
  --profile io \
  --concurrency 5 \
  --hold-seconds 120 \
  --timeout 300 \
  --io-mb 100 \
  --output-json results/test_base/io-5/001.json
```

### 网络型

```bash
uv run python run_concurrency_profile_test.py \
  --profile network \
  --concurrency 5 \
  --hold-seconds 120 \
  --timeout 300 \
  --output-json results/test_base/network-5/001.json
```

### 混合型

```bash
uv run python run_concurrency_profile_test.py \
  --profile mixed \
  --concurrency 5 \
  --hold-seconds 120 \
  --timeout 300 \
  --memory-mb 256 \
  --output-json results/test_base/mixed-5/001.json
```

## JSON 输出

两个脚本都支持：

```bash
--output-json <path>
```

并且输出结构是统一风格的，顶层包含：

- `meta`
- `summary`
- `results`

轻量脚本的 `meta` 里包含：

- `test_id`
- `test_time`
- `environment`
- `domain`
- `template_id`
- `concurrency`
- `hold_seconds`
- `timeout`
- `cleanup`
- `command`

复杂 workload 脚本在上面基础上还会增加：

- `profile`
- `network_url`
- `io_mb`
- `memory_mb`

两个脚本都会自动创建 `--output-json` 对应的父目录，因此可以直接写到：

```bash
results/test_base/light-5/001.json
results/test_base/cpu-5/001.json
results/test_base/mixed-10/001.json
```

## 结果绘图

当你已经在例如 `results/test_base` 目录里按上述结构积累了多轮 JSON 后，可以直接画图：

```bash
uv run python plot_results.py \
  --input-dir results/test_base \
  --output-dir plots/test_base
```

这会生成：

- `summary.csv`
- `summary.md`
- `success_rate.png`
- `durations.png`
- `failures.png`
- `error_types.png`

如果你后面换成别的目录，例如 `results/cpu_profile`，也可以直接指定对应路径。
