# GCP 虚拟机参数调整与替换说明

这份文档说明在当前 E2B GCP 部署中，如何调整虚拟机的 CPU、内存、系统盘、外挂磁盘，改动后会发生什么，以及“旧虚拟机怎么删、新虚拟机怎么加”。

适用范围：

- 当前仓库 [`/home/ubuntu/whz/infra`](/home/ubuntu/whz/infra)
- GCP 部署
- 当前环境主要参考 `dev`

---

## 1. 先说结论

这套架构里，虚拟机不是手工一台一台维护的，而是通过：

- Terraform
- GCE Instance Template
- Managed Instance Group，简称 `MIG`

统一管理。

所以你调整参数时，**正确做法不是手工删老机器再手工建新机器**，而是：

1. 改 `.env.dev` 或 Terraform 参数
2. `make plan`
3. `make apply`

然后系统会自动：

1. 生成新的 instance template
2. 实例组切换到新模板
3. 拉起新的 VM
4. 停掉并删除旧 VM

也就是说，绝大多数情况下：

- **你是“改配置”**
- **Terraform/MIG 负责“删旧建新”**

---

## 2. 当前有哪些虚拟机类型

当前这套 E2B 在 GCP 上主要有这些节点：

1. `server`
   - 控制面
   - 负责 Nomad / Consul

2. `api`
   - 对外 API
   - 内部协调入口

3. `build`
   - 构建 template
   - 处理镜像和依赖

4. `client`
   - 执行 sandbox
   - 真正跑用户工作负载

5. `clickhouse`
   - 可选
   - 分析/日志/事件存储

你当前主要在用前 4 类。

---

## 3. 改配置时，旧虚拟机会不会自动删

### 会自动删的情况

如果你修改的是这些典型参数：

- machine type
- boot disk size
- boot disk type
- source image
- startup script 相关内容

通常 Terraform 会判定：

- 旧 instance template 不能原地改
- 需要创建一个新的 template
- 实例组要替换到新模板

这时 GCP 的实际行为就是：

- 新 VM 建起来
- 旧 VM 停掉
- 旧 VM 删除

所以你看到“新建了一台，新旧同时存在一会儿”，这是正常的。

### 什么时候不要手工删

如果旧机器还处于：

- `STOPPING`
- `DELETING`
- MIG 正在滚动更新

这时不要手工删。  
因为它本来就会自动收敛，手工删反而容易干扰判断。

---

## 4. 我自己能不能手工删旧虚拟机

可以，但**通常不建议**。

原因：

- 如果它属于 MIG，手工删了也可能被实例组重新拉起
- 如果实例组正在替换，手工删没有必要
- 容易把“正常滚动替换”和“异常实例消失”混在一起

### 建议

默认遵循这个规则：

- **优先让 Terraform + MIG 自动处理**
- 只有在明确确认某台机器已经脱离实例组、或者实例组卡死时，才考虑手工删

---

## 5. CPU 和内存怎么改

在当前仓库里，`CPU / 内存` 主要通过 **machine type** 改。

例如：

- `e2-medium`
- `e2-standard-2`
- `e2-standard-4`

GCP 机型本身就绑定了 vCPU 和内存。

### `server`

在 [`.env.dev`](/home/ubuntu/whz/infra/.env.dev) 里改：

```env
SERVER_MACHINE_TYPE=e2-medium
SERVER_CLUSTER_SIZE=1
```

如果你想改大一些，例如：

```env
SERVER_MACHINE_TYPE=e2-standard-2
```

### `api`

在 [`.env.dev`](/home/ubuntu/whz/infra/.env.dev) 里改：

```env
API_MACHINE_TYPE=e2-medium
API_CLUSTER_SIZE=1
```

例如改成：

```env
API_MACHINE_TYPE=e2-standard-2
```

### `build`

`build` 不是单一变量，而是在：

```env
BUILD_CLUSTERS_CONFIG='{"default":{"cluster_size":1,"machine":{"type":"e2-standard-2"},"boot_disk":{"disk_type":"pd-standard","size_gb":20},"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}}}'
```

要改 CPU / 内存，本质就是改：

```json
"machine":{"type":"e2-standard-2"}
```

### `client`

同理，在：

```env
CLIENT_CLUSTERS_CONFIG='{"default":{"cluster_size":1,"hugepages_percentage":80,"machine":{"type":"e2-standard-2"},"autoscaler":{"size_max":1,"memory_target":100,"cpu_target":0.7},"boot_disk":{"disk_type":"pd-standard","size_gb":20},"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}}}'
```

改这里：

```json
"machine":{"type":"e2-standard-2"}
```

### 区域建议

你现在说“west 或 east 都可以”，那就统一用：

- `us-west1`
或
- `us-east1`

区域在 [`.env.dev`](/home/ubuntu/whz/infra/.env.dev) 里改：

```env
GCP_REGION=us-west1
GCP_ZONE=us-west1-a
```

或者：

```env
GCP_REGION=us-east1
GCP_ZONE=us-east1-b
```

注意：

- 改 region/zone 属于大变更
- 不只是换虚拟机，很多关联资源也会重建
- 除非你明确要迁区，否则不要频繁改

---

