# Holmes 场景手册

> 不看概念，不看命令表——找到你要干的事，照着做就行。
> 完整的命令参数查 `docs/reference.md`，运维细节查 `OPERATIONS.md`。

## 你只需要知道 3 个概念

- **条目**：一条结构化知识（Markdown 文件），比如"PLL 锁失败的排查树"
- **pending**：新知识的"待审批区"——**机器永远不能直接把知识写进正式库，必须人审一遍**
- **成熟度**：`draft → verified → proven`，靠真实使用反馈自动升级，代表这条知识可不可信

---

## 场景 1：我第一次用，怎么装好并让我的 agent 连上？

```bash
# 1. 安装（仓库根目录）
pip install -e ./kb

# 2. 建知识库（从模板复制，git 管理）
cp -r kb-template ~/holmes-kb && cd ~/holmes-kb && git init && git add . && git commit -m init

# 3. 配置（知识库路径 + 你的 LLM + 你的身份）
holmes setup --kb-path ~/holmes-kb --model deepseek-v4-flash \
  --api-base-url https://your-llm-gateway/v1 --api-key sk-xxxx
holmes config set username 你的名字      # 你的贡献会记在这个身份下

# 4. 启动 MCP server（本地模式，只监听本机）
holmes start                             # 默认 8765 端口

# 5. 在你的 agent 产品里配置 MCP 连接
#    { "mcpServers": { "holmes-kb": { "type": "http", "url": "http://localhost:8765/mcp" } } }
```

验证：在 agent 里问"知识库里有什么"，它应该能列出条目。

---

## 场景 2：我有一堆团队文档（排障报告/SOP），怎么灌进知识库？

```bash
# 先预览一篇，看 LLM 理解得对不对（不写盘）
holmes import ./docs/pll-troubleshooting.md --dry-run

# 没问题就正式导入（进 pending 待审批区，不是直接入库）
holmes import ./docs/pll-troubleshooting.md

# 批量导一个目录
holmes import --dir ./docs/

# 看看 pending 里都有什么
holmes pending

# 逐条审阅发布（这时才进正式库，分配永久 ID）
holmes approve pending-20260720-153000-ab1f

# 或批量全部审批（仍带查重门控，逐条自动确认）
holmes approve --all --no-interactive
```

> 提示：原文档里的**图片/波形截图**不会进入条目（文本管线读不了图）；如果条目里丢了图，末尾会有一行"📷 原文档含 N 张配图…请查阅源文件"的标注，agent 会据此引导你去看原图。

注意：import 一篇 4-20K 字符的文档约需 2-10 分钟（真实 LLM 调用），批量导入请耐心等待。文档很长时可调大读取段长：`holmes config set read_chunk_chars 30000`。

---

## 场景 3：排查问题时，我和 agent 各自该干什么？

你只需要做三件事：

1. **报障时带上背景**："Granite Rapids 平台 DVT 阶段，PLL 锁不上"——产品线/阶段越具体，agent 过滤越准
2. **配合物理操作**：agent 看到 `[physical]` 标签的步骤（量信号、插拔卡）会请你动手；`[api:write]`/`[api:danger]` 的写命令它会先征求你同意
3. **结束后告诉 agent 结果**："解决了" 或 "没解决"——agent 会据此向知识库反馈，解决的知识会变得更可信（成熟度提升）

其余（查库、读条目、走分支、反馈）agent 全自动。

---

## 场景 4：知识库里没有答案，问题解决后怎么把经验留下来？

```bash
# agent 在没查到条目时会自动存草稿到 _drafts/（你也可以让它存）

# 你定期把草稿结构化导入
holmes drafts                            # 看看有哪些草稿
holmes import _drafts/xxx.md             # 走正常 import 流程
holmes approve pending-xxxx              # 审批入库
```

---

## 场景 5：我发现某条条目内容写错了，怎么修？

**内容错误**（步骤错、值过时）→ 走纠错流程，人审裁决：

