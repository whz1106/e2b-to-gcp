# 如何构建模板、创建 Sandbox，并执行 Python / Bash

这份文档基于我们前面的实际验证整理，目标是把下面这条链路讲清楚：

- 如何自己构建模板
- 如何使用模板创建 sandbox
- 如何在 sandbox 中执行 Python
- 如何在 sandbox 中执行 Bash

这份说明专门面向你当前这套 self-hosted E2B。

---

## 1. 先理解三个核心概念

### 1.1 Template

`template` 是模板。

你可以把它理解成：

- 沙箱的母版
- 预装好环境的运行镜像
- sandbox 启动前的基础环境定义

模板里可以决定：

- 用什么基础镜像
- 安装哪些软件
- 启动时跑什么命令
- 哪个端口算“服务已就绪”

### 1.2 Sandbox

`sandbox` 是基于模板启动出来的实际运行实例。

你可以把它理解成：

- 真正可以操作的隔离环境
- 真正可以执行代码、读写文件、跑命令的对象

### 1.3 `template_id` 和 `sandbox_id`

这两个东西一定要分清。

- `template_id`
  - 模板 ID
  - 由 `Template.build(...)` 返回
- `sandbox_id`
  - 沙箱 ID
  - 由 `Sandbox.create(...)` 返回

所以顺序一定是：

1. 先 build 模板，得到 `template_id`
2. 再 create sandbox，得到 `sandbox_id`

---

## 2. 整体调用链路

业务代码如果自己控制模板和 sandbox，一般是这条链：

```text
Template.build(...)
-> 得到 template_id
-> Sandbox.create(template=template_id)
-> 得到 sandbox_id
-> 在 sandbox 中执行 Python / Bash
```

也就是说：

- 模板不是调用 `Sandbox.create()` 时自动生成的
- 模板必须先存在
- sandbox 是基于模板启动出来的

---

## 3. 你现在仓库里已有的两类模板构建脚本

### 3.1 通用业务模板示例

文件：

- [build_agent_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_agent_template.py)

定位：

- 业务侧自己构建模板的示例
- 用来演示“业务代码自己 build template”这条路线

特点：

- 基于 `e2bdev/code-interpreter:latest`
- 可以额外安装 Python / Node 依赖
- 会返回 `template_id`

### 3.2 专门给 `main.py` 跑通的模板

文件：

- [build_main_compatible_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_main_compatible_template.py)

定位：

- 专门为了让 `e2b_code_interpreter` 的 `run_code()` 跑通

特点：

- 基于 `e2bdev/code-interpreter:latest`
- 显式设置 code interpreter 的启动命令
- 显式等待 `49999` 端口 ready
- 这是目前已经实测跑通 `main.py` 的版本

---

## 4. 如何构建模板

进入目录：

```bash
cd /home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit
```

安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

准备环境变量：

```bash
cat > .env.local <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=你的key
EOF
```

### 4.1 构建通用业务模板

```bash
python build_agent_template.py
```

成功后会打印类似：

```text
alias: dynamic_agent_sandbox_xxx
template_id: xxxxxxxxxxxxxxxxxxxx
build_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 4.2 构建可直接跑 `run_code()` 的模板

```bash
python build_main_compatible_template.py
```

成功后会打印类似：

```text
alias: main-code-interpreter_xxx
template_id: xxxxxxxxxxxxxxxxxxxx
build_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

如果你的目标是：

```python
sbx.run_code("print('hello world')")
```

优先用这一种。

---

## 5. 如何创建 Sandbox

模板 build 完之后，拿到 `template_id`，再创建 sandbox。

最小例子：

```python
from e2b_code_interpreter import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="你的_template_id",
    timeout=120,
)

print(sbx.sandbox_id)
```

这里返回的：

- `sbx.sandbox_id`

就是实际沙箱实例 ID。

---

## 6. 如何在 Sandbox 中运行 Python

这里分两种方式。

