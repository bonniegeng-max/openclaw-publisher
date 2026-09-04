# ClawHub 作品集增长基线

更新时间：2026-09-05 05:43（Asia/Shanghai）
发布者：`@bonniegeng-max`  
GitHub 基线提交：`029fb2763b6d8530f6efd29dea6e5aa8d42ec7d3`

## 当前结论

作品集已经形成一条清晰主线：发布前审查、发布链路排障、发布后证明和商店页增长。`skill-publish-readiness` 是当前下载信号最强的入口；两个最新增长类 skill 已在搜索接口出现首次安装信号，但平台不同接口尚未同步一致。

本轮最高优先级“统一展示名”已完成。7 个 skill 均保留稳定 slug，同时使用人类可读展示名；下一阶段进入观察窗口，不用短期波动过早判断增长效果。

主入口加码动作也已完成：`skill-publish-readiness` 发布 `1.0.7`，新增真实复合失败审查案例和证据矩阵模板，并通过 ClawHub `clean` 审核及 E4 独立安装验证。该版本刚上线，暂不把下载量未变化解释为优化无效。

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

## 当前数据快照

| Skill | Downloads | Inspect installs | Search installs / 60d | Stars | Versions | Latest | DisplayName | Topics | Moderation | 可安装 |
|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| `skill-publish-readiness` | 100† | 1* | 1* | 0 | 8 | `1.0.7` | Skill Publish Readiness | `publishing`, `release-review`, `github-actions`, `skill-audit`, `metadata` | clean | 是 |
| `github-actions-clawhub-doctor` | 80† | 1* | 1* | 0 | 6 | `1.0.5` | GitHub Actions ClawHub Doctor | `github-actions`, `workflow-debug`, `publish-failure`, `release-ops`, `ci-troubleshooting` | clean | 是 |
| `skill-positioning-audit` | 74† | 1* | 1* | 0 | 5 | `1.0.4` | Skill Positioning Audit | `positioning`, `catalog-copy`, `skill-differentiation`, `install-conversion`, `storefront-review` | clean | 是 |
| `skill-launch-checklist` | 66† | 1* | 1* | 0 | 3 | `1.0.2` | Skill Launch Checklist | `launch-checklist`, `pre-publish-review`, `release-readiness`, `catalog-quality`, `skill-launch` | clean | 是 |
| `skill-summary-rewriter` | 67† | 1* | 1* | 0 | 3 | `1.0.2` | Skill Summary Rewriter | `summary-rewrite`, `storefront-copy`, `catalog-copy`, `install-conversion`, `skill-positioning` | clean | 是 |
| `release-proof-builder` | 68† | 1* | 1* | 0 | 3 | `1.0.2` | Release Proof Builder | `release-verification`, `publish-proof`, `registry-check`, `install-verification`, `release-ops` | clean | 是 |
| `skill-portfolio-growth-audit` | 59† | 1* | 1* | 0 | 2 | `1.0.1` | Skill Portfolio Growth Audit | `portfolio-audit`, `skill-growth`, `registry-analytics`, `competition-research`, `publisher-strategy` | clean | 是 |

\* 本次巡检对 7 个 Skill 各执行了至少一次独立安装，inspect 与搜索随后均显示 1 install；这些值不作为自然增长证据。

† downloads 在全量隔离安装和重复 registry 核验后同步跳升，且 7 个 Skill 均出现相近量级变化。当前无法从平台口径中排除自动验收流量，因此只保留原始值，不把增量解释为外部用户下载。

## 快照对比

| 维度 | 变化 | 解释 |
|---|---|---|
| Downloads | 七项同步跳升至 59-100 | 与验收时段重合，指标已被技术核验污染，不能证明自然增长 |
| Inspect installs | 七项均由 0 变为 1 | 与每项一次独立安装完全一致，不是自然采用证据 |
| Stars | 七项均保持 0 | 无变化 |
| Versions / latest | 主入口较基线增加 2 个版本，其余各增加 1 个 | `1.0.7` 是真实案例与报告模板升级，其余来自展示名修复 |
| DisplayName | 6 项由 slug 改为产品名 | 搜索可读性已实质改善；Doctor 原本已正确 |
| Moderation | 七项均保持 clean | 无审核异常 |
| 可安装状态 | 七项均安装成功 | 最新版本均完成 E4 安装验证 |

