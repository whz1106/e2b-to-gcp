# E2B GCP 环境暂停与恢复

这份文档记录当前这套 E2B GCP 环境在周末或临时不用时，如何安全暂停，后续如何恢复。

## 结论

不要直接在 GCP 控制台里对单台 VM 执行 `Stop`。

原因：

- 这些 VM 背后是 `Managed Instance Group`
- 你手动停一台，实例组会自动把它重新拉起来

正确做法是：

- 把实例组的 `target size` 调成 `0`
- 恢复时再调回原来的数量

## 当前环境已确认的实例组

我已经核对过当前环境，结果如下：

- `e2b-orch-server-rig`
  - 类型：`regional MIG`
  - 区域：`us-west1`
  - 当前副本数：`1`
- `e2b-orch-api-ig`
  - 类型：`zonal MIG`
  - 可用区：`us-west1-a`
  - 当前副本数：`1`
- `e2b-orch-build-default-rig`
  - 类型：`regional MIG`
  - 区域：`us-west1`
  - 当前副本数：`1`
- `e2b-orch-client-rig`
  - 类型：`regional MIG`
  - 区域：`us-west1`
  - 当前副本数：`1`

## 暂停方法

### 方法一：GCP 控制台

1. 进入 `Compute Engine`
2. 打开 `Instance groups`
3. 找到下面 4 个组：
   - `e2b-orch-server-rig`
   - `e2b-orch-api-ig`
   - `e2b-orch-build-default-rig`
   - `e2b-orch-client-rig`
4. 逐个执行 `Resize`
5. 把 `target size` 改成 `0`

这样整套 E2B 服务会被暂停。

### 方法二：命令行

在项目根目录执行：

```bash
gcloud compute instance-groups managed resize e2b-orch-server-rig --region us-west1 --size 0
gcloud compute instance-groups managed resize e2b-orch-api-ig --zone us-west1-a --size 0
gcloud compute instance-groups managed resize e2b-orch-build-default-rig --region us-west1 --size 0
gcloud compute instance-groups managed resize e2b-orch-client-rig --region us-west1 --size 0
```

## 恢复方法

恢复时把副本数调回当前最小运行值：

- `server = 1`
- `api = 1`
- `build = 1`
- `client = 1`

命令如下：

```bash
gcloud compute instance-groups managed resize e2b-orch-server-rig --region us-west1 --size 1
gcloud compute instance-groups managed resize e2b-orch-api-ig --zone us-west1-a --size 1
gcloud compute instance-groups managed resize e2b-orch-build-default-rig --region us-west1 --size 1
gcloud compute instance-groups managed resize e2b-orch-client-rig --region us-west1 --size 1
```

## 注意事项

- 暂停后，整套 E2B 会不可用，这是正常现象
- 恢复后需要等待几分钟，让 Nomad、API、build、client 全部重新收敛
- 如果之后再执行 `make apply`，Terraform 会按 `.env.dev` 把实例组重新调整到配置中的副本数
- `clickhouse` 和 `loki` 当前本来就是 `0`，不用额外处理

## 不推荐的操作

不要做这些：

- 直接停止单台 VM
- 手动删除正在被实例组引用的 instance template
- 只停 `server` 或只停 `api`，让剩余节点继续留着

原因：

- 单停 VM 会被实例组自动拉起
- 删模板可能影响实例组后续替换和恢复
- 部分停机会让环境处于半残状态，后续排障更麻烦

## 适合当前环境的建议

如果只是周末不使用，最简单和最安全的做法就是：

1. 把上面 4 个实例组都缩到 `0`
2. 下周再恢复到 `1`

这是当前这套环境最干净的暂停方式。
