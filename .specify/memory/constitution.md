<!--
SYNC IMPACT REPORT
==================
Version change: [1.0.0] (template) → 1.0.0 (ratified)
Bump type: PATCH — placeholder tokens replaced with concrete values; no new principles added or removed.

Modified principles: none (all 7 engineering principles + supporting sections retained verbatim)
Added sections: none
Removed sections: none (bracket token lines removed; content preserved)

Templates reviewed:
  ✅ .specify/templates/plan-template.md — Constitution Check gate placeholder is per-feature dynamic; no update required
  ✅ .specify/templates/spec-template.md — Sections align with validation and quality principles; no update required
  ✅ .specify/templates/tasks-template.md — Observability logging tasks and env-config tasks already present; no update required
  ✅ .specify/templates/commands/ — No command template files found; skipped

Deferred TODOs: none
-->

# Holmes Constitution

## Core Principles

### 软件工程原则

项目要严格符合软件工程设计原则：

| 设计原则 | 一句话归纳 | 目的 |
|---------|-----------|------|
| 1. 开闭原则 | 对扩展开放，对修改关闭 | 降低维护带来的新风险 |
| 2. 依赖倒置原则 | 高层不应该依赖低层，要面向接口编程 | 更利于代码结构的升级扩展 |
| 3. 单一职责原则 | 一个类只干一件事，实现类要单一 | 便于理解，提高代码的可读性 |
| 4. 接口隔离原则 | 一个接口只干一件事，接口要精简单一 | 功能解耦，高聚合、低耦合 |
| 5. 迪米特法则 | 不该知道的不要知道，一个类应该保持对其它对象最少的了解，降低耦合度 | 只和朋友交流，不和陌生人说话，减少代码臃肿 |
| 6. 里氏替换原则 | 不要破坏继承体系，子类重写方法功能发生改变，不应该影响父类方法的含义 | 防止继承泛滥 |
| 7. 合成复用原则 | 尽量使用组合或者聚合关系实现代码复用，少使用继承 | 降低代码耦合 |

### 方案设计原则【重要！！！】

1. 严禁假设输入和用户行为，设计必须尽可能全覆盖所有场景
2. 严禁做特定场景的修复，要思考本质原因，给出通用的根因解决方案
3. 重点考虑边界问题，给出的方案要全面，不要有明显的技术漏洞和考虑遗漏的场景
4. 优先解决主要用户场景，再考虑边缘场景
5. 方案始终以结果为导向，效果最好为第一性原则
6. 除非明确指示，否则不要让新功能违反已经确定的成熟的功能方案
7. 不要过分依赖现有的设计思路，思路可能是错的，除非你评估是准确的


### 环境配置原则

所有配置必须环境化，不允许硬编码。


### 代码整洁原则

生成的代码要根据模块做良好的文件拆分，不要都写在同一个目录，同一个文件下

### 验证原则

所有业务流程，模块必须有自动化验证。禁止只写不测。

### 渐进式实现原则

所有模块优先进行简单实现，严禁无明确收益的抽象层设计。严禁对未来无明确需求时的超前考虑。

### 可观测性原则

所有能力必须有明确清晰的日志，展示日常行为和错误定位。

### 代码规范

代码必须符合Google的代码style要求。

### 质量标准

1. 项目必须保证使用顺畅，用户从最开始使用、后续断点使用等所有场景都需覆盖
2. 用户在使用过程中界面展示优化，所有操作都有明细提示和指引
3. 项目可以保证长时间运行，运行时准确无问题

## 安全

1. 项目要有完整的权限控制体系，对于项目中的敏感操作要考虑权限控制
2. 未确认的功能严禁自行实现

## 知识获取和决策原则

1. 所有提出的决策需得到足够的知识验证，比如创新提出feature或者bug时，需明确相关参考代码或文档的逻辑。汲取经验。并结合本项目需求解决
2. 优先看提供的默认知识来源：https://zhuanlan.zhihu.com/p/2032094280060252204 和 https://github.com/claude-code-best/claude-code

## Governance

1. 所有的功能按模块提交commit，严禁add任何开发过程中的文档，比如specs/**
2. 远端仓库地址为https://github.com/buptwz/holmes-kb
3. 使用804255496@qq.com邮箱提交
4. 本台电脑是ubuntu机器，已装好git、conda

**Version**: 1.0.0 | **Ratified**: 2026-05-26 | **Last Amended**: 2026-05-26
