# ClawHub 作品集增长基线

更新时间：2026-09-05  
发布者：`@bonniegeng-max`  
GitHub 基线提交：`029fb2763b6d8530f6efd29dea6e5aa8d42ec7d3`

## 当前结论

作品集已经形成一条清晰主线：发布前审查、发布链路排障、发布后证明和商店页增长。`skill-publish-readiness` 是当前下载信号最强的入口；两个最新增长类 skill 已在搜索接口出现首次安装信号，但平台不同接口尚未同步一致。

本轮最高优先级“统一展示名”已完成。7 个 skill 均保留稳定 slug，同时使用人类可读展示名；下一阶段进入观察窗口，不用短期波动过早判断增长效果。

## 修复验收

GitHub 修复提交：`27bb7f5f87e882856eb9a7c6e2484c6d30c9b421`

| Skill | Latest | Display | Moderation | 安装验证 |
|---|---:|---|---|---|
| `skill-publish-readiness` | 1.0.6 | Skill Publish Readiness | clean | 通过 |
| `github-actions-clawhub-doctor` | 1.0.5 | GitHub Actions ClawHub Doctor | clean | 通过 |
| `skill-positioning-audit` | 1.0.4 | Skill Positioning Audit | clean | 通过 |
| `skill-launch-checklist` | 1.0.2 | Skill Launch Checklist | clean | 通过 |
| `skill-summary-rewriter` | 1.0.2 | Skill Summary Rewriter | clean | 通过 |
| `release-proof-builder` | 1.0.2 | Release Proof Builder | clean | 通过 |
| `skill-portfolio-growth-audit` | 1.0.1 | Skill Portfolio Growth Audit | clean | 通过 |

7 个 latest 版本均完成隔离安装，安装后的 `SKILL.md` 与该 GitHub 提交中的文件一致，证据等级达到 `E4`。

## 修复前快照

| Skill | Downloads | Inspect installs | Search installs | Stars | Versions | Latest | Display | Moderation |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `skill-publish-readiness` | 43 | 0 | 0 | 0 | 6 | 1.0.5 | slug | clean |
| `github-actions-clawhub-doctor` | 11 | 0 | 0 | 0 | 5 | 1.0.4 | 产品名 | clean |
| `skill-positioning-audit` | 0 | 0 | 未采集 | 0 | 4 | 1.0.3 | slug | clean |
| `skill-launch-checklist` | 0 | 0 | 未采集 | 0 | 2 | 1.0.1 | slug | clean |
| `skill-summary-rewriter` | 0 | 0 | 1 | 0 | 2 | 1.0.1 | slug | clean |
| `release-proof-builder` | 0 | 0 | 未采集 | 0 | 2 | 1.0.1 | slug | clean |
| `skill-portfolio-growth-audit` | 0 | 0 | 1 | 0 | 1 | 1.0.0 | slug | clean |

## 数据边界

- 这是首份基线，不能据此计算增长率。
- `inspect` 与 `search` 的 installs 数据存在差异，两组数据均保留。
- 新 skill 尚未经过 7 天观察窗口，不做停更或失败判断。
- downloads 不等于 installs，不能把 43 次 downloads 解释为 43 个用户。

## 搜索可见性

### `publish skill`

`skill-publish-readiness` 可以被搜到，但显示名仍是 slug。代表性竞品最高只有 2 installs / 60d，说明赛道存在需求但整体采用仍低。

### `skill summary`

`skill-summary-rewriter` 位于结果前列，并显示 1 install / 60d。搜索结果同时混入大量内容摘要类 skill，后续应继续强化 `storefront copy`、`catalog copy` 等差异化关键词。

### `skill portfolio`

`skill-portfolio-growth-audit` 已出现 1 install / 60d，高于同名 `skill-portfolio-audit` 的 0 installs。当前摘要强调 registry 证据和作品集决策，差异已经能被搜索结果识别。

## 决策

| Skill | 决策 | 依据 |
|---|---|---|
| `skill-publish-readiness` | 加码 | 当前 downloads 最高，仍是系列主入口 |
| `github-actions-clawhub-doctor` | 保留 | 已有第二强下载信号，定位具体 |
| `skill-positioning-audit` | 观察 | 发布窗口短，且属于后置需求 |
| `skill-launch-checklist` | 观察 | 已可安装，尚无足够增长数据 |
| `skill-summary-rewriter` | 观察并强化搜索词 | 搜索侧出现首次安装信号 |
| `release-proof-builder` | 观察 | 真实痛点明确，但尚无采用数据 |
| `skill-portfolio-growth-audit` | 观察并作为组合决策层 | 搜索侧出现首次安装信号 |

## 暂不进入的方向

- 通用 skill 更新器：已有成熟产品覆盖 diff、备份、迁移与回滚。
- 通用安装前安全审查：已有高安装量产品，竞争成熟。
- 继续拆分更多发布检查器：当前作品集数量已足够，先改善转化与系列识别。

## 唯一下一步

保持现有作品集结构至少一个完整 7 天观察窗口；下次周检优先比较展示名修复前后的搜索可见性、downloads 与 installs，再决定是否加码主入口或优化摘要，不新增同质化发布检查器。
