# ClawHub 作品集增长基线

更新时间：2026-09-05 18:45（北京时间）
发布者：`@bonniegeng-max`  
GitHub 最新 Skill 提交：`2748f047c26c57f9aa85c00a640ed0f5ae45db16`

## 当前结论

作品集已经形成一条清晰主线：发布前审查、发布链路排障、发布后证明和商店页增长。当前 7 个 latest 均已达到 E4。

此前合同修复批次完成了增长决策闸门、显式 slug/name 命令合同、Plugin 发布分支和 E2/E3/E4 证据定义。随后远端并行维护将主入口升级到 `skill-publish-readiness 1.0.9`；该版本已确认 moderation `clean`，并完成一次指定版本隔离安装。

最新主动维护与验收结束于北京时间 `2026-09-05 18:45:38`。此前维护时段、这次发布验收及紧随其后的 downloads / installs 变化全部视为维护污染；新的自然观察起点是 `2026-09-05 18:45:38`，最早在 7 天后且五项决策闸门全部通过时才允许增长或产品组合结论。

## 合同修复验收

GitHub 修复提交：`617239c623fbf95374286a0695cc342aa47aadec`

| Skill | Latest | Display | Moderation | 安装验证 |
|---|---:|---|---|---|
| `skill-publish-readiness` | 1.0.9 | Skill Publish Readiness | clean | 通过 |
| `skill-launch-checklist` | 1.0.3 | Skill Launch Checklist | clean | 通过 |
| `release-proof-builder` | 1.0.3 | Release Proof Builder | clean | 通过 |
| `skill-portfolio-growth-audit` | 1.0.2 | Skill Portfolio Growth Audit | clean | 通过 |

此前 4 个指定版本各执行一次隔离安装；主入口 `1.0.9` 只额外执行了一次限定安装。安装后的核心文件与对应提交 SHA-256 一致。证据见 `release_evidence/2026-09-05-skill-contract-fixes.md` 和 `release_evidence/2026-09-05-skill-publish-readiness-1.0.9.md`。

本轮未修改另外 3 个 Skill，因此未对它们重复执行 dry-run、inspect 或安装；此前 E4 证据继续有效。

### 主动维护后局部读数

以下数值来自本轮 E3 inspect，随后又发生一次 E4 install，只用于保存原始状态，不作为自然增长基线：

| Skill | Downloads | Installs | Versions | Latest |
|---|---:|---:|---:|---:|
| `skill-publish-readiness` | 150 | 1 | 10 | 1.0.9 |
| `skill-launch-checklist` | 73 | 1 | 4 | 1.0.3 |
| `release-proof-builder` | 75 | 1 | 4 | 1.0.3 |
| `skill-portfolio-growth-audit` | 65 | 1 | 3 | 1.0.2 |

这 4 个 Skill 的本轮操作包括 dry-run、publish workflow、inspect 和指定版本 install。任何紧随其后的计数变化均不得解释为外部采用。

## 首次全量修复验收（历史）

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

## 首次全量验收后快照（历史）

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

- 完整周检只运行 `python3 scripts/run_clawhub_growth_monitor.py`，避免绕过观察闸门或只更新一半快照。
- `metrics/observation-policy.json` 将首次允许采样时间锁定为 `2026-09-12T10:45:38+00:00`；在此之前，常规入口即使没有历史快照也必须零请求退出。
- 策略文件缺失或指标/搜索 latest 只存在一侧时必须 fail-closed，不得用重新采样掩盖基线损坏。
- 144 小时防重复门槛固定且不提供生产 CLI 覆盖；`--force` 仅用于明确的版本或审核异常复核。
- `--force` 允许提前采集事实，但在 `notBefore` 前必须把组合结果锁为 `decisionReady: false`，不得提前形成增长结论。
- 两个 `collect_clawhub_*.py` 采集器是内部子命令，必须验证统一入口签发的短时能力；网络 helper 还要求校验后的进程内会话，不得直接执行或导入调用。
- 能力绑定本轮父进程、采集器和暂存输出路径，并在调用 ClawHub CLI 前从环境中移除；它只防误调用，不是本机恶意调用防线。
- 生产入口固定调用 `clawhub`；新快照只有通过 schema、方法、`activeInstall: false`、slug/query 全覆盖及 15 分钟同轮配对校验后才允许轮换基线。
- 统一入口使用单实例文件锁；多文件轮换采用持久化 `prepared` / `committed` journal，若进程被强制终止，下一次启动必须先回滚未提交事务或完成已提交事务清理，再联网。
- 趋势判断使用 `python3 scripts/compare_clawhub_metrics.py <previous> <current>` 离线对比，不重复访问 registry。
- 统一入口生成 `clawhub-growth-decision.json` 与 Markdown 报告；只有指标和搜索两侧的 `evidenceQuality.decisionReady` 同时为 `true`，组合结果才允许进入加码、合并或停更判断。
- 前次与当前两组指标/搜索快照必须分别来自同一观察轮次，采集时间差均不得超过 15 分钟；超出时按跨轮次误拼处理，只能修复数据质量。
- 搜索排名由统一入口按 `metrics/search-queries.json` 每轮各查询一次。
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

## 历史决策（已失效）

以下表格形成于本轮合同修复和主动验收之前，只保留为历史记录，不满足新的 `decisionReady` 闸门，不能用于当前产品动作。

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

保持作品集结构不变，不再发布同类优化版本。下一次增长决策不得早于 `2026-09-12 18:45:38`（北京时间），并且必须满足同采集方法、前后快照均 `activeInstall: false`、间隔至少 7 天、相同 query/limit/query set、前次与当前两组指标/搜索采集时间差均不超过 15 分钟，以及 `evidenceQuality.decisionReady: true`；否则唯一结论是继续观察或修复数据质量。
