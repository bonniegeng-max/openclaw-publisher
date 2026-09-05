# Skill Publish Readiness 1.0.9 发布证据

## 验收范围

- slug：`skill-publish-readiness`
- 指定版本：`1.0.9`
- GitHub 提交：`2748f047c26c57f9aa85c00a640ed0f5ae45db16`
- 验收原因：远端并行维护产生实质版本变化，需要对 current latest 补齐一次
  限定 E4，并重新建立自然观察起点。
- 安装计划记录时间：`2026-09-05 18:44:51`（北京时间）
- 安装次数上限：本版本一次

## E1-E2

- E1：目标提交已存在于 `origin/main`。
- E2：ClawHub Skill Publish run `33960781848` 成功，publish job 耗时
  `1m 34s`。
- Run：
  <https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33960781848>

## E3

在安装前执行一次指定版本 inspect：

```bash
clawhub inspect @bonniegeng-max/skill-publish-readiness \
  --version 1.0.9 \
  --json
```

结果：

- latest：`1.0.9`
- displayName：`Skill Publish Readiness`
- topics：`publishing`、`release-review`、`github-actions`、`skill-audit`、
  `metadata`
- moderation verdict：`clean`
- registry `SKILL.md` SHA-256：
  `7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9fffb077447210ac`
- 提交内 `SKILL.md` SHA-256：
  `7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9fffb077447210ac`
- 安装前公开原始计数：downloads `150`、installs `1`、stars `0`

以上计数只作为主动验收前记录，不解释为自然用户或独立安装者。

## E4

状态：`passed`

执行结果：

1. 仅执行一次指定版本隔离安装，CLI 返回：
   `Installed skill-publish-readiness v1.0.9`。
2. 实际安装目录为 scoped 路径
   `skills/@bonniegeng-max/skill-publish-readiness`。
3. `SKILL.md`、`CHANGELOG.md` 和
   `references/security_review_guide.md` 的安装文件与提交文件 SHA-256
   均完全一致。
4. `.clawhubignore` 及 examples、references、templates 核心配套文件
   均存在。
5. 临时目录已删除。

| 文件 | SHA-256 |
|---|---|
| `SKILL.md` | `7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9fffb077447210ac` |
| `CHANGELOG.md` | `9c7fd6d7bbc63b3c0ec6586d0b88f5fa9275de116d5de2d24d4a3d2ebfd76550` |
| `references/security_review_guide.md` | `1b0ac936c0505ff30e8e1752cb0b3172fc24a452c687878aa50eaaca2d344cf9` |

E4 完成时间：`2026-09-05 18:45:38`（北京时间）。

## 污染边界

从 `2026-09-05 18:44:51`（北京时间）开始，本次 inspect、指定版本安装及
其紧随其后的 downloads / installs 增量均属于维护者验收，不得归因为
自然采用。

- 新自然观察起点：`2026-09-05 18:45:38`（北京时间）
- 最早允许采样和增长判断时间：`2026-09-12 18:45:38`（北京时间）
- 对应 UTC：`2026-09-12T10:45:38+00:00`
- 后续仍需满足成对快照、同采集方法、双 `activeInstall: false`、固定
  query/limit/query set、至少 7 天和两侧 15 分钟配对闸门。
