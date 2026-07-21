# CLI Contracts: 修复 Holmes KB v3 报告缺陷

## US1: holmes kb list --query（数字 tag 兼容）

```
命令: holmes kb list --query <keyword>
变更: 无命令接口变更，仅修复内部 tag 匹配逻辑
前置条件: KB 中可能存在含数字类型 tag 的条目
后置条件: 命令正常返回，不崩溃；数字 tag 被转换为字符串参与匹配
```

## US2: holmes import --dry-run（跳过 LLM）

```
命令: holmes import <file> --dry-run
变更: 无 API Key 时不报错，直接输出文件内容预览
输出格式（变更后）:
  Type:     (unknown)
  Title:    <文件名 stem 或原 title>
  Category: (none)

  --- Preview (dry run) ---
  <文件原始内容前 500 字符>
```

## US3+US4+US5+US7: holmes kb confirm <id>（纠错路径）

```
命令: holmes kb confirm <correction-pending-id> [--contributor <name>]
变更点:
  - created_at 继承自原始条目（US3）
  - contributor 追加到 contributors 列表（US4）
  - Gate 3 长内容（>800 字符）替换截断为提示命令（US5）
  - 输出 maturity 变更信息（US7）

Gate 3 输出（长内容，变更后）:
  Content exceeds 800 chars. To review full content:
    holmes kb pending --show <id>

  Proceed with confirm? [y/N]

Confirm 完成后输出（变更后，追加）:
  maturity: proven → verified
```

## US6: holmes kb pending（空 ID fallback）

```
命令: holmes kb pending
变更: id 为空时显示文件名 stem
输出示例（变更后）:
  FILE-STEM-001              pitfall      Title here...
（原本 id="" 时显示空白，现在显示 FILE-STEM-001）
```
