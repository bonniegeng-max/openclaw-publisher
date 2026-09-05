# Skill / Plugin 候选池

更新时间：`2026-09-05`

## 当前决策

作品集已有 7 个 Skill，覆盖发布准备、Actions 排障、发布证明、页面转化和组合决策。当前仍不立即发布第 8 个 Skill，先完成从 `2026-09-05 10:26:39`（北京时间）开始的 `Skill Publish Readiness 1.0.8` 自然采用观察窗口；最早决策时间为 `2026-09-12 10:26:39`，且仍须通过全部五项证据闸门。

下一高置信度 Skill 候选调整为 `package-publish-doctor`。ClawHub 官方仓库已出现至少 3 个由不同发布者提交、可复现且失败层不同的 package 发布案例，需求证据已超过“仅有供给空白”；但在观察窗口结束和竞品复核前不进入发布。

首个 Plugin 候选仍为 `skill-catalog-governor`，但还不进入开发。它解决的是 catalog 批量治理，不与 package 发布排障混为一个产品。

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

### GitHub 真实失败案例

`2026-09-05` 对 `openclaw/clawhub` issue 的只读复核发现，Package 发布已经形成独立、重复的问题簇：

| Issue | 失败层 | 证据状态 | 可诊断价值 |
|---|---|---|---|
| [#3275](https://github.com/openclaw/clawhub/issues/3275) | npm 12 改变 `npm pack --json` 结构 | 已关闭，有明确复现与 workaround | 识别“tarball 已生成但 CLI 解析失败” |
| [#3513](https://github.com/openclaw/clawhub/issues/3513) | `bundle-plugin` family 与 `openclaw.plugin.json` 要求冲突 | 开放，`source-repro` | 区分 family 检测、manifest 合约与产品决策 |
| [#3577](https://github.com/openclaw/clawhub/issues/3577) | ClawPack 经过公共边缘上传时返回 413 | 开放，历史复现明确，main 已修但 `v0.23.3` 尚未包含 | 根据 artifact 大小、CLI/workflow 版本和上传路径判断 |
| [#3349](https://github.com/openclaw/clawhub/issues/3349) | publish 返回成功，但版本未进入 latest/version index | 开放，`source-repro` | 识别“成功响应不等于公开可安装” |
| [#3466](https://github.com/openclaw/clawhub/issues/3466) | moderation 为 `CLEAN`，状态仍停在 `pending.publication` | 开放，`source-repro` | 识别 owner 无法自行恢复的发布状态冲突 |

前三项来自不同发布者，且分别发生在打包输出、family/manifest 合约和上传传输层，已满足“至少 3 个独立真实案例”的需求证据。后两项仍属于 Skill 发布后的状态一致性，应并入现有 Doctor / Release Proof Builder，而不是据此再拆一个新产品。

官方 `package-publish.yml@v0.23.3` 已提供 `validate → Inspector → publish → wait` 的机器可验证路径，并要求调用方授予 `actions: read`、`contents: read` 和 `id-token: write`；`package verify` 与 artifact hash 仍需在发布后单独补齐。这证明 Package 发布已经有独立操作面，但版本差异仍会决定诊断结论。

## 下一 Skill 候选

### `package-publish-doctor`

展示名：`ClawHub Package Publish Doctor`

定位：诊断 `clawhub package validate / pack / publish / verify` 与官方 reusable workflow 的失败，不处理普通 Skill 内容审查。

预期输入：

- 失败日志或 GitHub Actions run
- `package.json`、`openclaw.plugin.json` 和 bundle markers
- package family、artifact 类型与大小
- ClawHub CLI / workflow ref、Node 与 npm 版本

预期输出：

1. 失败层：workflow permission / source resolution / pack / family detection / Inspector / upload / moderation / index / verification
2. 直接证据：命令、日志、manifest 或 registry 状态
3. 版本适用性：当前修复是否只在 `main`、已发布 CLI 或指定 workflow ref 中
4. 最小安全修复：不伪造成功、不绕过 Inspector
5. 验证路径：`dry-run → publish → wait → package verify → artifact hash`

与现有产品的边界：

- `github-actions-clawhub-doctor`：继续负责 GitHub Actions → Skill 发布链路。
- `release-proof-builder`：继续负责 Skill 发布后的 E0-E4 证据。
- `package-publish-doctor`：只负责 package/plugin artifact 的打包、上传、审核与验证链路。
- `skill-catalog-governor`：只负责多个 Skill 的 catalog metadata 一致性。

已完成的研究与草案准备：

1. 已建立版本化故障矩阵。
2. 已为 6 个外部核心案例和 1 个本仓库权限案例建立离线 fixture。
3. 已实现覆盖 workflow permission、source resolution、pack、family detection、upload、moderation 和 verification 的只读诊断原型，并用版本边界、provenance 模式、trust 状态和 `surface: package` 负例约束误判。
4. GitHub 精确名称与 slug 预筛未发现同名产品，且已记录证据限制。
5. 已建立包含 `SKILL.md`、changelog、ignore、reference、template 和 example 的完整草案包。

进入正式发布候选前仍需完成：

1. 等待当前 7 天自然增长观察窗口结束，避免连续发布污染采用判断。
2. 只读确认届时 ClawHub 最新 release/workflow ref，刷新版本到已知故障的映射。
3. 用一次同口径 ClawHub 搜索确认没有直接同任务竞品。
4. 将草案提升到 `skills/`、同步 catalog，并完成本地回归。
5. ClawHub dry-run 通过后，才决定是否作为第 8 个 Skill 发布。

## 已进入仓库

| 产品 | 当前角色 | 后续只在有证据时补充 |
|---|---|---|
| `skill-publish-readiness` | 发布前完整审查主入口 | 观察 `1.0.8` 合同修复后的自然采用 |
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

1. ClawHub package registry 出现可安装的 code-plugin，且官方消费路径已稳定。
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