### 6.1 方式一：用 `e2b_code_interpreter` 的 `run_code()`

这是你前面 `main.py` 用的方式。

示例：

```python
from dotenv import load_dotenv
load_dotenv()

from e2b_code_interpreter import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="你的_template_id",
)

execution = sbx.run_code("print('hello world')")
print(execution.logs)
```

适用场景：

- 你要直接执行 Python 代码片段
- 你要得到结构化执行结果
- 你正在使用 `e2b_code_interpreter`

注意：

- 这要求模板本身支持 code interpreter
- 普通 `base` 模板不一定行
- 我们已经实测，使用 [build_main_compatible_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_main_compatible_template.py) 构建出的模板可以跑通

### 6.2 方式二：用普通命令执行 Python

如果你不依赖 `run_code()`，也可以直接在 sandbox 里执行 Python 命令：

```python
from e2b import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="你的_template_id",
)

result = sbx.commands.run("python3 -c \"print('hello from python')\"")
print(result.exit_code)
print(result.stdout)
print(result.stderr)
```

适用场景：

- 你只是想跑 Python 命令
- 你不需要 `e2b_code_interpreter` 的上下文能力
- 你想兼容普通 sandbox

---

## 7. 如何在 Sandbox 中运行 Bash

运行 Bash 最直接的方式就是 `commands.run(...)`。

示例：

```python
from e2b import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="你的_template_id",
)

result = sbx.commands.run("echo hello-from-bash && uname -a")
print(result.exit_code)
print(result.stdout)
print(result.stderr)
```

如果你要执行多行 Bash：

```python
from e2b import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="你的_template_id",
)

result = sbx.commands.run(
    "bash -lc '\n"
    "echo start\n"
    "pwd\n"
    "ls -la /\n"
    "'"
)

print(result.stdout)
print(result.stderr)
```

适用场景：

- 安装工具
- 调试环境
- 查看文件系统
- 跑 shell 脚本

---

## 8. 推荐的实际使用方式

### 场景 A：你要跑 `run_code()`

推荐顺序：

1. 用 [build_main_compatible_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_main_compatible_template.py) 构建模板
2. 记下输出的 `template_id`
3. 用 `e2b_code_interpreter.Sandbox.create(template=template_id)`
4. 再执行 `run_code()`

### 场景 B：你只是要跑 Python / Bash 命令

推荐顺序：

1. 用 [build_agent_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_agent_template.py) 或其他普通模板构建脚本 build 模板
2. 用普通 `e2b.Sandbox.create(...)`
3. 用 `commands.run(...)` 运行：
   - `python3 -c "..."`
   - `bash -lc "..."`

---

## 9. 一个完整最小示例

### 第一步：构建模板

```bash
cd /home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit
source .venv/bin/activate
python build_main_compatible_template.py
```

拿到：

```text
template_id: sz0vk8nn2cgp45hvt8eb
```

### 第二步：用模板创建 sandbox 并运行 Python

```python
from e2b_code_interpreter import Sandbox

sbx = Sandbox.create(
    domain="agentyard.top",
    api_key="e2b_xxx",
    template="sz0vk8nn2cgp45hvt8eb",
)

execution = sbx.run_code("print('hello world')")
print(execution.logs)
```

### 第三步：在同一个 sandbox 里运行 Bash

```python
result = sbx.commands.run("echo hello-from-bash")
print(result.stdout)
```

---

## 10. 最后的结论

把这件事压缩成一句最实用的话：

先 `build template`，拿到 `template_id`；  
再 `create sandbox`，拿到 `sandbox_id`；  
最后在 sandbox 里选择用 `run_code()` 跑 Python，或者用 `commands.run()` 跑 Python/Bash。

如果你用的是 `e2b_code_interpreter`，并且想跑：

```python
sbx.run_code("print('hello world')")
```

那优先使用：

- [build_main_compatible_template.py](/home/ubuntu/whz/infra/codex_artifacts/kits/custom-template-kit/build_main_compatible_template.py)
