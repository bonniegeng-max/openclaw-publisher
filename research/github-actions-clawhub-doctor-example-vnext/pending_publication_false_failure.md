# 真实修复案例：Actions 红灯不等于发布失败

这是基于本仓库历史提交与 GitHub Actions run 的脱敏案例。失败 artifact
正文没有进入仓库，因此以下内容不伪造 CLI 原始 payload，也不把后续绿灯
写成 registry 或安装成功。

机器可验输入见 `incident-evidence.json`。

## 输入证据

| 证据 | 观察结果 |
|---|---|
| 失败提交 | `77a4b1864655693b860f731dd2fd51e4c182cbd9` |
| 失败 run | `33870318104`，结论 `failure` |
| 失败步骤 | `Run skill publishes` |
| annotation | `Process completed with exit code 1.` |
| 修复提交 | `0a6ca43cc0ae519b5a6db6c601c11589a3fd2b2f` |
| 修复 run | `33871495707`，结论 `success` |
| registry latest | `UNKNOWN` |
| moderation | `UNKNOWN` |
| 指定版本独立安装 | `UNKNOWN` |

## 问题层级

`workflow-result-classification`

这不是“Skill 内容必然无效”的证据，也不是“版本已经公开可安装”的证据。
失败发生在 workflow 对发布结果的归类与退出条件层。

## 直接原因

修复提交新增了一个明确状态映射：

```text
pending-publication → pendingPublication
published           → published
unchanged           → alreadySynced
would-publish       → wouldPublish
```

workflow 只在 `failed` 数组非空时退出失败。由此可以高置信判断，修复目标是
把 `pending-publication` 从真正失败中分离，避免状态已被平台接受但仍在后续
处理时被本地封装错误归为失败。

由于失败 run 的 artifact payload 未保存在仓库里，不能进一步声称当时的
完整 CLI JSON、slug、版本、moderation 或 registry latest 已经得到证明。

## 证据判断

| 判断 | 结论 | 理由 |
|---|---|---|
| 原 workflow 确实失败 | 已证明 | GitHub run 和 annotation 可核对 |
| 修复专门处理 `pending-publication` | 已证明 | 修复提交中的状态映射可核对 |
| 修复后的 workflow 成功 | 已证明 | 后续 run 结论为 `success` |
| 失败 run 的完整 CLI payload | `UNKNOWN` | artifact 正文不在仓库 |
| 目标版本已公开、moderation clean | `UNKNOWN` | 没有本示例对应的 E3 证据 |
| 目标版本可下载使用 | `UNKNOWN` | 没有本示例对应的 E4 证据 |

当前证据最多证明修复 run 达到 `E2`。不得把 Actions success、
`pending-publication` 或“没有 failed 项”单独写成 E3/E4。

## 最小修复

1. 将 CLI 的结构化状态按语义分别保存，不用非空结果统一判失败。
2. `pending-publication` 放入独立数组并保持 workflow 成功。
3. 只让 validation、权限、输入、上传或未知状态等确定性错误进入 `failed`。
4. 始终保存结构化发布 artifact，便于后续确认具体 slug、版本和状态。

不要通过吞掉所有非零退出码、删除状态检查或伪造 `published` 来消除红灯。

## 修复后验证

先验证 workflow 结果：

```text
GitHub Actions run completed with conclusion: success
```

这只证明 E2。若目标版本发生变化，再按顺序补证：

```bash
clawhub inspect @<owner>/<slug> --version <version> --json
clawhub --workdir <isolated-dir> install @<owner>/<slug> --version <version>
```

验收时还必须：

1. 确认 registry latest、displayName、topics 和指定版本正确。
2. 确认 `moderation.verdict` 明确为 `clean`。
3. 每个变化版本最多执行一次计划内隔离安装。
4. 比较安装后核心文件与对应 GitHub 提交。
5. 记录主动 inspect/install 的时间与指标污染边界。

## 最终结论

这次修复证明 workflow 曾错误处理发布状态，并在加入
`pending-publication` 独立映射后恢复成功；它没有单独证明目标版本已经达到
E3 或 E4。只有补齐 registry 和隔离安装证据后，才能声明“已上线、可下载
使用”。
