# 发布证据报告：Skill Publish Readiness 1.0.9

本报告由已有发布证据整理而成，没有重新执行 inspect、install 或发布。
机器可验输入见 `e4-evidence.json`。

## 发布结论

`Skill Publish Readiness 1.0.9` 已达到 E4，可以对这个指定版本声明：

> 已上线、可下载使用。

该结论不自动转移到未来版本，也不证明自然下载或安装增长。

## 当前证据等级

`E4 可安装`

## 已验证证据

| 等级 | 检查项 | 结果 | 证据 |
|---|---|---|---|
| E0 | 版本化源码存在 | 通过 | 仓库包含目标 Skill 与配套文件 |
| E1 | 目标提交进入远端 | 通过 | `2748f047c26c57f9aa85c00a640ed0f5ae45db16` 位于 `origin/main` |
| E2 | 目标 workflow 完成且成功 | 通过 | ClawHub Skill Publish run `33960781848`，结论 `success` |
| E3 | 指定版本、展示名、topics 正确 | 通过 | latest `1.0.9`，displayName `Skill Publish Readiness` |
| E3 | moderation 明确 clean | 通过 | `moderation.verdict: clean` |
| E4 | 指定版本隔离安装 | 通过 | 仅安装一次 `1.0.9`，CLI 返回成功 |
| E4 | 安装文件与源码一致 | 通过 | 3 个核心文件 SHA-256 完全一致 |

## Registry 与源码一致性

`SKILL.md` 的 registry 与源码 SHA-256 都是：

```text
7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9fffb077447210ac
```

公开 metadata：

- latest：`1.0.9`
- displayName：`Skill Publish Readiness`
- topics：`publishing`、`release-review`、`github-actions`、`skill-audit`、
  `metadata`
- moderation：`clean`

## 安装与核心文件

指定版本仅执行一次计划内隔离安装，实际安装目录为：

```text
skills/@bonniegeng-max/skill-publish-readiness
```

| 文件 | SHA-256 |
|---|---|
| `SKILL.md` | `7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9fffb077447210ac` |
| `CHANGELOG.md` | `9c7fd6d7bbc63b3c0ec6586d0b88f5fa9275de116d5de2d24d4a3d2ebfd76550` |
| `references/security_review_guide.md` | `1b0ac936c0505ff30e8e1752cb0b3172fc24a452c687878aa50eaaca2d344cf9` |

`.clawhubignore` 及 examples、references、templates 核心配套文件存在，验收
临时目录已删除。

## E4 安装污染记录

- 安装计划时间：`2026-09-05 18:44:51`（北京时间）
- 安装完成时间：`2026-09-05 18:45:38`（北京时间）
- Slug：`skill-publish-readiness`
- 版本：`1.0.9`
- 原因：远端实质版本变化后的限定 E4
- 安装次数：一次
- 验收前原始计数：downloads `150`、installs `1`、stars `0`
- 新自然观察起点：`2026-09-05 18:45:38`（北京时间）
- 最早允许增长判断：`2026-09-12 18:45:38`（北京时间）

本次 inspect、install 及紧随其后的 downloads / installs 增量不得归因为
自然用户。

## 冲突信号

最终验收范围内没有未解决冲突：

- GitHub 提交与 registry `SKILL.md` 哈希一致。
- Registry 版本、展示名、topics 与预期一致。
- Moderation 为 `clean`。
- 指定版本隔离安装与源码一致。

这不代表未来版本自动继承 E4。

## 缺失证据

对 `skill-publish-readiness 1.0.9` 的 E4 声明没有缺失的必要证据。

仍然没有证明：

- 验收后的计数变化来自自然用户。
- 该版本提升了搜索排名、下载或安装转化。
- 后续版本仍然可安装且内容一致。

## 反事实降级

| 缺失项 | 最高等级 | 禁止声明 |
|---|---|---|
| 只有 workflow success | E2 | 已上架或可下载 |
| moderation 不是明确 `clean` | E2 | 已上架且审核正常 |
| 没有指定版本隔离安装 | E3 | 可下载使用 |
| 安装后没有比较核心文件 | E3 | 安装内容与源码一致 |

## 下一步动作

不重复安装 `1.0.9`。保持自然观察窗口，只有 future latest 发生实质变化时，
才对变化版本执行一次新的限定 E4。
