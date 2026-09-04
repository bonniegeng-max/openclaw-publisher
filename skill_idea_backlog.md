# Skill / Plugin 候选池

## 当前定位

优先围绕这条主线扩展：

- ClawHub 发布前质量
- GitHub Actions -> ClawHub 发布排障
- 商店页定位与安装转化

这样能逐步建立一个清晰 IP：`发布与增长工具作者`

## 已进入仓库

### `clawhub-launch-checklist`

- 类型：skill
- 当前作用：轻量入口，先判断这次发布是不是已经值得发
- 后续可继续补：更强的 checklist 输出样式、首屏改写建议、和其他 skill 的路由关系

### `skill-summary-rewriter`

- 类型：skill
- 当前作用：专门改写商店页摘要，承接“定位没错但第一页不够打”的问题
- 后续可继续补：摘要风格切换、短版/长版双输出、与 `skill-positioning-audit` 的联动路由

## 优先级 A

### 1. `clawhub-catalog-optimizer`

- 类型：plugin
- 价值：集中维护 categories、topics、摘要、版本和 changelog
- 原因：当 skill 数量变多后，手工维护成本会上升

## 优先级 B

### 2. `release-proof-builder`

- 类型：skill
- 价值：自动整理发布证据，包括 workflow 状态、公开页、安装命令
- 原因：适合做成“发完后一键核验”

### 3. `skill-series-planner`

- 类型：skill
- 价值：围绕现有 skill 生成系列化扩展方向
- 原因：帮你持续开新题，而不是一次性发完

### 4. `topic-fit-audit`

- 类型：skill
- 价值：检查 categories / topics 是否匹配内容和目标用户
- 原因：直接影响在 ClawHub 里的发现性

## 优先级 C

### 5. `workflow-ref-doctor`

- 类型：skill
- 价值：更聚焦 reusable workflow 引用、版本和兼容性问题
- 原因：是 `github-actions-clawhub-doctor` 的垂直拆分版

### 6. `skill-page-benchmark`

- 类型：skill
- 价值：把你的页面和同类 skill 做结构化对比
- 原因：更偏增长策略，适合后期做

### 7. `trusted-publisher-preflight`

- 类型：plugin
- 价值：专门检查 package trusted publishing 和 OIDC 配置
- 原因：更适合 plugin 发布链路成熟后再做

### 8. `release-change-narrator`

- 类型：skill
- 价值：根据 changelog 和更新内容生成更好的发布说明
- 原因：有助于连贯输出和持续更新

## 选择原则

优先做这类题：

- 来自你真实踩过的坑
- 能和已有 skill 形成系列
- 页面上能一句话说清楚价值
- 用户装完后马上能用，而不是需要复杂接入

先不急着做这类题：

- 过于宽泛的“万能助手”
- 纯概念型 agent 增强
- 需要大量外部服务授权才能用的方向
