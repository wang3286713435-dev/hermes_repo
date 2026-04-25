# DEV_LOG

- [Phase 2.10] 新增会话文件作用域最小实现，支持同一 Hermes 会话内文件切换与 evidence 防污染。
- [Phase 2.10] 修复 A/B 对比只召回单文件的问题，compare mode 改为双 scoped retrieval 合并。
- [Phase 2.10] 真实终端 A->B->A->A/B 对比验收通过，同会话切换不再依赖新开会话。
- [Phase 2.11a] 增强上下文治理 trace 与污染诊断，明确历史会话记忆只能作提示，不能替代本轮 retrieval evidence。
- [Phase 2.11a] 修复 history_memory_as_evidence 语义，强制历史记忆不作为本轮 citation/evidence。
- [Phase 2.11a] 真实终端验收通过：A 锁定、刚才文件延续、A/B 对比均无历史记忆伪 evidence 或第三文件污染。
- [Phase 2.11b] 完成企业文件别名规划，明确 alias 绑定 document_id，session 级先行。
- [Phase 2.11b] 完成 session-level 文件别名最小实现，支持绑定、使用、对比与 missing/rebind 诊断，missing 时抑制本轮 retrieval。
- [Phase 2.11b] 修复真实终端 alias 绑定未打通问题，绑定改为会话层状态并注入 context。
- [Phase 2.11b] 真实终端验收通过：双 alias 对比无第三文件污染，missing alias 可抑制 retrieval。
- [Phase 2.11c] 完成大标书基础信息召回规划，建议先做 metadata snapshot 再配合章节 boost。
- [Phase 2.11c] 同步 Hermes_memory 最小实现状态，基础信息 snapshot trace 已可供 Hermes 侧真实终端验收。
- [Phase 2.11c] 修复终端 trace 语义，metadata snapshot 可用于导航，但 snapshot_as_answer 强制保持 false。
- [Phase 2.11c] 真实终端复验通过，@主标书基础信息召回命中目标大标书且无 snapshot evidence 误标。
- [Phase 2.11d] 完成上下文治理综合回归规划，设计 15 条终端验收 prompt，用于验证 2.11a/b/c 组合防污染。
- [Phase 2.11d] 完成新增真实文件入库与 15 条综合回归执行，alias、compare、snapshot、missing alias 防污染均通过。
