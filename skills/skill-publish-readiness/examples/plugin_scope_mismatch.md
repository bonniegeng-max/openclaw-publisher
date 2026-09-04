# 示例：plugin scope 与 owner 不匹配

## 假设输入

- plugin 目录：`plugins/release-bot/`
- `package.json` 名称：`@openclaw/release-bot`
- 实际准备发布的 owner：`bonniegeng-max`

## 问题点

- package scope 是 `@openclaw`
- 但发布 owner 是 `bonniegeng-max`
- 这两者不一致

## 预期判断

- 发布结论：`不可直接发布`
- 阻塞问题：package scope 与 owner 不匹配
- 风险问题：如果继续沿用当前命名，会误导用户对归属的理解

## 最小修复路径

二选一：

1. 把 owner 改成与 package scope 一致的发布方
2. 把包名改成 `@bonniegeng-max/release-bot`

## 为什么这个例子重要

很多 plugin 不是失败在代码本身，而是失败在发布归属和命名规则上。这个例子用来提醒用户：ClawHub 的 plugin 发布不是只看代码是否能跑，还要看命名空间是否合理。
