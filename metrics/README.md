# ClawHub 指标快照

唯一受支持的在线采集入口是：

```bash
python3 scripts/run_clawhub_growth_monitor.py
```

统一入口内部使用 `scripts/collect_clawhub_metrics.py` 调用 `clawhub inspect --json`，并使用 `scripts/collect_clawhub_search_visibility.py` 执行只读搜索；两者都不会下载或安装 Skill。内部采集器需要由统一入口签发短时能力，且能力绑定当前父进程、脚本名和本轮暂存输出路径；网络 helper 还必须接收校验后生成的进程内会话，因此直接执行或导入调用都会在任何 ClawHub 请求和文件写入前失败。统一入口固定使用当前 Python 解释器，不接受包装解释器覆盖。这个边界用于防止误操作，不用于抵御同一主机上的恶意调用者。

默认输出：

```text
metrics/clawhub-latest.json
metrics/clawhub-search-latest.json
```

下一次成功采集会把旧的 latest 快照保存为：

```text
metrics/clawhub-previous.json
metrics/clawhub-search-previous.json
```

任何一个 Skill 或搜索查询失败时，latest 和 previous 都不会轮换。

快照包含：

- 采集时间与采集方法
- slug、展示名、摘要和 topics
- latest version 与 moderation
- downloads、installs、stars 和 versions
- 明确的数据口径说明

## 使用边界

- downloads 不等于独立用户
- installs 可能包含维护者的 E4 验收
- 单次快照不能证明趋势
- 常规周检不应安装未变化版本
- 如果主动执行过安装，应重新建立自然观察起点

历史判断、污染说明和当前决策仍以根目录 `skill_growth_monitor.md` 为准。JSON 只保存机器可读事实，不自动推断增长原因。

## 对比两个快照

对比器完全离线，只读取已有 JSON：

```bash
python3 scripts/compare_clawhub_metrics.py \
  metrics/clawhub-previous.json \
  metrics/clawhub-latest.json \
  --output metrics/clawhub-change-report.md \
  --json-output metrics/clawhub-change-report.json
```

也可以输出机器可读 JSON：

```bash
python3 scripts/compare_clawhub_metrics.py \
  metrics/clawhub-previous.json \
  metrics/clawhub-latest.json \
  --format json
```

状态含义：

- `verify`：latest 变化、moderation 非 `clean`、Skill 新增或消失，或计数异常回退
- `observe`：出现正向计数变化或非风险元数据变化
- `unchanged`：同口径字段无变化

证据质量含义：

- `eligible`：采集方法一致、两次均明确没有主动安装，且间隔至少 7 天
- `premature`：观察窗口不足 7 天
- `contaminated`：至少一个快照声明执行过主动安装
- `incomparable`：采集方法缺失或不一致
- `insufficient`：时间或主动安装声明缺失

只有 `evidenceQuality.decisionReady` 为 `true` 时，才允许把报告带入下一轮产品加码、合并或停更决策。即使证据质量为 `eligible`，也只能说明观察条件合格，不能证明计数来自独立自然用户。

`observe` 不是“自然增长”结论。对比器只证明两个快照之间存在计数差异，不判断流量来源，也不会自动触发安装。

latest、previous 和默认 Markdown 报告均为本地观察产物，已从 Git 跟踪中排除；公开仓库只保存采集逻辑和口径规则。

## 搜索可见性

`metrics/search-queries.json` 为每个已发布 Skill 保存一条真实任务查询。统一入口的内部采集器会先确认查询配置与 catalog 的 slug 集合完全一致，再逐条执行只读搜索。

默认输出并自动轮换：

```text
metrics/clawhub-search-latest.json
metrics/clawhub-search-previous.json
```

每条记录包含目标查询、目标 Skill 当前排名、是否出现在结果范围内、同页结果和 CLI 版本。不同来源可能展示 60 天 installs、skills.sh lifetime installs、downloads 或 score，这些指标保留原始类型，不混为同一口径。

搜索排名是时间点观察，不是稳定位置。脚本不会执行 inspect、download 或 install；任一查询失败或 CLI 输出格式无法识别时，整轮失败且不写入部分快照。

使用同一个离线对比器生成搜索排名变化报告：

```bash
python3 scripts/compare_clawhub_metrics.py \
  metrics/clawhub-search-previous.json \
  metrics/clawhub-search-latest.json \
  --output metrics/clawhub-search-change-report.md
```

排名状态包括 `up`、`down`、`gained`、`lost` 和 `unchanged`。如果查询文本、查询 limit、查询集合或采集方法变化，证据质量会变成 `incomparable`；不足 7 天或存在主动安装声明时，同样不允许进入增长决策。

## 统一周检入口

必须使用统一入口完成两类采集：

```bash
python3 scripts/run_clawhub_growth_monitor.py
```

执行顺序：

1. 获取 `metrics/.growth-monitor.lock` 单实例锁。
2. 如存在未完成事务日志，先恢复上一套完整基线，再读取 latest 或发起请求。
3. 在 `metrics` 下的临时目录采集采用指标和搜索可见性。
4. 校验两份新快照的 schema、方法、`activeInstall: false`、catalog/query 覆盖及 15 分钟同轮配对；生产 CLI 固定使用 `clawhub`，不接受替代可执行文件。
5. 如果已有 latest，则先在临时目录生成两份 Markdown 报告和对应 JSON sidecar。
6. 合并指标与搜索证据，生成唯一组合闸门。
7. 先持久化 `prepared` journal，再原子轮换正式 latest、previous、Markdown/JSON 报告和组合闸门；全部输出同步后写入 `committed` journal。不可捕获终止由下次启动恢复：`prepared` 回滚旧基线，`committed` 保留新基线并完成清理。

任何子命令失败都会中止本轮，保留上一次完整输出。正式文件替换若在中途失败，已替换目标也会逆序恢复，避免留下指标与搜索时间点不一致的半套基线。首次运行生成 latest 和不可决策的组合闸门；第二次开始才会生成 previous 和差异报告。

组合结果写入：

```text
metrics/clawhub-growth-decision.json
metrics/clawhub-growth-decision.md
```

只有指标与搜索两侧都返回 `decisionReady: true`，且前次与当前两组快照各自的指标/搜索采集时间差不超过 15 分钟，组合闸门才会给出 `review-growth-signals`。任一侧观察窗口不足时返回 `continue-observation`；跨轮次误拼、污染、口径不一致、配置变化或证据格式错误时返回 `repair-data-quality`。

`metrics/observation-policy.json` 记录维护后首次允许采样的 `notBefore` 和原因。策略文件缺失或两类 latest 只存在一侧时，统一入口会 fail-closed 且不发起 ClawHub 请求；常规运行在 `notBefore` 前也会零请求退出。已有完整采集时，统一入口还要求距离两类 latest 中较新的采集时间至少固定的 144 小时，该门槛不接受生产 CLI 覆盖：

```bash
python3 scripts/run_clawhub_growth_monitor.py
```

只有在版本或审核异常需要提前重新采样时，才显式强制运行：

```bash
python3 scripts/run_clawhub_growth_monitor.py --force
```

`--force` 允许在观察截止时间或采样间隔前执行异常复核，只用于版本、moderation、公开文件异常或用户明确要求。提前采集生成的组合闸门在 `notBefore` 前始终保持 `decisionReady: false`；它也不会绕过快照完整性、未来时间校验、`activeInstall` 声明或离线对比器的 7 天证据门槛。
