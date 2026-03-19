# E2B 核心概念说明

这份文档的目标是把你当前最容易混淆的几个概念彻底分开：

- `team_id`
- `E2B_API_KEY`
- `template_id`
- template alias
- `build_id`
- `sandbox_id`

这些概念如果不分清，后面会很容易出现：

- 明明模板存在，但当前 key 用不了
- `base` 明明看到了，但 `Sandbox.create()` 仍然报错
- 模板 build 成功了，却不知道应该拿哪个 ID 去创建 sandbox

所以你可以把这份文档当作：

- 当前这套 self-hosted E2B 的概念地图

---

## 1. 一句话先讲清楚整条链路

最核心的链路其实只有这一条：

```text
team
-> API key
-> template
-> sandbox
```

也就是说：

1. 先有一个 team
2. team 下面有 API key
3. team 下面构建模板
4. 再基于模板创建 sandbox

你后面看到的大多数 ID，都只是这条链路上不同层级对象的标识。

---

## 2. `team_id` 是什么

`team_id` 是团队的唯一标识。

你可以把 team 理解成：

- 一个租户
- 一个命名空间
- 一组资源的归属单位

在实际使用里，很多关键资源都是围绕 team 组织的：

- API key 属于 team
- 模板属于 team
- 模板 alias 的可见性和 team 有关
- sandbox 的创建权限也和 team 有关

### 2.1 为什么数据库里会有很多 `team_id`

因为可能有：

- 历史测试 team
- smoke test 临时 team
- seed 脚本创建的 team
- 多个用户/多次实验留下的 team

所以看到很多 `team_id` 不奇怪。

### 2.2 实际使用时应该怎么做

通常应当：

- 选定一个正式 team
- 用这个 team 的 API key
- 在这个 team 下构建模板
- 用这个 team 的模板创建 sandbox

也就是说，日常开发最好围绕同一个 team 工作。

---

## 3. `E2B_API_KEY` 是什么

`E2B_API_KEY` 是 team API key。

它的作用是：

- 证明你是谁
- 更重要的是，证明你代表哪个 team 在操作

所以 API key 不只是“登录凭证”，它还决定：

- 你能访问哪个 team 的模板
- 你能不能构建模板
- 你能不能创建 sandbox

### 3.1 关键理解

不是“有 key 就能访问所有模板”，而是：

- 有某个 team 的 key
- 才能访问这个 team 相关的模板和资源

这就是为什么你前面会遇到：

- 模板 alias 叫 `base`
- 但当前 key 仍然 `404`

因为那个 `base` 可能属于别的 team。

---

## 4. template 是什么

template 是模板。

你可以把它理解成：

- sandbox 的母版
- 预装好环境的运行镜像
- sandbox 启动前的基础环境定义

模板里面通常会定义：

- 用什么基础镜像
- 装哪些依赖
- 启动时执行什么命令
- 用什么 ready 检查

例如：

- 普通模板
- code interpreter 模板
- 带 Playwright / OCR / 文档处理能力的业务模板

---

## 5. `template_id` 是什么

`template_id` 是模板的唯一标识。

这是数据库和平台内部真正认模板的 ID。

例如：

- `sz0vk8nn2cgp45hvt8eb`
- `o36rjkqq5xxf4zc6rxww`

### 5.1 它是怎么来的

它通常来自：

- `Template.build(...)` 的返回值

例如：

```python
build = Template.build(...)
print(build.template_id)
```

### 5.2 它用来做什么

它最直接的用途就是：

- 创建 sandbox

例如：

```python
sbx = Sandbox.create(
    template="sz0vk8nn2cgp45hvt8eb",
)
```

---

## 6. template alias 是什么

template alias 就是模板别名。

它是给人类看的名字，不是模板真正的底层 ID。

例如：

- `base`
- `code-interpreter`
- `dynamic_agent_sandbox_20260318_xxx`

### 6.1 alias 和 `template_id` 的区别

- `template_id`
  - 唯一 ID
  - 平台内部真正识别模板的方式
- alias
  - 人类更容易记
  - 但可能存在命名空间和 team 作用域问题

所以：

- alias 更方便记忆
- `template_id` 更准确、更稳定

### 6.2 为什么 alias 可能会出问题

因为 alias 往往和 team / namespace 有关系。

比如：

- 你看到有个 `base`
- 但它未必属于你当前这把 key 的 team

所以实践里更稳的方式是：

- 关键场景优先直接使用 `template_id`

---

## 7. `build_id` 是什么

`build_id` 是一次模板构建任务的 ID。

注意：

- `build_id` 不是模板 ID
- `build_id` 也不是 sandbox ID

它只表示：

- 某一次 build 过程的唯一标识

比如：

- 你 build 一个模板时会返回：
  - `template_id`
  - `build_id`

这里的关系是：

- `template_id` 表示“这个模板是谁”
- `build_id` 表示“这次构建任务是谁”

