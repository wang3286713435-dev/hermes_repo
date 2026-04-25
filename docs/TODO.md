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

## Phase 2.11c

- 已完成大标书基础信息 / 元数据召回增强规划。
- 建议优先做轻量 `tender_metadata_snapshot`，再配合基础信息 query profile / section boost。
- metadata snapshot 仅用于检索辅助和引用导航，不得直接替代本轮 retrieval evidence。
- 优先字段：工程名称、工程地点、招标人 / 建设单位、代建单位、最高投标限价、工期、项目编号 / 标段信息。
- Hermes_memory 侧已完成最小实现与真实大标书直接复测；Hermes 主仓库当前只消费 retrieval 返回的 trace，不改 memory kernel 主架构。
- 真实终端验收已通过：围绕 `@主标书` 查询工程地点 / 建设单位 / 代建单位，均命中目标大标书 document_id，evidence 不再落到工程量清单章节。
- `snapshot_as_answer` 终端 trace 语义已复验：即使 `metadata_snapshot_used=true`，snapshot 也只作为导航，回答 evidence 必须来自 retrieval evidence。

## Phase 2.11d

- 已完成上下文治理综合回归小套件规划，覆盖 active document、file alias、A/B compare、tender metadata snapshot、history memory 非 evidence、missing alias suppress retrieval。
- 回归计划包含 15 条真实终端验收 prompt；其中 10 条可用现有文件执行，5 条需要新增第二份大型标书与一份企业制度 / 合同类文件。
- 通过标准要求记录 alias、active document、compare ids、metadata snapshot、retrieval evidence、history memory、suppress retrieval 与 contamination flags。
- 当前仍不写功能代码，不改 retrieval contract，不改 memory kernel 主架构。
- 新增文件已入库并完成回归文件池固定：`@对比标书`、`@交付标准新版`、`@会议纪要` 均完成 chunk 与 OpenSearch 索引。
- 综合回归已执行 15/15 通过；两份大标书、两份数字化交付标准、会议纪要与 missing alias 均未出现跨文件污染。
- 非阻塞尾项：multi-document compare 顶层 trace 暂不聚合每份文档的 metadata snapshot 字段；当前 evidence 与防污染已通过，不阻塞 Phase 2.11d 收口。

## Phase 2.11e

- 已完成 repo hygiene 与 trace polish 边界规划。
- 主仓库 `uv.lock` 作为 dependency hygiene 单独处理；`tests/agent/test_memory_kernel_adapter_reload.py` 作为后续测试任务评审。
- Hermes_memory PRD / Roadmap / Technical Design、Linear 协作文档、DX 脚本、`.run/`、`uv.lock` 已分类建账。
- trace polish 建议只做 compare 顶层 `per_document_metadata_snapshot` 聚合，不改 retrieval contract 或 answer evidence 规则。

## Phase 2.12a

- 已完成 Hermes CLI structured citation 最小修复：Excel evidence/citation 稳定展示 `sheet_name` + `cell_range`；PPTX 稳定展示 `slide_number` + `slide_title`。
- 已修复 Hermes 主仓库 citation normalization 丢 structured metadata 的消费问题：raw citations 会按 `document_id/version_id/chunk_id` 回填 item metadata。
- 已修复 context builder 仅看 `items` 不看 `citations` 的展示缺口，避免 structured citation 在 CLI 上被静默吞掉。
- 5 条 live 复验已通过：Excel 文件锁定、Excel 单项检索、PPTX 文件锁定、PPTX 单页信息、Excel/PPTX 跨类型切回均命中目标 `document_id`，无污染。
- Phase 2.12 真实终端验收已完成，当前只剩 Git baseline 固化；不再需要回退 Hermes_memory parser 或 retrieval contract。

## Phase 2.13

- 已补 Hermes 主仓库会议纪要 trace/context 消费语义：`meeting_transcript_used=true` 只表示本轮 retrieval evidence 命中，`transcript_as_fact=false` 必须保持不变。
- context block 已明确会议纪要是 retrieval evidence only，不是 confirmed facts；后续终端复验需先绑定 `@会议纪要` 与 `@主标书`，再做 compare 防污染验收。
- 真实终端复验已通过：`@主标书`、`@会议纪要` 均绑定成功；行动项 / 决策 / 风险提取保持 `transcript_as_fact=false`；会议纪要与主标书对比允许双 evidence，并未把会议内容误引用为标书条款。
