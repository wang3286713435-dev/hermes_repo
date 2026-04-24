# DEV_LOG

- [Phase 2.10] 新增会话文件作用域最小实现，支持同一 Hermes 会话内文件切换与 evidence 防污染。
- [Phase 2.10] 修复 A/B 对比只召回单文件的问题，compare mode 改为双 scoped retrieval 合并。
- [Phase 2.10] 真实终端 A->B->A->A/B 对比验收通过，同会话切换不再依赖新开会话。
- [Phase 2.11a] 增强上下文治理 trace 与污染诊断，明确历史会话记忆只能作提示，不能替代本轮 retrieval evidence。
- [Phase 2.11a] 修复 history_memory_as_evidence 语义，强制历史记忆不作为本轮 citation/evidence。
- [Phase 2.11a] 真实终端验收通过：A 锁定、刚才文件延续、A/B 对比均无历史记忆伪 evidence 或第三文件污染。
