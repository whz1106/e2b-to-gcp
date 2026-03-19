# Mac Local E2B Smoke Kit

这个目录是给本地 Mac 用的最小测试包，用来快速验证已经部署好的 GCP self-hosted E2B 是否可用。

当前建议先跑最简单的基础脚本：

- `main.py`: 最小 sandbox 测试，只做创建 sandbox、执行 `hello world`、列出根目录文件
- `smoke_basic.py`: 兼容入口，实际调用 `main.py`
- `build_custom_template.py`: 自己构建一个 code interpreter 模板的最小例子
- `smoke_full.py`: 更完整的端到端测试，会临时写数据库、创建 team/api key、再构建模板
- `requirements.txt`: Python 依赖

## 1. 安装依赖

```bash
cd codex_artifacts/kits/mac-local-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 最简单测试

这个测试就是你现在最关心的基础验证：

- 能不能创建 sandbox
- 能不能在 sandbox 里执行一段最简单的 Python 代码
- 能不能列出 sandbox 根目录文件

测试脚本核心逻辑如下：

```python
from dotenv import load_dotenv
load_dotenv()
from e2b_code_interpreter import Sandbox

sbx = Sandbox.create()
execution = sbx.run_code("print('hello world')")
print(execution.logs)

files = sbx.files.list("/")
print(files)
```

为了兼容 self-hosted 环境，仓库里的 `main.py` 额外支持从环境变量读取这些参数：

- `E2B_DOMAIN`
- `E2B_API_KEY`
- `E2B_TEMPLATE_ID`
- `E2B_TIMEOUT` 可选

如果你是 self-hosted E2B，通常至少要提供前 3 个。

### 方式一：直接 export 环境变量

```bash
export E2B_DOMAIN="agentyard.top"
export E2B_API_KEY="your_api_key"
export E2B_TEMPLATE_ID="your_template_id"
python main.py
```

### 方式二：写 `.env.local`

在当前目录创建 `.env.local`：

```bash
cat > .env.local <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=your_api_key
E2B_TEMPLATE_ID=your_template_id
E2B_TIMEOUT=120
EOF
```

然后直接运行：

```bash
python main.py
```

### 预期输出

如果跑通，你应该至少能看到类似输出：

```text
sandbox_id: ...
execution.logs: ...
files: ...
```

其中：

- `execution.logs` 里应该有 `hello world`
- `files` 应该能列出 sandbox 根目录下的一些文件或目录项

## 3. 兼容入口

如果你还想沿用旧名字，也可以直接运行：

```bash
python smoke_basic.py
```

它现在会直接调用 `main.py`。

## 4. 完整测试

如果你想测试更完整的链路，再使用：

```bash
python smoke_full.py
```

这个脚本会额外做这些事情：

- 临时往 Postgres 写入用户 / team / API key
- 构建一个临时模板
- 再用这个模板创建 sandbox

它适合做完整验证，不适合做最小起步验证。

## 5. 自己构建模板的例子

如果你想让业务代码像你给我的那段示例一样，自己先构建模板，再使用模板创建 sandbox，可以运行：

```bash
python build_custom_template.py
```

默认行为：

- 从 `e2bdev/code-interpreter:latest` 作为基础镜像开始
- 额外安装少量 Python 包
- 自动生成一个新的 alias
- 打印 `template_id`

你也可以覆盖资源：

```bash
python build_custom_template.py --cpu-count 2 --memory-mb 2048
```

这个脚本的目的不是构建完整生产模板，而是给你一个最小、可复用、符合 self-hosted E2B 的“自己构建模板”示例。

## 6. 说明

- 这次重构的目标不是覆盖所有能力，而是先验证“最基础 sandbox 是否能跑起来”。
- `main.py` 现在是最推荐的入口。
- 如果最简单脚本都跑不通，问题通常出在 API key、domain、template 或 self-hosted 集群本身，而不是复杂业务逻辑。
