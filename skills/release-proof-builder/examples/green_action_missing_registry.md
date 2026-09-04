# 示例：GitHub 已成功，但 Registry 查不到

## 已知信号

- 本地提交已经 push 到 GitHub
- 远端 HEAD 与本地 HEAD 一致
- 发布 workflow 被触发
- `clawhub inspect @owner/new-skill` 返回 not found

## 不能得出的结论

- 不能因为 push 成功就说 skill 已上架
- 不能因为 workflow 启动过就说 registry 已接受
- 不能因为 dry-run 通过就说正式发布成功

## 当前证据等级

`E2 已执行`

## 还需要的证据

- publish job 对目标 skill 的结构化返回
- registry 能读取正确 slug 和版本
- 隔离目录中的真实安装结果

## 推荐下一步

先检查 workflow artifact 或日志中目标 slug 的 publish 状态；如果是上传票据或限流错误，重试正式发布。registry 可见后，再执行安装验证。