```bash
# 1. 把修正后的内容写成 md 文件（自己改或让 agent 改）
# 2. 提交修正提案，指向错的条目
holmes write-pending --file fix.md --corrects PT-DB-a3f8c2
# 3. 审批——修正版入库，旧条目自动作废（有快照可回滚）
holmes approve pending-xxxx
```

**形式瑕疵**（标签贴错、`firmware: "unknown"` 之类，通常是旧版 import 留下的）→ 机器直接修：

```bash
holmes doctor            # 会报"行为标签疑似误标""占位噪声"
holmes doctor --fix      # 机械修复，不动内容
```

**注意**：agent 按某条目排查没解决时，知识库会记下 not_solved 反馈；`holmes doctor` 会把这些条目列出来提醒人工复核——这是发现"内容过时"的主要线索。

---

## 场景 6：知识库的日常健康维护怎么做？

```bash
holmes doctor                 # 每周：综合体检（索引、证据、卫生、反馈）
holmes doctor --fix           # 每月：连体检带修复
holmes pending                # 随手清：超期 pending 要么 approve 要么 reject
holmes decay --dry-run        # 每季：预览成熟度衰减（长期没人用的知识自动降级）
holmes decay                  # 确认后执行
```

管线升级（holmes 版本更新）后，跑一次 `holmes doctor --fix` 翻新旧条目。

---

## 场景 7：团队多人共用一个知识库（git 协作）

知识库就是一个 git 仓库，各自 clone、本地使用、push 共享：

```bash
# 日常同步（一键：pull --rebase + 自动合并冲突 + 重建索引）
holmes sync

# 本地导入/审批后推送（approve 后命令会提醒你提交）
git add -A && git commit -m "add xxx" && git push

# 如果 sync 报告有需要人工裁决的内容矛盾：
holmes resolve <id> --keep A  # 或 --keep B（A=本地 B=远端）
```

索引文件和日志不会冲突（设计如此）；只有同一条目被两人改成不同内容时才需要人工裁决。

---

## 场景 8：部署一个全团队共用的中心 server（管理员）

```bash
# 中心服务器上
holmes config set mcp_token 一个足够长的随机串
holmes start --mode central --port 8765     # 监听 0.0.0.0，强制 token + 身份

# 每个工程师的 agent 配置：
#   url: http://中心服务器:8765/mcp
#   headers: { "Authorization": "Bearer 同一个token" }
# 并要求 agent 调用时声明 contributor（否则 central 模式拒绝记录反馈）
```

中心模式下：每条使用反馈都记到真实的人名下（成熟度统计才准确）；发布/删除等管理操作仍然只能在服务器上用 CLI 做，agent 碰不到。

---

## 场景 9：我 import 出来的条目质量不好/类型判错了

```bash
# 类型判错：导入时强制指定（跳过 LLM 分类）
holmes import ./doc.md --type process

# 分类/标题/标签不满意：导入时直接覆盖
holmes import ./doc.md --category hardware --title "更准确的标题"

# 已经进 pending 了：直接改 pending 文件再 approve
vim ~/holmes-kb/contributions/pending/pending-xxxx.md
holmes approve pending-xxxx

# 已经入库了：走场景 5 的纠错流程
```

---

## 常见问题速答

- **agent 连不上 server**：`holmes doctor` 看 KB 路径；`curl http://localhost:8765/mcp` 应返回 406（不是 000/拒绝）
- **agent 反馈被拒 missing_session_id**：agent 需要先调 kb_browse 拿 session_id 并全程携带（guide 里有写，重连 agent 让它读到最新工具说明）
- **升级 holmes 后 agent 行为不对**：MCP 客户端缓存了旧工具 schema，**重连/重启 agent**
- **import 太慢**：正常（真实 LLM 多次调用），可 `holmes config set read_chunk_chars 30000` 提速
- **条目 ID 不是连号的**：正常，新 ID 是 `PT-DB-a3f8c2` 式随机后缀（防止多人协作撞号）
