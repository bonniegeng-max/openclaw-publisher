# Package release 扫描卡住

这个例子用于区分旧版 package 扫描故障与普通 Skill 的 pending publication。

## 输入

```text
surface: package
family: bundle-plugin
clawhub: 0.23.1
publish: accepted with release ID
scan: pending for 24 hours
latestRelease: null
inspect target version: not visible
republish same version: already exists
```

## 结论

```text
diagnosis: PACKAGE_RELEASE_SCAN_STALLED
layer: moderation
confidence: high
versionStatus: fixed-in-release
```

旧版 package 发布已经保留 release，但扫描和公开投影没有完成；`v0.23.2` 已包含对应修复。该规则只适用于明确的 package surface、`bundle-plugin`、受影响版本和完整状态组合。

## 最小修复

升级到包含修复的正式 CLI 后核验原 release 的 scan、latest 与 inspect 状态，不要连续 bump 版本制造更多孤立 release。

## 反例

以下任一情况都返回 `UNKNOWN`：

- 输入来自 `clawhub skill publish`
- CLI 已是 `0.23.2` 或更高版本
- pending 未满 24 小时
- 没有 release ID
- 同版本可以正常重新发布

这些反例可能属于正常异步处理、其他 registry 故障或普通 Skill 发布问题，不能套用历史 package workaround。
