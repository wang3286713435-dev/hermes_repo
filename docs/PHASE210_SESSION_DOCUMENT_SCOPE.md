# Phase 2.10 Enterprise Session Document Scope

## 目标

在同一 Hermes 会话内维护企业文件作用域，避免用户切换文件时必须新开会话。

## 最小实现

- Hermes 主仓库新增 `SessionDocumentScopeStore`，按 `session_id` 维护 `active_document_id`、`active_document_title`、`scope_source`、`updated_at`。
- Hermes_memory retrieval 继续保持 stateless，不新增服务端会话状态。
- 检索优先级为：显式 `document_id` > 明确文件切换/标题点名 > active document > 普通检索。
- `run_agent.py` 在构造 `KernelRequest` 前完成文件作用域解析，并把解析后的 `document_id` filter 与 trace 注入 memory kernel。
- `MemoryKernel` 在 context 注入前按允许的 `document_id` 二次过滤 evidence，避免旧文件污染。

## 文件切换语义

- `围绕 A 文件` / `切到 B 文件` / `切回 A 文件`：解析标题，更新 active document，并注入 `document_id`。
- `刚才那份文件` / `当前文件`：沿用当前 session 的 active document。
- `对比 A 和 B` / `比较 A/B` / `A 与 B 的区别`：进入 multi-document mode，不更新单一 active document；Hermes 主仓库对 A/B 分别发起 scoped retrieval 后合并 evidence。
- 标题解析失败时，如果用户没有明确说 `刚才/当前`，不默认沿用旧 active document，并在 trace 写入 `scope_resolution_failed`。

## Trace 字段

- `active_document_id`
- `active_document_title`
- `document_scope_source`
- `document_scope_changed`
- `scope_resolution_status`
- `cross_document_allowed`
- `allowed_document_ids`
- `compare_document_ids`
- `returned_document_ids`
- `active_document_bypassed`
- `active_document_id_bypassed`
- `document_scope_filter`

## 验收覆盖

- 同一 `session_id` 内 A -> B -> A 文件切换。
- `刚才那份文件` 沿用 B。
- 标题解析失败不误用旧 active document。
- 对比 A/B 允许两份文件，禁止第三份文件 evidence 混入。
- 对比 A/B 必须真实返回两份文件的本轮 retrieval evidence，不能依赖历史会话记忆补齐第二份文件。
- trace 字段完整。

## 真实终端验收结论

- Phase 2.10 最小实现已完成。
- 真实 Hermes 终端中 A -> B -> A -> A/B 对比验收通过。
- A 文件锁定通过：`1db84714-d49f-48a2-8fa9-c6f73424dd32`。
- B 文件切换通过：`46372530-ea3d-4442-bd67-23efeb0b70df`。
- A/B 对比时本轮 citations/evidence 同时包含两份文件，无第三份文件混入。
- 同一 Hermes 会话内文件切换不再依赖新开会话。
- 当前仍是最小实现，不代表完整企业上下文系统全部完成。

## 非目标

- 不改 retrieval contract。
- 不改 memory kernel 主架构。
- 不做 facts、权限大改、dense ingestion、完整 AI 审标自动化。
