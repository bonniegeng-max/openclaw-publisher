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
