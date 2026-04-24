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
