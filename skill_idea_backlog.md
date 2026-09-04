# Skill / Plugin 候选池

更新时间：`2026-09-05`

## 当前决策

作品集已有 7 个 Skill，覆盖发布准备、Actions 排障、发布证明、页面转化和组合决策。当前不新增第 8 个 Skill，先观察 `Skill Publish Readiness 1.0.7` 的自然采用信号。

首个 Plugin 候选暂定为 `skill-catalog-governor`，但还不进入开发。ClawHub package registry 当前没有可观察样本，需求与分发条件都不足以支持正式投入。

## 研究证据

### Skill 搜索

| 查询 | 结果 | 决策 |
|---|---|---|
| `skill metadata catalog topics` | 无直接结果 | 存在供给空白，需求未知 |
| `catalog optimizer` | 无直接结果 | 保留为候选，不立即开发 |
| `skill topics categories` | 无直接结果 | 能力并入 catalog governor |
| `topic category fit audit` | 无直接结果 | 不单独拆 Skill |
| `skill storefront benchmark` | 无直接结果 | 并入 Positioning / Portfolio |
| `publisher analytics portfolio` | 仅自家 Portfolio Growth Audit | 现有 Skill 已覆盖 |
| `release changelog notes` | 多个 ClawHub 结果；skills.sh 同类有 1,000-12,000+ lifetime installs | 通用方向拥挤，不进入 |

### Package 搜索

以下查询均使用 `clawhub package explore --family code-plugin --json`：

- `catalog metadata`
- `topics categories`
- `publisher analytics`

三组结果均为空。随后枚举全部 package family，registry 仍返回 `0` 个结果。

这只能证明当前 CLI 可见范围内没有公开 package 样本，不能证明用户需要一个 Plugin。package 命令已支持 `validate`、`pack`、`publish --dry-run`、moderation 和 artifact verification，技术路径存在，但市场与消费路径尚未形成可观察证据。

## 已进入仓库

| 产品 | 当前角色 | 后续只在有证据时补充 |
|---|---|---|
| `skill-publish-readiness` | 发布前完整审查主入口 | 观察 `1.0.7` 真实案例升级后的自然采用 |
| `github-actions-clawhub-doctor` | GitHub Actions → ClawHub 排障 | 增加新出现且可复现的失败模式 |
| `skill-positioning-audit` | 单页定位与转化诊断 | 吸收 topic fit 和页面 benchmark |
| `skill-launch-checklist` | 低门槛发布入口 | 观察是否形成独立需求 |
| `skill-summary-rewriter` | 商店页摘要改写 | 观察与 Positioning 的重叠程度 |
| `release-proof-builder` | `E0-E4` 发布证明 | 增加机器可读证据前先验证需求 |
| `skill-portfolio-growth-audit` | 作品集组合决策 | 吸收 series planner 和竞争 benchmark |

## 首个 Plugin 候选

### `skill-catalog-governor`

定位：在本地统一检查和维护 Skill 的稳定 slug、人类可读名称、categories、topics、版本与 changelog，并输出可审阅的修复 diff。

预期价值：

- 发现 `SKILL.md` 与 `.clawhub/skill-catalog.json` 的漂移
- 阻止受保护 slug 和目录名不一致
- 检查版本是否高于 registry latest
- 识别 topics 堆砌、重复定位和分类偏差
- 生成 diff，不默认自动发布

不把它拆成多个小 Skill。`topic-fit-audit`、版本一致性和 catalog metadata 维护属于同一个治理任务。

进入开发必须同时满足：

1. ClawHub package registry 出现可安装的 code-plugin 或官方消费路径已稳定。
2. 至少出现 3 个独立的 catalog 漂移或批量维护案例。
3. 能用本仓库 7 个 Skill 做真实回归样本。
4. Plugin Inspector 能在不执行危险代码的情况下完成基础验证。
5. 发布后可以完成 package inspect、moderation 和 artifact verification。

## 合并到现有产品

| 原候选 | 处理 | 原因 |
|---|---|---|
| `topic-fit-audit` | 并入 `skill-positioning-audit` 与 catalog governor | 单独产品过薄 |
| `skill-page-benchmark` | 并入 `skill-positioning-audit` 和 `skill-portfolio-growth-audit` | 与现有定位高度重叠 |
| `skill-series-planner` | 并入 `skill-portfolio-growth-audit` | 组合决策已覆盖系列扩展 |
| `workflow-ref-doctor` | 并入 `github-actions-clawhub-doctor` | 垂直拆分会稀释排障入口 |
| `trusted-publisher-preflight` | 暂缓 | package 生态和真实案例不足 |

## 明确淘汰

### 通用 changelog / release-note 生成

ClawHub 已有多个同类 Skill，skills.sh 同类产品也有较高 lifetime installs。除非未来出现“ClawHub 发布证据自动生成 changelog”这类不可被通用工具覆盖的任务，否则不进入。

### 通用 Skill 更新器

已有成熟产品覆盖 diff、备份、迁移与回滚，不复制。

### 通用安装前安全审查

已有高安装量产品，不做缺乏新壁垒的版本。

## 选择原则

- 问题来自真实失败或重复维护成本
- 目标用户与触发时机能用一句话说清
- 新产品加强现有发布与增长主线
- 输出能被验证，不依赖无法观察的承诺
- 优先扩展已有产品，避免为了数量拆薄能力
- 搜索空白只代表供给缺口，必须另找需求证据
