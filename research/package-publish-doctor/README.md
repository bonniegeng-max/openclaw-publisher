# ClawHub Package Publish Doctor 研究包

状态：`research-prototype`
更新时间：`2026-09-05`

这里保存 `package-publish-doctor` 的发布前研究证据和离线 fixture。它不是可发布 Skill，不在 `.clawhub/skill-catalog.json` 中，也不会触发 ClawHub Skill 发布。

## 产品边界

目标任务是诊断 ClawHub package/plugin artifact 的发布链路：

```text
source
  → package validate
  → npm pack / ClawPack
  → family 与 manifest 判定
  → Plugin Inspector
  → upload
  → publication wait
  → package verify
  → artifact hash
```

不处理：

- 普通 Skill 的内容质量与差异化
- Skill catalog metadata 批量治理
- GitHub Actions → Skill 发布的常规故障
- 绕过 Inspector、moderation 或可信发布边界

## 版本故障矩阵

| Case | 受影响证据 | 当前状态 | 诊断信号 | 安全建议 |
|---|---|---|---|---|
| `npm-pack-json-shape` | `clawhub@0.23.1` + npm 12 | Issue 已关闭，修复落在哪个正式 release 尚未确认 | tarball 已生成，但 CLI 报 `npm pack did not return a tarball filename` | 判断 stdout 是数组还是对象；必要时在 job 内临时固定 npm 11 |
| `bundle-native-manifest-contract` | `clawhub@0.23.3`，且 issue 声明 current main 仍可复现 | 等待产品与安全决策 | 检测到兼容 bundle markers，但缺少根目录 `openclaw.plugin.json` | 不伪造 native manifest；明确这是合约阻塞，不是目录缺失 |
| `clawpack-staging-gap` | `package-publish.yml@v0.23.3` / 对应 CLI | main 已修复，最新 release `v0.23.3` 尚未包含 | artifact 大于约 4 MiB、低于旧 18 MiB 阈值，通过公共边缘上传返回 413 | 优先升级到包含修复的正式版本；发布前不要依赖未发布的 main |
| `reusable-workflow-actions-read` | 调用官方 `package-publish.yml@v0.23.3` | 本仓库已修复 | workflow 在创建 job 前报 nested job 请求 `actions: read` | 调用方显式授予 `actions: read`，保留最小权限 |

## 证据来源

- [npm 12 pack 输出结构变化](https://github.com/openclaw/clawhub/issues/3275)
- [bundle-plugin 与 native manifest 合约冲突](https://github.com/openclaw/clawhub/issues/3513)
- [ClawPack 公共边缘 413](https://github.com/openclaw/clawhub/issues/3577)
- [官方 Package Publish workflow v0.23.3](https://github.com/openclaw/clawhub/blob/v0.23.3/.github/workflows/package-publish.yml)
- [ClawHub 最新 release v0.23.3](https://github.com/openclaw/clawhub/releases/tag/v0.23.3)
- [本仓库权限修复后的成功运行](https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33932342586)

## 离线 fixture

`fixtures/` 中的 JSON 只保存判定所需的最小输入，不访问 registry、不执行安装、不生成大型二进制：

- `npm-pack-json-shape.json`：同一 tarball 在 npm 11/12 下的输出形状差异
- `bundle-native-manifest-contract.json`：兼容 bundle markers 存在但 native manifest 缺失
- `clawpack-staging-gap.json`：真实案例中的 artifact 大小与两个上传阈值
- `reusable-workflow-actions-read.json`：调用方权限不足导致 workflow 启动失败

这些 fixture 的目标不是模拟 ClawHub 服务端，而是固定诊断器必须识别的事实边界。`diagnose.py` 会输出结构化诊断，`tests/test_package_publish_doctor_research.py` 会验证 fixture 完整性、预期分类以及避免误判的负例。

本地运行：

```bash
python3 research/package-publish-doctor/diagnose.py \
  research/package-publish-doctor/fixtures/clawpack-staging-gap.json
```

输出只包含诊断层、证据、建议和来源，不执行网络请求或修复动作。无法满足完整判定条件时必须返回 `UNKNOWN`，不能根据单个错误关键词猜测根因。

## 启动门槛

只有同时满足以下条件，才把研究包升级为正式 Skill：

1. 当前 7 天自然增长观察窗口结束。
2. 重新确认最新 ClawHub release 与官方 workflow ref。
3. 完成一次同口径竞品搜索，确认没有直接同任务产品。
4. 至少保留当前 4 个离线 fixture，并为新增规则同时提供正例和负例。
5. 输出必须区分“已修复但未发布”“当前仍可复现”“需要维护者决策”。
6. 本地测试与 ClawHub dry-run 通过后，才允许加入 catalog 和发布。
