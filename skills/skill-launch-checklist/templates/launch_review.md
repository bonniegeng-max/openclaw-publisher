# 上线前快速评审

## 上线结论

- 可以发 / 基本可发 / 先别发

## 阻塞项

- 列出必须先补的地方

## 漏项

- 列出容易忽略但会拖累结果的地方

## 最小补法

1. 先补最影响上线结果的一项
2. 再补最影响页面理解的一项
3. 最后执行 dry-run

## 下一步命令

```bash
clawhub skill publish <path> \
  --slug <stable-slug> \
  --name "<Human Readable Name>" \
  --dry-run \
  --owner <owner>
```
