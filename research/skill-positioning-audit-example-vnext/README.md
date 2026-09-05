# Skill Positioning Audit 示例修复草案

状态：`observation-window-hold`

本目录保存已发布 `skill-positioning-audit` 的下一版示例候选，不是新 Skill，
不进入 catalog，也不触发 ClawHub 发布。

## 已确认问题

正式示例的“更强定位版本”把标题写成：

```text
skill-positioning-audit
```

同一 Skill 的正文却把“标题像内部目录名”列为主要问题，catalog 的权威展示名
也已经是 `Skill Positioning Audit`。示例因此混淆了两个不同字段：

- `displayName`：用户在商店页看到的人类可读产品名。
- `slug`：发布、安装和路由使用的稳定标识。

这是仓库内容可直接证明的自相矛盾，不需要增长数据才能进入修复候选。

## 候选修复

完整示例将使用：

- 展示名：`Skill Positioning Audit`
- 稳定 slug：`skill-positioning-audit`
- 当前版本：`1.0.4`

并按正式模板补齐：

1. 页面定位结论。
2. 当前最大问题。
3. 最小改法。
4. 差异化判断。
5. 可直接替换的标题、摘要与首屏第一段。
6. 五维 rubric 评估及证据边界。

## 文件

- `positioning-evidence.json`：机器可验的 catalog、旧示例和候选输出。
- `complete_positioning_review.md`：候选完整定位报告。

## 声明边界

- rubric 分数是基于仓库内容的编辑评估，不是 ClawHub 排名或转化指标。
- 候选文案没有经过平台 A/B 测试。
- 修复示例自相矛盾不等于证明当前标题造成下载损失。
- 是否提升正式版本仍等待自然观察窗口后的真实采用与搜索证据。

## 提升条件

1. 不早于 `2026-09-12T10:45:38+00:00` 运行统一增长监控。
2. 确认 Positioning Audit 仍有独立任务需求。
3. 将示例修复与运行 metadata 修复合并为一次实质版本。
4. 保持 slug 不变，不因展示名优化创建新 registry ID。
5. 发布后只对变化版本执行一次 E4，并重建观察起点。
