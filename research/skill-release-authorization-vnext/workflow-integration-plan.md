# GitHub 发布门禁接线方案

状态：`deferred-until-observation-review`

本方案只定义观察窗口结束后的接线方式。当前两个正式发布 workflow 保持不变，
本文件不会触发 ClawHub dry-run 或 publish。

## 信任边界

GitHub environment 可以要求指定 reviewer、阻止发起者自批、限制允许部署的分支，
并禁止管理员绕过保护规则。环境 secret 在 reviewer 批准 job 前不可访问：

- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-deployments/reviewing-deployments

仓内授权 JSON 只能证明候选内容、版本和证据没有漂移。批准者身份由
`clawhub-production` environment 提供，不能由 JSON 中的 `status` 字段单独提供。

目标 environment 必须配置：

- 至少一个 required reviewer。
- `prevent_self_review: true`。
- 禁止管理员绕过保护规则。
- 仅允许受保护的 `main` 分支。
- `CLAWHUB_TOKEN` 迁移为 environment secret，并删除同名 repository secret。

GitHub 明确说明，可复用 workflow 的 environment secret 不能通过
`on.workflow_call` 从 caller 传入；called workflow 必须在具体 job 上声明
environment，届时使用该 environment 自己的 secret：

- https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

## 两阶段 job

### Preflight

`preflight` job 不声明 environment，不读取 token，不安装 Bun，不检出 ClawHub
源码，也不访问 registry。它只执行：

1. checkout 最终发布 HEAD，`fetch-depth: 0`。
2. 从受信任 commit 同时取得 release checker 与 catalog validator，而不是执行
   候选提交可修改的控制面。
3. 将 checker 与 validator 封装为同一受信任执行单元，并验证 control commit
   的 Git 对象类型、文件模式和摘要；只单独运行一遍 validator 不能阻止 checker
   随后重新加载候选副本。
4. 由 workflow 固定可信 Python 与 Git 可执行文件及 `PATH`，使用 `python -I`
   启动 checker，并清除候选可控的 Python/Git 环境变量；checker 内部的路径自检
   只能证明路径匹配，不能替代 launcher 的启动前信任。
   研究版 launcher 固定使用 `/usr/bin/git`，不得通过继承的 `PATH` 发现 Git；
   workflow runner 必须提供并保护该系统入口，同时以固定绝对路径启动 Python。
   研究版启动合同位于
   `research/skill-release-authorization-vnext/trusted_preflight_launcher.py`；
   它尚未被正式 workflow 调用，因此不构成部署证据。
5. 在运行测试、编译或任何可能生成缓存的步骤之前，创建相互独立、干净且不可并发
   写入的 control 与 candidate checkout；launcher/checker 会验证 symlink、
   hardlink、Git object store、blob、类型和执行位，但不把同主机恶意并发改写
   纳入 CLI 自证范围。
6. 受信任控制面显式接收候选仓库根目录，不能依赖导出路径推断 repo root。
7. 验证 base、candidate commit、唯一授权提交、单 Skill 版本递增、完整摘要和
   `authorized: true`。
8. 输出允许发布的 slug、version、candidate commit 和最终 head。

只要 preflight 失败，后续 job 不创建 deployment，也不接触任何 ClawHub secret。

### Publish

`publish` job 必须同时满足：

- `needs: preflight`
- `environment: clawhub-production`
- preflight 的 `authorized` 输出为 `true`
- 当前 ref 为受保护的 `main`

环境审批通过后才允许：

1. 读取 `CLAWHUB_TOKEN`。
2. 安装固定版本的 ClawHub CLI。
3. 只发布 preflight 输出的单个 slug。
4. 显式传递稳定 `--slug` 与人类可读 `--name`。
5. 保存结构化 publish JSON。

GitHub 建议令牌采用最小权限，并把第三方 action 固定到完整 commit SHA；只有完整
SHA 是不可变引用：

- https://docs.github.com/en/actions/reference/security/secure-use

接线时应把 `actions/checkout`、`actions/setup-python`、`actions/upload-artifact`
等 `uses:` 引用统一固定到已核验的完整 SHA。

## Workflow 来源

同仓库的：

```yaml
uses: ./.github/workflows/example.yml
```

会使用 caller 同一个 commit 中的 called workflow。GitHub 官方文档明确说明，
若需要稳定、安全的 reusable workflow，应使用带完整 commit SHA 的
`owner/repository/.github/workflows/file.yml@<sha>` 形式：

- https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

正式接线应从受信任完整 SHA 调用 reusable workflow。更新门禁 workflow 时：

1. 单独提交 workflow 与 checker 变更。
2. 不与 Skill 发布混在同一个 diff。
3. 验证远端 CI 后，才更新 caller 中的固定 SHA。
4. SHA 更新本身也走 CODEOWNERS 与 branch protection。

GitHub 建议用 CODEOWNERS 保护 `.github/workflows`，让 workflow 变更必须由指定
reviewer 审核：

- https://docs.github.com/en/actions/reference/security/secure-use

## 触发策略

不使用 `pull_request_target` checkout 候选代码。GitHub 将
`pull_request_target` 和 `workflow_run` 下的不可信代码 checkout 列为高风险，
建议没有必要时避免：

- https://docs.github.com/en/actions/reference/security/secure-use

建议分为：

- `pull_request`：只运行无 secret 的静态 catalog、测试和 pending 合同校验。
- `workflow_dispatch` dry-run：显式选择候选 ref，经过单独的受保护环境后执行。
- `push main` publish：只接受已完成 dry-run 证据、`mode: publish` 和最终环境审批。

同一授权不能跨模式自动升级。dry-run 完成后，必须更新 review 证据、重新生成
授权摘要并重新审批 publish。

## 接线验收

正式接线前必须用离线 workflow 合同测试证明：

- 缺少授权文件时，Bun 和 ClawHub 步骤不可达。
- `status: pending` 时，publish job 不创建 deployment。
- candidate 后存在额外提交时失败。
- environment 未批准时，`CLAWHUB_TOKEN` 不可访问。
- 发起者不能自批。
- 非 `main` ref 不能进入 production environment。
- 修改 checker、validator、policy 或 workflow 的同批 Skill release 会失败。
- checker 必须由固定 SHA 的 launcher 以 `python -I` 启动，候选 `PYTHONPATH`、
  Git config 注入、replace refs、fsmonitor 与仓库重定向变量均不能生效。
- candidate checkout 在 preflight 前保持无 ignored/untracked 文件，且执行期间
  不与其他 job 或进程共享可写工作区。
- publish 只处理授权的一个 slug，不会扫描并发布全部目录。
- 真实发布成功仍只代表 E2；E3 moderation 与 E4 隔离安装必须单独完成。

只有 environment 配置、固定 SHA、workflow 合同测试和一次受控演练全部通过，
才能把本目录状态从 `offline-contract-ready-not-wired` 改为
`wired-and-protected`。

仓内 `workflow-integration-contract.json` 只记录可复核事实和未完成 gate。其
离线 checker 不解析 YAML，也不能证明 environment 的真实配置或 reviewer 身份；
这些结论必须来自 GitHub API/受保护环境产生的外部证据，并在接线提交之外完成
复核。缺少外部证据时，`deploymentReady` 必须保持 `false`。

观察期冻结状态不能由 caller 当前文件与合同内可同步修改的裸摘要互相证明。
合同必须记录 `callerBaseline` 的固定 commit、mode、blob OID 与 SHA-256；离线
checker 同时核验该 Git 对象和当前工作树副本。任何 caller 变化都必须等到观察期
结束后的 fresh review，不能通过同步更新合同摘要绕过。
