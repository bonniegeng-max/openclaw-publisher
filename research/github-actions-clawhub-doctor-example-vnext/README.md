# GitHub Actions ClawHub Doctor 示例修复草案

状态：`observation-window-hold`

本目录保存已发布 `github-actions-clawhub-doctor` 的下一版示例候选，不是新
Skill，不进入 `.clawhub/skill-catalog.json`，也不触发 ClawHub 发布。

## 修复目标

现有 `examples/pending_publication_false_failure.md` 只有症状与三步建议，
没有完整兑现正文承诺的五项输出：

1. 问题所在层级。
2. 直接原因。
3. 可追溯证据。
4. 最小修复方案。
5. 修复后验证命令与声明边界。

更重要的是，现有示例把“公开页或 inspect 可能看到新版本”与 workflow
状态放在一起，却没有区分：

- workflow 结果；
- CLI 返回状态；
- registry latest 与 moderation；
- 指定版本独立安装。

这会让读者误把 Actions 绿灯或 `pending-publication` 当成“已上线、可下载
使用”的充分证据。

## 真实证据

候选示例只使用仓库和 GitHub 可验证的事实：

- 提交 `77a4b1864655693b860f731dd2fd51e4c182cbd9` 的 Skill Publish run
  `33870318104` 在 `Run skill publishes` 以 `exit code 1` 失败。
- 提交 `0a6ca43cc0ae519b5a6db6c601c11589a3fd2b2f` 引入本地 reusable
  workflow，并将 CLI 状态 `pending-publication` 映射到
  `pendingPublication`，只在 `failed` 非空时退出失败。
- 修复提交对应的 run `33871495707` 成功。

失败 run 的 artifact 正文没有进入本仓库，本草案也没有下载或重放它。
因此示例不伪造原始 CLI payload，不声称失败 run 中某个具体 Skill 的
registry 状态已经被证明。

## 文件

- `incident-evidence.json`：机器可验的提交、run、代码映射和未知边界。
- `pending_publication_false_failure.md`：候选完整示例。

## 提升条件

只有在 `2026-09-12T10:45:38+00:00` 之后完成一次统一增长监控，并确认
目标 Skill 与改进优先级后，才评估是否：

1. 将候选示例复制到正式 Skill。
2. 更新 `SKILL.md` 中对示例的描述。
3. 增加正式内容防回归测试并升级版本。
4. 通过发布 workflow 后按 E0–E4 完成一次限定验收。

若增长证据未就绪，本草案继续留在 `research/`；不得为了示例优化提前发布
或重复安装。
