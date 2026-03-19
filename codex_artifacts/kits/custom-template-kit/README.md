# Custom Template Kit

这个目录演示的是：

- 业务代码自己调用 E2B SDK 构建模板
- 不是调用 `packages/shared` 里的 `make build-base-template`
- 也不是依赖管理员预先初始化一个固定 `base`

适用场景：

- 你已经有可用的 `E2B_DOMAIN`
- 你已经有可用的 `E2B_API_KEY`
- 你希望业务侧按自己的要求创建模板

## 1. 安装依赖

```bash
cd codex_artifacts/kits/custom-template-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 准备环境变量

可以直接导出：

```bash
export E2B_DOMAIN="agentyard.top"
export E2B_API_KEY="your_api_key"
```

或者写 `.env.local`：

```bash
cat > .env.local <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=your_api_key
EOF
```

## 3. 构建一个自己的模板

```bash
python build_agent_template.py
```

默认行为：

- 基于 `e2bdev/code-interpreter:latest`
- 额外安装少量 Python 和 Node 依赖
- 自动生成一个唯一 alias
- 打印 `template_id` / `build_id`

## 4. 构建一个能跑 `main.py` 的模板

如果你的目标是跑这类代码：

```python
from e2b_code_interpreter import Sandbox

sbx = Sandbox.create()
execution = sbx.run_code("print('hello world')")
print(execution.logs)
```

优先使用：

```bash
python build_main_compatible_template.py
```

这个脚本会：

- 基于 `e2bdev/code-interpreter:latest`
- 显式设置 code interpreter 启动命令 `/root/.jupyter/start-up.sh`
- 显式等待端口 `49999`
- 默认资源使用 `2 CPU / 2048 MB`

你也可以覆盖资源：

```bash
python build_main_compatible_template.py --cpu-count 2 --memory-mb 3072
```

## 5. 覆盖资源和 alias

```bash
python build_agent_template.py \
  --alias my-agent-template \
  --cpu-count 2 \
  --memory-mb 2048
```

## 6. 这和 `make build-base-template` 的区别

- `make build-base-template`：infra 侧预先构建一个固定 `base`
- 这里的脚本：业务代码自己定义模板内容并调用 `Template.build(...)`

也就是说，这里更接近你给我的那段业务代码思路：

```python
template = Template().from_base_image()
...
Template.build(template, alias=alias)
```

## 7. 使用构建出来的模板

构建成功后，脚本会打印：

- `alias`
- `template_id`
- `build_id`

后续创建 sandbox 时，可以优先直接使用 `template_id`，例如：

```python
from e2b_code_interpreter import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="<template_id>",
)
```

## 8. 注意

- 这个目录是“业务侧自建模板”示例，不负责管理员初始化。
- 你仍然需要先有一把可用的 `E2B_API_KEY`。
- 模板越重，构建越慢，对集群构建资源要求越高。
