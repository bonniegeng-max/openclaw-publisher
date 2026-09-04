# Changelog

## 1.0.7

- 新增基于真实 GitHub Actions → ClawHub 发布事故整理的复合失败审查案例
- 覆盖受保护 slug、`pending-publication` 误判和上传票据瞬时失效
- 将发布报告模板升级为证据矩阵，补充问题优先级、修复后验收和证据边界
- 在主文档加入 `Built from real publish failures`，强化产品可信度与差异化

## 1.0.6

- 将 frontmatter `name` 统一为人类可读展示名 `Skill Publish Readiness`
- 新增稳定 `slug: skill-publish-readiness`，避免展示名变化影响 registry 标识
- 同步更新页面主标题，强化系列产品的一致性

## 1.0.1

- 将商店页摘要改为中英混合短描述，首屏更快说明它解决什么问题
- 补充 `emoji`，提高在目录和安装页里的识别度
- 为 `skill-publish-readiness` 增加目录级 catalog metadata
- 自动发布时同步写入 `categories` 和 `topics`，避免技能继续落在 `Other`
- 为后续 skill 预留 `.clawhub/skill-catalog.json` 作为统一元数据入口

## 1.0.0

- 创建 `clawhub-publish-assistant-pro` 的首个可发布版本
- 增加面向 ClawHub 发布前的五类检查：
  - 文件完整性
  - 版本与一致性
  - 代码与环境
  - 安全与审核风险
  - 同类 skill 差异化
- 增加真实使用示例与典型失败案例
- 增加差异化评分规则
- 增加配套参考文件、示例文件与输出模板
