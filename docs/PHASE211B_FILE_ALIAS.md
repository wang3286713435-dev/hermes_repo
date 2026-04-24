# Phase 2.11b Enterprise File Alias

## 目标

解决真实企业使用中文件标题过长、反复引用困难的问题，在 Phase 2.10/2.11a 的文件作用域与上下文治理基础上，规划轻量文件别名能力。

示例：

- 将《福田区园岭街道兄弟高登...招标文件》设为 `@主标书`
- 将《附件十一：数字化交付标准》设为 `@交付标准`
- 后续可说：围绕 `@主标书` 回答
- 可说：对比 `@主标书` 和 `@交付标准`

## 实现结论

- alias 必须绑定到 `document_id`，不能只绑定 title。
- alias 可保留 `document_title`、`version_id`、`source_type`、`document_type` 作为诊断与展示字段。
- session-level alias 已完成最小实现。
- project-level alias 只做规划，不在本阶段实现持久化。
- Hermes_memory retrieval 继续保持 stateless，不改 retrieval contract。

## 最小实现范围

1. `SessionDocumentScopeStore` 内部 session alias store
   - 按 `session_id` 维护 alias 映射。
   - 字段建议：
     - `alias`
     - `document_id`
     - `document_title`
     - `version_id`
     - `scope_source`
     - `updated_at`
2. alias 设置语义
   - “把 A 设为 @主标书”
   - “将当前文件命名为 @交付标准”
   - “@主标书 指向这份招标文件”
3. alias 使用语义
   - “围绕 @主标书 回答”
   - “切到 @交付标准”
   - “对比 @主标书 和 @交付标准”
4. compare mode
   - 支持 `@A` / `@B` 解析成两组 `document_id`。
   - 继续在 Hermes adapter/orchestrator 层做 scoped retrieval 合并。
   - 禁止第三份文件 evidence 混入。

## 检索优先级

1. explicit `document_id`
2. resolved file alias
3. compare scope
4. active document
5. active project / task hint
6. query title inference
7. ordinary retrieval
8. history memory context

alias 一旦解析成功，应转化为明确 `document_id` scope，再进入现有 session document scope / compare scope 流程。

## 已完成行为

- 支持“把《A》设为 @主标书”。
- 支持“把当前文件设为 @主标书”。
- 支持“围绕 @主标书 回答”。
- 支持“对比 @主标书 和 @交付标准”。
- 支持“@主标书 是哪份文件？”一类 alias 查询，trace 可显示其绑定文件。
- alias 命中后按 resolved `document_id` scoped retrieval，不沿用旧 active document。
- alias missing 时标记 `alias_missing` 并抑制本轮 retrieval，不回退旧 active document 假装命中。
- rebind alias 时标记 `alias_conflict`，允许显式改绑但必须可诊断。
- “把当前文件设为 @alias” 若 active document 不存在，会先允许本轮 retrieval；若本轮 retrieval 唯一命中文档，则在会话层完成 alias binding。
- alias binding 是 Hermes 会话层状态解析，不依赖模型工具；context block 会显式注入 alias 处理状态。

## 真实终端验收结论

- Phase 2.11b 真实终端验收已通过。
- `@主标书` 绑定成功：`document_id=869d4684-0a98-4825-bc72-ada65c15cfc9`，session scope alias bound。
- `@主标书` 使用成功：alias 解析到 `869d4684-0a98-4825-bc72-ada65c15cfc9`，retrieval evidence 仅包含该文档，`contamination_flags=none`。
- `@交付标准` 绑定成功：`document_id=46372530-ea3d-4442-bd67-23efeb0b70df`，retrieval evidence 仅包含该文档。
- 双 alias 对比成功：`compare_document_ids` 与 `retrieval_evidence_document_ids` 同时包含 `@主标书` 与 `@交付标准` 两份文件，无第三份文件混入，`contamination_flags=none`。
- missing alias 成功抑制 retrieval：`alias_missing=true`、`suppress_retrieval=true`、`retrieval_evidence_document_ids=[]`。
- `@主标书` 已成功解析但工程地点 / 建设单位 / 代建单位未被召回，归类为大型标书基础信息召回质量尾项，不阻塞 Phase 2.11b 收口。

## 失效与冲突诊断

- alias 未找到：`alias_missing`
- alias 重名：`alias_conflict`
- alias 指向文档不存在：`alias_document_missing`
- alias 指向旧版本：`alias_stale_version`
- alias 解析成功但 retrieval 无 evidence：`alias_scope_no_current_evidence`
- compare alias 只解析出一侧：`alias_compare_partial_resolution`

上述状态必须进入 trace，不允许静默回退到旧 active document 或 history memory。

## Trace 字段

- `file_alias_used`
- `file_alias`
- `file_alias_scope`
- `alias_resolution_status`
- `alias_document_id`
- `alias_document_title`
- `alias_version_id`
- `compare_aliases`
- `compare_document_ids`
- `alias_conflict`
- `alias_stale_version`
- `suppress_retrieval`
- `scope_retrieval_suppressed`

## 验收样本

1. 把大标书设为 `@主标书` 后，围绕 `@主标书` 回答应命中该 `document_id`。
2. 把附件十一设为 `@交付标准` 后，围绕 `@交付标准` 回答应命中该 `document_id`。
3. 同一 session 内从 `@主标书` 切到 `@交付标准`，不得沿用旧 active document。
4. 对比 `@主标书` 和 `@交付标准`，本轮 evidence 必须同时包含两份文件。
5. 对比模式不得混入第三份文件。
6. alias 不存在时必须 trace `alias_missing`，不得默认使用旧 active document。
7. alias 指向旧版本时必须 trace `alias_stale_version`。

## 非目标

- 不实现 Excel/PPTX parser。
- 不实现 OCR / ASR。
- 不实现完整项目知识库管理。
- 不做权限体系大改。
- 不改 retrieval contract。
- 不改 memory kernel 主架构。

## 测试

- `tests/agent/test_session_document_scope.py`
  - bind title to alias
  - bind current active document to alias
  - bind after same-turn retrieval
  - use alias for retrieval
  - compare two aliases
  - missing alias 不回退 active document，并抑制本轮 retrieval
  - rebind alias 可诊断
  - alias scope 强制 enterprise retrieval，即使 query 本身缺少普通 router hint

## 收口判断

- Phase 2.11b 最小实现已完成。
- 真实终端验收已通过。
- 当前能力解决“长文件名反复引用困难”的 session-level alias 问题。
- 当前仍不代表 project-level alias、完整项目知识库管理或多模态能力完成。