### 7.1 `build_id` 主要用来做什么

- 查构建日志
- 查构建是否成功
- 排查模板 build 问题

---

## 8. sandbox 是什么

sandbox 是基于模板启动出来的实际运行实例。

你可以把它理解成：

- 真正可以执行代码的隔离环境
- 真正可读写文件、跑命令、联网的对象

模板不是运行实例，sandbox 才是。

---

## 9. `sandbox_id` 是什么

`sandbox_id` 是具体某个 sandbox 实例的唯一标识。

例如：

- `iesoj79yn75152nbp5h7c`

### 9.1 它是怎么来的

它来自：

- `Sandbox.create(...)`

例如：

```python
sbx = Sandbox.create(template="sz0vk8nn2cgp45hvt8eb")
print(sbx.sandbox_id)
```

### 9.2 它用来做什么

- 标识具体的运行实例
- 用于连接、调试、销毁 sandbox

---

## 10. `template_id` 和 `sandbox_id` 最容易搞混

你一定要记住：

- `template_id`：模板 ID，表示“用什么母版”
- `sandbox_id`：沙箱 ID，表示“实际启动出的实例”

可以这样类比：

- `template_id` 像操作系统镜像 ID
- `sandbox_id` 像基于镜像启动出来的某一台虚拟机 ID

所以它们不是一个层次的东西。

---

## 11. 为什么通常要围绕同一个 team 工作

因为在这套系统里：

- key 属于 team
- 模板属于 team
- alias 可见性和 team 有关
- sandbox 创建权限也和 team 有关

如果你在多个 team 之间乱切，就会很容易碰到：

- `base` 明明存在，但当前 key 不能用
- 模板 alias 重名但其实是别人的
- API key 能鉴权成功，但模板访问失败

所以通常建议：

1. 选一个正式 team
2. 用这个 team 的 API key
3. 在这个 team 下 build 模板
4. 用这些模板创建 sandbox

---

## 12. 一条完整例子

假设你现在有这些信息：

- `team_id = TEAM_A`
- `E2B_API_KEY = e2b_xxx`
- 构建出来的 `template_id = sz0vk8nn2cgp45hvt8eb`

调用链是：

```text
TEAM_A
-> e2b_xxx
-> Template.build(...) 返回 template_id=sz0vk8nn2cgp45hvt8eb
-> Sandbox.create(template=sz0vk8nn2cgp45hvt8eb)
-> 返回 sandbox_id=iesoj79yn75152nbp5h7c
-> sbx.run_code(...) / sbx.commands.run(...)
```

这就是最标准的关系。

---

## 13. 实际中你最该怎么理解这些概念

如果只保留最重要的记忆点，可以记这 5 句。

### 13.1 `team_id`

表示资源归属的团队。

### 13.2 `E2B_API_KEY`

表示你以哪个 team 的身份在调用平台。

### 13.3 `template_id`

表示你要拿哪一个模板来启动 sandbox。

### 13.4 alias

是模板的人类可读名字，但不一定比 `template_id` 更稳。

### 13.5 `sandbox_id`

表示真正跑起来的那个实例。

---

## 14. 最后一句话总结

把整套关系压缩成一句最实用的话：

`team_id` 决定资源归属，`E2B_API_KEY` 决定你代表哪个 team，`template_id` 决定用哪个模板启动，`sandbox_id` 则是最终真正跑起来的实例。

---

## 15. 关系图

下面这张图可以把这些概念串起来看：

```text
User
  |
  | belongs to
  v
users_teams
  |
  v
Team
  |
  | identified by
  v
team_id
  |
  | owns
  +------------------------------+
  |                              |
  v                              v
team_api_keys                 Templates
  |                              |
  | provides                     | stored as
  v                              v
E2B_API_KEY                  envs.id = template_id
                                 |
                                 | may have
                                 v
                           env_aliases.alias
                                 |
                                 | built by
                                 v
                           env_builds.id = build_id
                                 |
                                 | used to create
                                 v
                           Sandbox
                                 |
                                 | identified by
                                 v
                           sandbox_id
```

如果换成“你平时实际操作”的视角，可以看这条链：

```text
选择一个 team
-> 使用这个 team 的 E2B_API_KEY
-> 在这个 team 下 build 模板
-> 拿到 template_id
-> 用 template_id 创建 sandbox
-> 拿到 sandbox_id
-> 在 sandbox 中 run_code / run bash
```

如果换成一个更具体的例子：

```text
team_id = TEAM_A
-> E2B_API_KEY = e2b_xxx
-> Template.build(...) 返回 template_id = sz0vk8nn2cgp45hvt8eb
-> Sandbox.create(template="sz0vk8nn2cgp45hvt8eb")
-> 返回 sandbox_id = iesoj79yn75152nbp5h7c
-> sbx.run_code("print('hello world')")
```

最容易记住的版本是：

```text
team
-> key
-> template
-> sandbox
```