本轮唯一明确的可见性变化是展示名修复生效。搜索排名缺少更早的同口径完整记录，因此不声称排名上升或下降。

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
- downloads 不等于 installs，也不等于独立用户。
- E4 验收会触发真实下载与安装，后续自然增长必须从“最后一次主动验收后的快照”开始观察。
- 当前最可靠的相对信号仍是验收前基线：主入口 43 downloads、Doctor 11，其余为 0。

## 巡检采样规则

- 周检先读取 `inspect` 和搜索结果，不重复安装未变化的版本。
- 只有 latest 变化、moderation 异常、公开文件缺失或用户明确要求时，才执行一次隔离安装。
- 主动 dry-run、inspect、install 和工作流核验都要记录时间，避免与自然指标混为一谈。
- 发生主动安装后，重新建立观察起点；该时点之前与紧随其后的增量不用于增长归因。
- 同一轮只采集一次同口径指标，避免重复查询本身影响未知的平台计数。

## 搜索可见性

| Skill | 真实任务关键词 | 当前位置 | 代表性结果 | 判断 |
|---|---|---:|---|---|
| `skill-publish-readiness` | `publish skill readiness` | 1 | `Novel Publish Ready` 0 installs；`Skill Validation` 0 installs | 长尾可见，且与自家 Launch Checklist 同场 |
| `github-actions-clawhub-doctor` | `github actions publish failure` | 1 | 无直接同任务结果 | 定位最独特，搜索噪音低 |
| `skill-positioning-audit` | `skill positioning storefront` | 2 | 第 1 是自家 Summary Rewriter | 两项关键词重叠，先观察再决定是否合并 |
| `skill-launch-checklist` | `skill launch checklist` | 1 | `site-launch-checklist` 有 1,956 skills.sh lifetime installs，但任务是网站上线 | 长尾可见，代表性竞品并非同任务 |
| `skill-summary-rewriter` | `skill summary rewrite` | 1 | 高安装结果主要是论文写作类 | 精确词可见，宽泛 summary 词噪音较高 |
| `release-proof-builder` | `release verification install proof` | 1 | 无直接同任务结果 | 细分任务独特，尚无自然采用证据 |
| `skill-portfolio-growth-audit` | `skill portfolio growth audit` | 1 | 无直接同任务结果 | 精确词可见，但刚发布，不能判断需求 |

这些查询只验证当前可发现性，不代表稳定排名。skills.sh lifetime installs 与 ClawHub 60 天 installs 不是同一统计口径，未参与数值比较。

## 决策

| Skill | 决策 | 依据 |
|---|---|---|
| `skill-publish-readiness` | 加码已执行，进入观察 | 验收前 downloads 基线领先、长尾搜索第 1；`1.0.7` 已补真实案例与结构化输出 |
| `github-actions-clawhub-doctor` | 加码 | 验收前 downloads 基线第二，任务最具体，搜索中没有直接竞品 |
| `skill-positioning-audit` | 观察 | 新发布、0 downloads，且与 Summary Rewriter 关键词重叠 |
| `skill-launch-checklist` | 观察 | 可见且可安装，但与主入口任务相邻，尚无独立采用证据 |
| `skill-summary-rewriter` | 观察 | 精确查询第 1，但 0 downloads，宽泛关键词噪音较高 |
| `release-proof-builder` | 观察 | 独特的发布后核验任务已成立，但没有自然采用证据 |
| `skill-portfolio-growth-audit` | 观察 | 刚发布且只有当前截面，不能做趋势或停更判断 |

当前没有足够证据把任何 Skill 标为“停更”；也没有足够观察窗口把 Positioning Audit 与 Summary Rewriter 标为“合并”。展示名问题已修复，因此本轮不保留“修复”标签。

## 暂不进入的方向

- 通用 skill 更新器：已有成熟产品覆盖 diff、备份、迁移与回滚。
- 通用安装前安全审查：已有高安装量产品，竞争成熟。
- 继续拆分更多发布检查器：当前作品集数量已足够，先改善转化与系列识别。

## 唯一下一步

保持作品集结构不变，等待 `skill-publish-readiness 1.0.7` 至少一个完整 7 天观察窗口；下一次周检只比较自然 downloads、installs 与搜索可见性变化，再决定是否继续加码主入口或转向 `github-actions-clawhub-doctor`。
