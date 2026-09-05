# OpenClaw Publisher 自动化操作契约

本文件约束在本仓库中执行发布、验收、增长巡检和新方向评估的 Agent 与自动化任务。目标是保持 GitHub、ClawHub 和本地证据一致，同时避免维护行为污染自然采用数据。

## 核心原则

- 事实优先于推测，registry 与独立安装结果优先于本地意图。
- downloads、installs、stars 和搜索排名必须分开记录。
- downloads 不等于独立用户，installs 可能包含维护者验收。
- 不把单次快照、短期零增长或维护流量解释为市场结论。
- 不为制造活跃度而发布无实质变化的版本。
- 不自动发布未经验证的新 Skill 或 Plugin。

## 发布约束

- Skill slug 不得以 `clawhub-` 开头或以 `-clawhub` 结尾。
- 每个 Skill 必须包含 `SKILL.md`、`CHANGELOG.md` 和 `.clawhubignore`。
- `.clawhub/skill-catalog.json` 是展示名、categories 和 topics 的唯一仓库级来源。
- 发布命令必须显式传递稳定 `--slug` 和人类可读 `--name`。
- 自动发布只处理发生实质变化的目录。
- 确定性错误立即失败；只对已识别的瞬时上传错误进行有限退避重试。
- 不在日志、报告、Issue 或提交中输出 token、密钥或认证头。

## 证据等级

- `E0`：仅有本地文件。
- `E1`：GitHub 远端包含目标提交。
- `E2`：目标发布 workflow 已执行成功。
- `E3`：ClawHub registry 返回正确版本、展示名、topics 和 `clean` moderation。
- `E4`：指定版本完成一次隔离安装，核心文件与对应 GitHub 提交一致。

只有达到 `E4` 才能声明“已上线、可下载使用”。GitHub push、workflow 绿灯或 dry-run 不能单独替代 E3/E4。

## 常规周检

常规周检只运行一次统一入口：

```bash
python3 scripts/run_clawhub_growth_monitor.py
```

执行要求：

- 不在同一轮再次单独运行指标或搜索采集器。
- 两个 `collect_clawhub_*.py` 仅是内部子命令，必须由统一入口签发并绑定本轮暂存路径的短时能力；网络 helper 还必须持有校验后的进程内会话，不得直接执行或导入调用。
- 遵守 `metrics/observation-policy.json` 的 `notBefore`；无历史快照时也不得提前首次采样。
- 策略文件缺失或指标/搜索 latest 只存在一侧时必须 fail-closed，不得在线补采样。
- 默认 144 小时防重复门槛不得绕过。
- 不执行 install、download、publish、dry-run 或隔离安装。
- 不修改 Skill 文件、版本号或 catalog。
- 只读取生成的 latest、previous、差异报告和 `clawhub-growth-decision` 组合闸门。
- 任一子步骤失败时保留上一轮完整基线，不用部分结果做判断。

只有版本变化、moderation 异常、公开文件缺失或用户明确要求时，才允许使用：

```bash
python3 scripts/run_clawhub_growth_monitor.py --force
```

`--force` 只允许提前重新采样，不代表允许安装或跳过证据门槛；`notBefore` 前的强制采集必须保持 `decisionReady: false`。

## 增长判断

采用指标和搜索可见性必须同时满足，且以 `clawhub-growth-decision.json` 的组合结果为唯一决策入口：

- `evidenceQuality.decisionReady` 为 `true`
- 采集方法一致
- 两次快照均明确为 `activeInstall: false`
- 观察窗口至少 7 天
- 搜索查询文本、limit 和查询集合保持一致
- 前次与当前两组指标/搜索快照的采集时间差均不超过 15 分钟

若任一条件不满足，结论只能是“继续观察”或“修复数据质量”，不得据此：

- 宣称自然增长
- 合并或停更 Skill
- 修改定位与关键词
- 新建相邻同质化 Skill
- 启动 Plugin 开发

## 决策顺序

证据合格后按以下顺序处理：

1. moderation、可发现性或发布状态异常：先修复。
2. latest 变化但未完成 E4：只对变化版本执行一次限定范围验收。
3. 采用信号增长且搜索稳定：优先加码已有 Skill。
4. 搜索下降但采用信号稳定：先诊断标题、摘要、topics 和任务词匹配。
5. 无采用信号且搜索稳定：继续观察，不用短期零值判定失败。
6. 只给一个最高优先级动作，其余进入候选池。

## E4 验收边界

- 未变化版本不得重复安装。
- 每个变化版本最多执行一次计划内隔离安装。
- 安装前记录时间、slug、版本和原因。
- 安装后验证 `SKILL.md` 与对应 GitHub 提交一致。
- 完成后重新建立自然观察起点。
- 验收时段及紧随其后的 downloads 与 installs 增量不得归因为自然用户。

## 新方向门槛

优先优化已有采用信号的 Skill。新 Skill 必须同时具备：

- 独立、可描述的用户任务
- 至少一个真实失败或重复需求证据
- 与现有 7 个 Skill 不重复
- 可定义输入、输出、失败边界和验收方法
- 能强化“ClawHub 发布与增长工具作者”主线

`skill-catalog-governor` 是当前首个 Plugin 候选，但只有同时满足以下条件才启动：

- package registry 或官方消费路径稳定
- 至少 3 个独立 catalog 漂移案例
- 可用现有 7 个 Skill 做真实回归
- Plugin Inspector 可安全验证
- 可完成 package inspect、moderation 和 artifact verification

## 修改与提交

提交前至少运行：

```bash
python3 -m unittest discover -s tests
python3 -m py_compile scripts/*.py tests/*.py
git diff --check
```

涉及 workflow 时额外验证 YAML 可解析。推送后确认：

- 本地 `HEAD` 与 `origin/main` 一致
- 对应 GitHub Actions 运行完成且成功
- 检查 Actions annotations；运行时弃用或权限警告不能仅因结论为 success 而忽略
- 若改动触发 ClawHub 发布，再按 E0-E4 逐级验收

## 通知规则

以下情况才主动提醒：

- 发布或 CI 失败
- moderation、latest 或可下载状态异常
- 指标达到完整观察窗口并出现实质变化
- 搜索可见性出现 `gained`、`lost` 或明显升降
- 需要人工授权或外部操作
- 出现满足门槛的高置信度新方向

没有实质变化时保持简洁，不重复汇报相同状态。
