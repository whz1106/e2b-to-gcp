# test-3.18

这个目录是一个最小示例工程，按“一个功能一个文件”的方式拆开：

- 构建模板
- 创建 sandbox
- 在 sandbox 里执行 Python
- 在 sandbox 里执行 Bash
- 文件上传
- 文件下载
- 目录查看
- 网络访问
- 手动销毁 sandbox

## 1. 安装依赖

```bash
cd /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 准备环境变量

```bash
cat > /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/.env.local <<'EOF'
E2B_DOMAIN=agentyard.top
E2B_API_KEY=你的_API_KEY
EOF
```

说明：
- 这套脚本固定读取和写入 [test-3.18/.env.local](/home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/.env.local)
- 所以你在任何目录执行都可以，不需要先 `cd` 到 `test-3.18`

## 3. 文件说明

- `common.py`
  - 公共常量和环境变量加载
- `create_template.py`
  - 构建支持 `run_code()` 的模板
- `create_sandbox.py`
  - 基于模板创建 sandbox
- `run_python.py`
  - 连接已有 sandbox，执行 Python 代码
- `run_bash.py`
  - 连接已有 sandbox，执行 Bash 命令
- `upload_file.py`
  - 把本地文件写入 sandbox
- `download_file.py`
  - 把 sandbox 文件保存回本地
- `list_directory.py`
  - 查看 sandbox 目录内容
- `network_check.py`
  - 验证 sandbox 是否能访问外网
- `close_sandbox.py`
  - 手动销毁 sandbox

## 4. 使用顺序

### 第一步：构建模板

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/create_template.py
```

你会得到：

- `template_id`
- `build_id`
- `alias`
- 脚本会自动把 `template_id` 写入 `.env.local` 的 `E2B_TEMPLATE_ID`

### 第二步：创建 sandbox

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/create_sandbox.py
```

你会得到：

- `sandbox_id`
- 脚本默认从 `.env.local` 读取 `E2B_TEMPLATE_ID`
- 脚本会自动把 `sandbox_id` 写入 `.env.local` 的 `E2B_SANDBOX_ID`

### 第三步：在 sandbox 里执行 Python

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/run_python.py
```

默认执行：

```python
print('hello world')
```

也可以自定义：

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/run_python.py --code "x = 1\nprint(x + 1)"
```

### 第四步：在 sandbox 里执行 Bash

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/run_bash.py
```

默认执行：

```bash
bash -lc 'echo hello-from-bash && python3 --version'
```

也可以自定义：

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/run_bash.py --command "bash -lc 'pwd && ls -la /'"
```

### 第五步：上传本地文件到 sandbox

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/upload_file.py
```

默认会把：
- [sample_upload.txt](/home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/sample_upload.txt)

上传到：
- `/tmp/test-3.18/sample_upload.txt`

### 第六步：查看 sandbox 目录

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/list_directory.py
```

### 第七步：把 sandbox 文件下载回本地

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/download_file.py
```

默认会保存到：
- [downloaded_sample.txt](/home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/downloaded_sample.txt)

### 第八步：验证 sandbox 外网访问

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/network_check.py
```

### 第九步：手动销毁 sandbox

```bash
python /home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/close_sandbox.py
```

## 5. 说明

- 这个目录故意按功能拆开，便于你逐步验证每一层能力。
- `create_template.py` 负责模板，不返回 `sandbox_id`。
- `create_sandbox.py` 负责 sandbox，返回 `sandbox_id` 并写入 `.env.local`。
- `run_python.py` 和 `run_bash.py` 默认从 `.env.local` 读取 `E2B_SANDBOX_ID` 做执行验证。
- `upload_file.py` / `download_file.py` / `list_directory.py` / `network_check.py` 也默认从 `.env.local` 读取 `E2B_SANDBOX_ID`。
- sandbox 在创建时带有 `timeout`，到期后平台会自动销毁。
- 如果你不想等超时，可以手动执行 `close_sandbox.py` 立即销毁。
