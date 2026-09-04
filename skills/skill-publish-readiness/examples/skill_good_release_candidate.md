# 示例：较成熟的 skill 发布候选

## 假设输入

- 目录：`skills/release-note-writer/`
- 文件：
  - `SKILL.md`
  - `CHANGELOG.md`
  - `examples/`
  - `templates/`
- frontmatter 具备：
  - `name`
  - `description`
  - `version`
  - `metadata.openclaw.requires.bins`
  - `metadata.openclaw.envVars`

## 典型特征

- 标题、目录名、slug 和能力描述一致
- 文案明确目标用户，例如“负责发布说明和变更摘要的开发者或 PM”
- 示例里没有硬编码 token
- 输出结果不是泛泛建议，而是明确报告与下一步命令
- 适用场景足够窄，不是“适合所有人”

## 理想判断

- 发布结论：`可发布`
- 阻塞问题：无
- 风险问题：可选优化项，例如增加更多真实案例
- 差异化评分：`19-22/25`

## 为什么它更像成品

- 文件完整
- 元数据自洽
- 用户安装后知道怎么用
- 页面读完后能记住它服务哪类人