## 6. 系统盘怎么改

这里说的系统盘，就是 boot disk。

### `server` 系统盘

在 [`.env.dev`](/home/ubuntu/whz/infra/.env.dev) 里：

```env
SERVER_BOOT_DISK_TYPE=pd-standard
SERVER_BOOT_DISK_SIZE_GB=20
```

### `api` 系统盘

当前仓库已经支持通过环境变量调：

```env
API_BOOT_DISK_TYPE=pd-standard
API_BOOT_DISK_SIZE_GB=20
```

### `build` 系统盘

在 `BUILD_CLUSTERS_CONFIG` 里：

```json
"boot_disk":{"disk_type":"pd-standard","size_gb":20}
```

### `client` 系统盘

在 `CLIENT_CLUSTERS_CONFIG` 里：

```json
"boot_disk":{"disk_type":"pd-standard","size_gb":20}
```

---

## 7. 外挂磁盘怎么改

这里的“外挂磁盘”在当前 build/client 配置里，对应的是：

- `cache_disks`

虽然名字叫 cache disk，但在这套架构里你可以把它理解成：

- 节点额外挂载的工作盘 / 数据盘

### `build` 外挂盘

在 `BUILD_CLUSTERS_CONFIG` 里：

```json
"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}
```

你可以改：

- `disk_type`
- `size_gb`
- `count`

例如：

```json
"cache_disks":{"disk_type":"pd-standard","size_gb":100,"count":1}
```

### `client` 外挂盘

在 `CLIENT_CLUSTERS_CONFIG` 里：

```json
"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}
```

同样可改：

- `disk_type`
- `size_gb`
- `count`

### 注意

如果用的是 persistent disk：

- 当前代码约束下 `count` 基本应保持 `1`

因为 worker cluster 对 persistent disk 有校验，多个盘不是当前默认路径。

---

## 8. 改动示例

下面是一套便宜一些、便于测试的示例：

```env
GCP_REGION=us-west1
GCP_ZONE=us-west1-a

SERVER_MACHINE_TYPE=e2-medium
SERVER_CLUSTER_SIZE=1
SERVER_BOOT_DISK_TYPE=pd-standard
SERVER_BOOT_DISK_SIZE_GB=20

API_MACHINE_TYPE=e2-medium
API_CLUSTER_SIZE=1
API_BOOT_DISK_TYPE=pd-standard
API_BOOT_DISK_SIZE_GB=20

BUILD_CLUSTERS_CONFIG='{"default":{"cluster_size":1,"machine":{"type":"e2-standard-2"},"boot_disk":{"disk_type":"pd-standard","size_gb":20},"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}}}'

CLIENT_CLUSTERS_CONFIG='{"default":{"cluster_size":1,"hugepages_percentage":80,"machine":{"type":"e2-standard-2"},"autoscaler":{"size_max":1,"memory_target":100,"cpu_target":0.7},"boot_disk":{"disk_type":"pd-standard","size_gb":20},"cache_disks":{"disk_type":"pd-standard","size_gb":50,"count":1}}}'
```

---

## 9. 实际操作步骤

每次改完配置，按这个顺序做：

```bash
cd /home/ubuntu/whz/infra
make plan
make apply
```

### `make plan` 的作用

- 读取当前 `.env.dev`
- 读取当前 Terraform state
- 计算需要新增/替换/删除哪些资源

### `make apply` 的作用

- 真正执行 `plan` 生成的变更
- 新模板生效
- 实例组滚动替换

---

## 10. 什么时候会重建

下面这些改动，通常都要重建实例：

- machine type
- boot disk type
- boot disk size
- `build/client` 的 `boot_disk`
- `build/client` 的 `cache_disks`
- `min_cpu_platform`

也就是说，你最关心的这些：

- CPU
- 内存
- 系统盘
- 外挂盘

**基本都属于会重建的改动。**

---

## 11. 如果我想删掉旧虚拟机，正确姿势是什么

默认正确姿势不是手工删 VM，而是：

1. 改配置
2. `make plan`
3. `make apply`
4. 等 MIG 自动删旧 VM

### 什么时候可以手工删

只有在下面两种情况才考虑：

1. 旧 VM 已经不在实例组里
2. MIG 明显卡死，且你已经确认替换逻辑异常

否则，优先让 GCP 自己删除。

---

## 12. 你和我后续应该共同遵循的操作方式

以后如果要调虚拟机参数，就按这个原则：

1. 先明确改哪类节点
2. 在 `.env.dev` 改对应字段
3. 跑 `make plan`
4. 看 plan 是否出现 `forces replacement`
5. 再跑 `make apply`
6. 等实例组自动删旧建新

不要把“手工删机器”作为主流程。

---

## 13. 最后建议

如果目标是低成本测试：

- `server`: `e2-medium`, `20GB pd-standard`
- `api`: `e2-medium`, `20GB pd-standard`
- `build`: `e2-standard-2`, `20GB pd-standard` + `50GB pd-standard`
- `client`: `e2-standard-2`, `20GB pd-standard` + `50GB pd-standard`

如果目标是更稳定的并发测试：

- 优先先把 `client` 升级
- 再考虑 `api`
- `server` 一般先保持稳定即可

