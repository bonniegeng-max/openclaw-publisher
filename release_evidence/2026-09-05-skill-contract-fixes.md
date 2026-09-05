# 2026-09-05 Skill 合同修复证据

## 范围

本批次修复 4 个已发布 Skill 的正确性问题：

| Skill | 版本 | 修复 |
|---|---:|---|
| `skill-publish-readiness` | `1.0.8` | Skill 命令强制 `--slug` / `--name`；Plugin 使用独立 package 分支 |
| `skill-launch-checklist` | `1.0.3` | 所有发布命令强制 `--slug` / `--name` |
| `release-proof-builder` | `1.0.3` | E2 要求 workflow 成功；E3 要求 moderation clean；E4 记录安装污染 |
| `skill-portfolio-growth-audit` | `1.0.2` | 五项证据闸门未全部通过时禁止增长和产品组合决策 |

GitHub 提交：`617239c623fbf95374286a0695cc342aa47aadec`

## E0-E2

- 本地 69 项测试全部通过。
- Python 编译、workflow YAML、发布命令合同和 `git diff --check` 通过。
- 4 个本地 dry-run 均返回 `ok: true`、`status: would-publish`，slug、displayName 和版本正确。
- GitHub Skill Publish：
  - Run：<https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33938320922>
  - 结论：`success`
  - publish job annotations：`0`
  - 发布 JSON artifact digest：`sha256:815e40f79a706ee4900faa8af07bf014a25ad2a6fb86eea08a41571c09ebe178`
- Metrics Tools CI：
  - Run：<https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33938320808>
  - 结论：`success`

## E3-E4

4 个 slug 各执行一次 `inspect --json`，确认 latest、展示名和 moderation；随后各执行一次指定版本隔离安装。

| Skill | Latest | DisplayName | Moderation | 本地 / 安装 `SKILL.md` SHA-256 | E4 |
|---|---:|---|---|---|---|
| `skill-publish-readiness` | `1.0.8` | Skill Publish Readiness | `clean` | `752c2ad1a9462bdd04789b83467ff5e9b5cfdbef63acf3fd6c2d86798ec5184c` | 通过 |
| `skill-launch-checklist` | `1.0.3` | Skill Launch Checklist | `clean` | `71f44dbc4917736019356fad9b66601e82b6dbb3ba6c1caacb523b5661559211` | 通过 |
| `release-proof-builder` | `1.0.3` | Release Proof Builder | `clean` | `784896a9dfcce7d86ad6674ab6da945c9b0b2c740f16b5ab481a614e345f63e0` | 通过 |
| `skill-portfolio-growth-audit` | `1.0.2` | Skill Portfolio Growth Audit | `clean` | `7e2aeeac64b578a7904127ed199a339b34fbd59c4bd16b70bf70968bd344991b` | 通过 |

安装后的 hash 与提交中的对应 `SKILL.md` 完全一致。

## 指标污染

- 主动维护开始：`2026-09-05 10:10`（北京时间）
- E4 验收完成：`2026-09-05 10:26:39`（北京时间）
- 主动操作：4 次 dry-run、4 次 inspect、4 次指定版本 install，以及发布 workflow。
- 受影响 Skill：上述 4 个 slug。
- 该时段及紧随其后的 downloads / installs 变化不得归因为自然用户。
- 新自然观察起点：`2026-09-05 10:26:39`（北京时间）。
- 最早决策时间：`2026-09-12 10:26:39`（北京时间），且仍需满足同采集方法、双快照 `activeInstall: false`、相同 query/limit/query set 和 `decisionReady: true`。

其余 3 个未变更 Skill 本轮未执行 dry-run、inspect 或 install。
