# Skill Launch Checklist 完整示例草案

状态：`observation-window-hold`

本目录保存已发布 `skill-launch-checklist` 的下一版示例候选，不是新 Skill，
不进入 catalog，也不触发 ClawHub 发布。

## 修复目标

现有 `launch_ready_vs_rushed.md` 只描述两个抽象版本，没有提供：

- 可追溯的真实输入。
- 每项检查的通过/阻塞结果。
- 明确的 go/no-go 结论。
- 阻塞项与非阻塞漏项的区分。
- 带稳定 `--slug` 和人类可读 `--name` 的下一步命令。

## 真实案例

候选示例来自本仓库历史：

- 候选提交：`e806aec8cd69a4a885a065ac41fab59596664fda`
- 候选目录：`skills/clawhub-launch-checklist`
- 候选版本：`1.0.0`
- 修复提交：`33ead75f52ec36da2adf89f542425f2ed3cbd67b`

候选包已有 `SKILL.md`、`CHANGELOG.md`、`.clawhubignore`、example、
reference 和 template，catalog 中也有 categories 与 topics。但 slug 以
受保护前缀 `clawhub-` 开头，因此无论页面材料多完整，结论都必须是
“先别发”。

修复提交将目录和 catalog key 改为 `skill-launch-checklist`，并在 workflow
加入受保护 slug 的前置失败规则。

## 文件

- `launch-review-evidence.json`：机器可验的历史输入、检查矩阵和最小修复。
- `complete_launch_review.md`：候选完整 go/no-go 报告。

## 声明边界

- 本草案没有执行 dry-run 或正式发布。
- 历史文件齐全不等于当时可以发布。
- 修复 slug 后仍只能进入“等待 dry-run”状态，不能直接宣称上线。
- 该正确性修复不证明下载、搜索或安装增长。

## 提升条件

1. 等待自然观察窗口结束。
2. 结合真实采用信号决定是否优先升级 Launch Checklist。
3. 与运行 metadata 修复合并为一次实质版本。
4. 正式修改后运行带显式 slug/name 的 dry-run。
5. 发布后只对变化版本执行一次 E4，并重建观察起点。
