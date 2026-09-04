# ClawHub 指标快照

`scripts/collect_clawhub_metrics.py` 只调用 `clawhub inspect --json`，不会下载或安装 Skill。

运行：

```bash
python3 scripts/collect_clawhub_metrics.py
```

默认输出：

```text
metrics/clawhub-latest.json
```

下一次成功采集会先把旧的 latest 快照保存为：

```text
metrics/clawhub-previous.json
```

任何一个 Skill 查询失败时，latest 和 previous 都不会轮换。

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
  --output metrics/clawhub-change-report.md
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
