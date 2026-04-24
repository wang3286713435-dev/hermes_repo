# DEV_LOG

- [Phase 2.10] 新增会话文件作用域最小实现，支持同一 Hermes 会话内文件切换与 evidence 防污染。
- [Phase 2.10] 修复 A/B 对比只召回单文件的问题，compare mode 改为双 scoped retrieval 合并。
- [Phase 2.10] 真实终端 A->B->A->A/B 对比验收通过，同会话切换不再依赖新开会话。
