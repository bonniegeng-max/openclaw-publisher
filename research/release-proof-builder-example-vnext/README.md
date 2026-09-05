# Release Proof Builder 完整 E4 示例草案

状态：`observation-window-hold`

本目录保存已发布 `release-proof-builder` 的下一版示例候选，不是新 Skill，
不进入 catalog，也不触发 ClawHub 发布。

## 修复目标

现有 `green_action_missing_registry.md` 正确展示了“workflow 成功但 registry
查不到”只能达到 E2，但它没有展示一份完整发布证明最终应长什么样：

- 没有逐级 E0–E4 矩阵。
- 没有实际 slug、版本、提交和 workflow run。
- 没有 moderation、文件哈希和隔离安装证据。
- 没有完整的主动安装污染记录。
- 没有说明拿掉某一项证据后最高只能停在哪一级。

候选示例使用已经完成的 `Skill Publish Readiness 1.0.9` E4 验收记录，补齐
一份可复查的成品报告，同时保留现有 E2 反例的教育价值。

## 权威输入

- 证据文件：
  `release_evidence/2026-09-05-skill-publish-readiness-1.0.9.md`
- GitHub 提交：
  `2748f047c26c57f9aa85c00a640ed0f5ae45db16`
- Skill Publish run：`33960781848`
- 目标版本：`skill-publish-readiness 1.0.9`
- E4 完成时间：`2026-09-05 18:45:38`（北京时间）

本草案不重新执行 inspect 或 install，只把现有证据结构化。

## 文件

- `e4-evidence.json`：机器可验的 E0–E4 矩阵、核心哈希、污染窗口与反事实。
- `verified_e4_release_report.md`：候选完整发布证明报告。

## 反事实边界

草案固定以下降级规则：

1. 只有 workflow 成功：最高 E2。
2. registry 可见但 moderation 不是明确 `clean`：最高 E2。
3. E3 已满足但没有指定版本隔离安装：最高 E3。
4. 安装成功但没有与源码比较核心文件：仍不能达到 E4。

## 声明边界

- E4 只对指定 slug、版本、提交和验收时点成立。
- 新版本不会继承旧版本的 E4，需要重新走变化版本验收。
- 主动 inspect/install 计数不得归因为自然采用。
- 完成示例不代表 Release Proof Builder 已产生下载增长。

## 提升条件

1. 等待自然观察窗口结束。
2. 结合真实采用信号确认是否优先升级 Release Proof Builder。
3. 若提升，将完整 E4 正例与现有 E2 反例同时保留。
4. 与运行 metadata 修复合并为一次实质版本。
5. 每个变化版本最多执行一次 E4，并重建观察起点。
