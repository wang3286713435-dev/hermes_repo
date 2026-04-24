# TODO

## Phase 2.10

- 已完成同一 Hermes 会话内 active document 最小实现。
- 已修复 multi-document compare scope：对比 A/B 时分别 scoped retrieval 后合并 evidence，禁止第三份文件混入。
- 真实 Hermes 终端 A -> B -> A -> A/B 对比验收已通过，同一会话文件切换不再依赖新开会话。
- 后续如进入更强文件作用域能力，再评估多文件对比排序、摘要与引用编排增强。

## 非本阶段缺口

- dense ingestion 未接通。
- 当前仍是最小实现，不代表完整企业上下文系统全部完成。
- facts、权限治理、完整审标自动化不属于 Phase 2.10 最小实现。

## Phase 2.11a

- 已完成最小企业上下文治理增强：project/task hint、history memory 非 evidence 标记、retrieval evidence trace、污染诊断规则。
- 已修复 `history_memory_as_evidence` 语义：历史会话记忆可 used，但不得作为本轮 retrieval evidence 或 citation。
- 真实终端验收已通过：A 锁定、刚才文件延续、A/B 对比均使用本轮 retrieval evidence；`history_memory_as_evidence=false`，无第三份文件混入。

## Phase 2.11b

- 已完成 session-level 企业文件别名最小实现：alias 绑定 `document_id`，title/source_name/version_id 仅作展示与诊断。
- 已支持 title 绑定、当前 active document 绑定、alias scoped retrieval、双 alias compare、missing 不回退 active document、rebind 可诊断。
- alias missing / compare partial 时会抑制本轮 retrieval，避免普通检索偶然带回旧文件 evidence。
- 已修复真实终端暴露的会话层绑定问题：alias binding 不依赖模型工具；当前文件绑定可在本轮 retrieval 唯一命中文档后写入 session alias。
- 已补 alias trace：`alias_resolution.status`、`alias`、`resolved_document_id`、`resolved_title`、`alias_scope=session`、`alias_conflict`、`alias_missing`、`alias_stale_version`、`suppress_retrieval`。
- 真实终端验收已通过：`@主标书`、`@交付标准` 绑定与使用成功；双 alias 对比同时召回两份文件；missing alias 成功抑制 retrieval。
- 质量尾项：`@主标书` 已成功解析，但工程地点 / 建设单位 / 代建单位未被召回，属于大型标书基础信息召回问题，不阻塞 Phase 2.11b。
- project-level alias 持久化仍未实现，后续如进入项目级知识库治理需单独设计。
