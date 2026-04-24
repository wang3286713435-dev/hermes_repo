# Phase 2.11a Context Governance Minimal Implementation

## 目标

在 Phase 2.10 session document scope 基础上，补最小企业上下文治理能力。

## 实现范围

- 扩展轻量 context scope trace：
  - `active_document`
  - `compare_documents`
  - `active_project`
  - `active_task`
  - `history_memory`
- 保持 Hermes_memory retrieval stateless。
- 不改变 retrieval contract。
- 不改变 memory kernel 主架构。

## 优先级

1. explicit `document_id`
2. compare scope
3. active document
4. active project / task hint
5. query title inference
6. ordinary retrieval
7. history memory context

## 防污染规则

- history memory 只能作为上下文提示，不得替代本轮 retrieval evidence。
- `history_memory_as_evidence` 必须始终为 `false`；即使 `history_memory_used=true`，也不能把历史记忆当作 citation/evidence。
- 文件作用域存在但本轮 retrieval 为空时，trace 标记 `no_current_retrieval_evidence`。
- compare scope 只允许 A/B evidence，第三份文件会被过滤并标记 `out_of_scope_evidence_filtered`。
- project/task hint 只进入 trace，不对未知项目强制过滤。

## 语义修正记录

- 真实终端曾出现 `history_memory_used=true` 且 `history_memory_as_evidence=true` 的错误语义。
- 根因归为 trace/上下文语义终态未强制收敛；历史记忆 block 可被使用，但不应被下游理解为 evidence。
- 当前已在 memory kernel result payload 前强制 `history_memory_as_evidence=false`，并在 legacy memory block 中明确其不是 retrieval evidence。

## 真实终端验收结论

- Phase 2.11a 真实终端验收已通过。
- 单文件 A 锁定通过：`retrieval_evidence_document_ids` 仅包含 `1db84714-d49f-48a2-8fa9-c6f73424dd32`。
- `刚才那份文件` 延续通过：retrieval evidence 仍来自 A，未用历史记忆替代证据。
- A/B 对比通过：`compare_document_ids` 与 `retrieval_evidence_document_ids` 同时包含 A/B 两份文件。
- `history_memory_as_evidence=false`，`evidence_source_policy=documentonly`，`contamination_flags=none`。
- 无第三份文件混入，无历史会话记忆替代实时检索。

## Trace 字段

- `context_scope.source`
- `active_document_id`
- `active_document_title`
- `compare_document_ids`
- `active_project`
- `active_task`
- `retrieval_evidence_document_ids`
- `history_memory_used`
- `history_memory_as_evidence`
- `contamination_flags`

## 非目标

- 不实现 Excel/PPTX parser。
- 不实现 OCR / ASR。
- 不推进 facts、权限大改或 rollout。
