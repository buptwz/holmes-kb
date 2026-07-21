# 合成评测集（T034 / spec 043 D7⑤）

NPI 特征合成文档，用于 import 管线的回归评测。每篇文档配一个同名
`.json` 期望文件。所有内容均为虚构（公司/平台/料号/人名），仅为
模拟真实半导体测试文档的形态与密度。

## 两层评测接入方式

- **a) 结构层（默认测试套件，无 LLM）**
  `TestEvalFixturesStructural`（`kb/tests/test_eval_regression.py`）：
  文档加载与大小、outline 提取、零 LLM 结构信号
  （`analyze_document_structure`）、Direct mode 阈值边界与按文档路由
  （`DIRECT_MODE_CHAR_LIMIT`）、多主题切分（`_run_multi_topic`，
  用脚本化 MockProvider 驱动 Classifier，测的是确定性切分逻辑）。
  运行：`cd kb && python -m pytest tests/test_eval_regression.py`

- **b) 标记层（真实 LLM）**
  `TestEvalFixturesLLM`，带 `llm` marker，默认跳过。断言期望 JSON
  `survival` 各字段（关键命令/数字/分支/物理步骤/steps/行为标签/
  关键术语）在管线产出条目中的存活率（对多主题文档合并所有产出
  条目后判定）。运行：
  `HOLMES_LLM_TESTS=1 pytest tests/test_eval_regression.py -m llm`

注意：目录下另有 `ground_truth.yaml` 与 `fixtures/npi/`（更早的
三层评测，Layer 1/2/3），与本评测集相互独立，均走 `llm` marker。

## 期望 JSON 字段

- `source`：文档文件名（相对本目录）
- `design_intent`：设计意图
- `expected_type` / `expected_language`：期望类型/语言（`null` = 不断言）
- `structural`：a 层断言——`min_chars`、`expect_direct_mode`、
  `expect_multi_topic`、`expect_empty_outline`、`min_outline_sections`、
  `expected_headings`（子串匹配）、`min_ordered_steps` /
  `min_symptom_mentions` / `min_rule_mentions`
- `survival`：b 层断言——`commands` / `numbers` / `branches` /
  `physical_steps` / `steps`（对齐 D7 IR 的 steps 字段）/
  `behavior_tags` / `key_terms`，均为产出条目中的子串存活检查

## 文档清单与基线（a 层实测值，2026-07-20）

| 文档 | 意图 | 字符数 | 标题数 | steps | symptom | rule |
|------|------|--------|--------|-------|---------|------|
| pll_lock_failure_tree.md | 超长多分支 pitfall 排查树（>20K，6 分支，物理量测与远程命令混排） | 20058 | 72 | 15 | 38 | 39 |
| eye_diagram_jitter_notes.txt | 信息密集无结构纯文本（无标题，命令密集） | 1019 | 0 | 0 | 2 | 0 |
| mixed_topics_weekly_log.md | 多主题混合（pitfall + process + guideline 拼合） | 1272 | 6 | 6 | 2 | 11 |
| power_sequencing_bilingual.md | 中英混排 pitfall（PMIC 冷上电锁死） | 1416 | 1 | 5 | 4 | 1 |
| i2c_register_dump_process.md | 标准 process 流程文档 | 1094 | 7 | 10 | 2 | 2 |
| oscilloscope_measurement_guideline.md | guideline 规范文档（必须/禁止条款密集） | 999 | 8 | 13 | 1 | 26 |
| pcie_gen5_retrain_storm_en.md | 英文 pitfall（Gen5 链路 retrain 风暴） | 1743 | 4 | 4 | 1 | 0 |

说明：`steps`/`symptom`/`rule` 为 `analyze_document_structure` 的零
LLM 计数（有序步骤数 / 症状关键词出现数 / 规范关键词出现数）。
pll 文档（20058 字符 > 8000）走 tool loop，其余走 Direct mode；
`mixed_topics_weekly_log.md` 期望多主题切分为 3 段。

## 新增文档步骤

1. 把 `.md`/`.txt` 放入本目录；
2. 写同名 `.json` 期望文件（字段见上）；
3. a 层自动参数化接入；b 层用 `HOLMES_LLM_TESTS=1` 跑一遍确认阈值。
