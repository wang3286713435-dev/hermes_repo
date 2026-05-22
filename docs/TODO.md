# TODO

## Phase 2.112d

- 已完成 alias continuity owner-scope review fix：natural import continuity 不再按 alias 全局恢复，而是按 safe owner key + alias 恢复。
- Stable owner value 仅哈希化保存；diagnostics 只暴露 `alias_continuity_owner_source` / persistent 标记，不输出 raw owner。
- 无 stable owner 时仅使用 process-local non-persistent fallback；新 store load 不恢复 unscoped fallback alias。
- 已补 TTL/stale cleanup、cross-owner denial、conflict fail-closed / suppress retrieval。
- 验证通过：py_compile；natural import / upload client / session scope regression `105 passed`；gateway latest-user drift targeted test `1 passed`。
- 待办：Codex B review；通过后再 selective runtime test-candidate baseline，并交测试机 OpenWebUI / 8642 复验。

## Phase 2.112

- 已完成 natural import upload-success -> session alias / active document / same-session scoped retrieval 最小修复。
- 成功导入后会把 seeded alias 持久化为 session file alias，并将 diagnostics 更新为 `alias_bound`；后续 `@alias` query 会带 `document_id/version_id` scoped filters。
- Phase 2.112b 已补真实 OpenWebUI / 8642 pause 对应的 alias blocker：当兼容接口 session key 漂移时，会从上一轮 natural import diagnostics 恢复 session alias；已存在导入 alias 的 title rebind 不再因 title resolver miss 返回 `alias_bind_failed`。
- Phase 2.112c 已补 OpenWebUI 只发送最新 user message 的断链：成功 natural import 会写入 bounded alias-continuity registry，follow-up api session drift 也能恢复 `@alias -> document_id/version_id` scoped retrieval。
- 冲突 alias-continuity 候选会 fail-closed 并 suppress retrieval；diagnostics 输出 `alias_continuity_status/source`、`api_session_key_source`、`history_message_count`，且不把 import diagnostics 当 retrieval evidence。
- 未提供 alias 时会生成安全 alias，并在成功响应中提示用户可继续用 `@alias` 查询。
- 已补 session alias bounded discovery；模糊找文件请求只返回 session alias 候选并 suppress ordinary retrieval，避免误检索旧文件。
- 主仓 targeted regression：py_compile 通过，natural import / upload client / session scope tests `102 passed`，gateway latest-user drift test `1 passed`。
- 待办：Codex B review 后做 selective test-candidate baseline，再交测试机 Codex 跑真实 OpenWebUI / 8642 natural import -> `@alias` retrieval / citation 验收；本轮未执行真实 upload。

## Phase 2.56d

- 已完成 natural import runtime wiring 最小实现。
- `run_agent.py` 现在会在普通 memory kernel retrieval / LLM answer 前调用 natural import runtime hook。
- 非导入 prompt 不被拦截；明确导入 prompt 默认 `real_upload_enabled=false`，fail-closed 返回 diagnostics，不进入普通 retrieval 乱答。
- fake adapter success / failure / missing id 路径已覆盖；diagnostics 不作为 retrieval evidence，safety flags 保持 false / required。
- 本轮未调用真实 Hermes_memory upload API、未上传真实文件、未写 DB / OpenSearch / Qdrant。

## Phase 2.56a

- 已完成 natural import real adapter skeleton。
- 新增 feature-flagged upload adapter，默认 `enabled=false`。
- `run_natural_file_import_preflight()` 默认 `real_upload_enabled=false`；有效导入请求未显式启用时返回 `real_upload_disabled`，不会调用 adapter。
- fake adapter success 需显式 `real_upload_enabled=True`，可返回 `document_id/version_id` 并 seed session alias。
- import diagnostics 仍不是 retrieval evidence；本轮未调用真实 Hermes_memory upload API、未上传文件、未运行 API / CLI smoke。

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

## Phase 2.14

- 已进入企业记忆回归评测规划：主评测建议放在 Hermes_memory API-level deterministic eval，Hermes 主仓库只补少量 CLI black-box smoke。
- CLI smoke 重点覆盖 session scope、alias、A/B compare、structured citation 展示、meeting transcript 非 fact 语义。
- Phase 2.14b CLI smoke 已收口：修复非交互 `chat -q --resume` 新进程无法恢复 alias/scope 的问题，将 session document scope / file alias 最小持久化到 Hermes state 文件。
- Phase 2.14b live runner 已通过：`total=4, passed=4, failed=0, skipped=0`，覆盖 missing alias suppress、alias bind/use `@主标书`、`@会议纪要` vs `@主标书` compare、`transcript_as_fact=false`。
- Phase 2.20a 已扩展 CLI smoke：新增 `alias_stale_version_warning`，通过 session state bootstrap 绑定旧 version；live runner `5 passed / 0 failed / 0 skipped`。
- Phase 2.20a 已完成收口验证：Hermes_memory governance eval `5/5`、CLI smoke `5/5`、full Phase 2.14 eval `16 passed / 0 failed / 1 skipped`；dense 假失败根因为本机 `.env` 指向旧 Qdrant collection。

## Phase 2.19b

- 已完成 alias stale version 联调边界规划；当前主仓库 alias 结构已有 `version_id` 字段并会持久化，但 active document state 不保存 `version_id`，部分“当前文件绑定”路径可能丢版本信息。
- 最小实现边界：alias 若绑定旧 `version_id`，应以显式历史版本检索，trace 输出 `alias_stale_version=true`、`latest_version_id`、`superseded_by_version_id`，并提示用户可切换 latest。
- compare mode 中任一 alias stale 时，需在 trace 中按 alias 侧可诊断；不得因为 stale 提示放松 A/B evidence 防污染规则。
- 非目标：不做复杂版本 diff、不做版本管理后台、不自动合并不同 `document_id` 历史文件、不做 facts、不进入 rollout。
- Phase 2.19b 最小实现已完成：active document / alias 均可保留 `version_id`，alias scoped retrieval 会显式带旧 `version_id`，并将 Hermes_memory `version_scope` 映射为 `alias_stale_version` 诊断。
- Live smoke 已通过：`@版本测试` 绑定 v1 后上传 v2，继续查询 alias 时返回 v1 evidence，同时输出 `alias_stale_version=true` 与 `latest_version_id=<v2>`。

## Phase 2.24a

- 已完成 confirmed facts 作为 Agent 辅助上下文的最小实现：仅显式 facts hint / scope 请求时注入，且必须存在本轮 retrieval evidence。
- trace 固定输出 `facts_context_used`、`facts_context_fact_ids`、`facts_as_answer=false`、`stale_fact_source_count`；context block 明确 facts 不能替代 citation。
- confirmed facts 查询通过 Hermes_memory `search_confirmed_facts`，继承 source document soft policy；deny 或无 confirmed facts 时不注入。
- live smoke 已覆盖：正向注入、stale source warning、无 retrieval evidence 时 suppress facts context。
- 已修复真实终端验收暴露的展示混淆：confirmed facts context 改为独立分区，不再与 meeting transcript metadata / retrieval evidence 混在 session scope 中。
- stale fact source 诊断已补强：`stale fact source` 类 query 可触发 confirmed facts stale 检查，并输出 `stale_fact_source_count` 与 `latest_version_id`。
- 无作用域 stale / fact-answer policy query 已抑制普通 retrieval，避免拉入无关文档；仍可输出 facts 诊断并保持 `facts_as_answer=false`。
- `facts_context_fact_ids` 只允许 fact_id list，不写入 `[E]` / `[C]` retrieval chunk 或 citation id。
- alias 绑定 / 普通 retrieval-only / meeting transcript retrieval 场景均会稳定输出 facts diagnostics：`facts_context_used=false`、`facts_context_fact_ids=[]`、`facts_as_answer=false`。
- Codex C 真实终端复验已通过：`@会议纪要` 预备绑定稳定输出 `false/[]/false`，5 条正式验收全部通过。
- 已检出 stale fact `9f98384b-5053-4a8f-9b83-35983b28b38e`，`stale_fact_source_count=1`，`latest_version_id=76ca95a1-393f-4278-b254-ab66295bb14f`。
- 复验未出现 E/C chunks 写入 `facts_context_fact_ids`、fact-only query 检索无关文档或 facts 替代 retrieval evidence；`facts_as_answer` 全场景为 false。
- 复验注意：`@会议纪要` 属于 session alias，Prompt 4 前必须先在当前会话绑定该 alias，避免新会话 `alias_missing`。
- 当前仍不让 facts 进入 Agent final answer，不做自动抽取、知识图谱、UI 或 rollout。

## Phase 2.30b

- 已修复 Practical MVP Pilot 中标题类 alias 绑定稳定性问题：`把《标题》设为 @alias` 在 title resolver 未命中时不再直接 suppress retrieval。
- 新增 `alias_bind_pending_title_retrieval`，同轮 retrieval 返回唯一目标文档后完成 alias 绑定并持久化 document_id / version_id。
- 绑定失败时返回 `no_title_retrieval_match` / `ambiguous_title_retrieval` 诊断，不复用旧 active document。
- missing alias suppress retrieval、compare 防第三文件污染、stale alias 诊断保持既有语义。
- 待 Codex C 复跑 12 条 Pilot query，重点覆盖 `@硬件清单`、`@会议纪要`、`@C塔方案` 与 `@会议纪要 vs @主标书`。
- 已补齐 Pilot runbook 原文 alias 绑定覆盖：无书名号 `把会议纪要文件设为 @会议纪要`、`把硬件清单设为 @硬件清单`、`把C塔方案设为 @C塔方案` 均可走 title retrieval fallback。
- `把当前主标书设为 @主标书` / `把当前标书设为 @主标书` 可按 current document binding 或 current retrieval fallback 处理，不误复用旧 alias 或无关文件。

## Phase 2.34

- 已完成 Day-1 Pilot Q8 compare false-positive 最小修复：当最终 `retrieval_evidence_document_ids` 均属于 `compare_document_ids` 时，trace 明确输出 `third_document_mixed=false`。
- `out_of_scope_document_ids_filtered` 仅记录候选过滤诊断，不再作为最终 `contamination_flags` 中的第三文件污染标记。
- 若最终 evidence 中仍出现 compare scope 外的 document_id，继续输出 `third_document_mixed=true` 与 `unexpected_document_id`，不压制真实污染。
- context block 已补 compare scope 提示，要求模型不要把主题差异、partial evidence 或已过滤候选误说成 third-document contamination。
- Codex C 真实终端复验已通过：`@会议纪要 vs @主标书` compare 输出 `third_document_mixed=false`、`third_document_mixed_document_ids=[]`、`contaminationflags=none`，无第三文件污染误报。
- Facts / transcript 抽样保持 `facts_context_used=false`、`facts_context_fact_ids=[]`、`facts_as_answer=false`、`transcript_as_fact=false`。
- Day-1 P1 backlog 仍保留：`@主标书` 最高投标限价 Missing Evidence，资质 / 经理 / 联合体 / 业绩 / 人员等深层字段需人工复核。
- Day-1 P2 backlog 仍保留：会议纪要决策 / 公司方向分析长输出延迟，本轮不做 latency 优化。

## Phase 2.35c

- 修复真实终端复验暴露的 alias/session 阻断：`请把上一轮已锁定的当前文件设为 @主标书` 现在会被识别为 current-document binding。
- 若当前 session 已有 active document，则直接绑定 active document；若没有 active document，则通过同轮唯一 retrieval evidence 完成 alias bind 并持久化。
- 新增 direct assertion tests 覆盖跨 `SessionDocumentScopeStore` 实例 resume、run_agent pre-resolved scope、missing alias suppress 与 compare 相邻路径。
- 主仓库 session scope 回归已用 `.venv/bin/python -m pytest -o addopts='' tests/agent/test_session_document_scope.py -q` 复跑通过：`48 passed`。
- Codex C 真实终端复验已通过：正式 Q1/Q2 均为 `alias_resolved`，`alias_missing=false`，`retrieval_suppressed=false`。
- 当前可进入 Phase 2.35c baseline，但 baseline 只能声明 alias/session 修复收口，不能声明 deep-field recall 完全收口。

## Phase 2.36b

- 已完成 deep-field trace display 映射最小修复：HermesMemoryAdapter / MemoryKernel 会将 Hermes_memory `metadata_deep_field_profile`、`deep_field_profile`、`deep_field_section_hints`、`deep_field_query_aliases`、`deep_field_missing_reason`、`deep_field_diagnostics` 从 retrieval trace 提升到主仓顶层 trace。
- ContextBuilder 已新增 deep-field diagnostics 渲染行，明确 diagnostics 只是 routing / Missing Evidence 诊断，不替代 retrieval evidence。
- 已补一步 alias bind prompt：`锁定“标题”，并绑定为 @alias` 支持中文弯引号与 `绑定为 / 绑定成`。
- 目标测试通过：py_compile 通过，`tests/agent/test_session_document_scope.py tests/agent/test_structured_citation_context.py` 为 `59 passed`。
- 下一步需 Codex B review；若通过，交 Codex C 复验 Step 1 / Q1 / Q2 终端 trace 透出。

## Phase 2.38d

- Hermes_memory retrieval intent / metadata 已将人员要求 query 收敛到 `personnel_scope`，但 Codex C 复验显示最终回答仍会把项目经理 / 建造师或推断人数混入人员要求回答。
- 本轮主仓库只补 context-level answer boundary：`personnel_scope` 时明确不得把项目经理 / 项目负责人 / 注册建造师 / 一级建造师 / B证 / 安全考核证 / 投标资质 / 联合体 / 类似工程业绩作为 personnel-only 答案，且不得从角色列表推断“每个项目只能1个 / 每类1人 / 至少各1名”。
- 第二轮最小修复已把 guard 强化为 `STRICT PERSONNEL-ONLY FINAL ANSWER GUARD`，并明确 mixed citation chunk 中也只能抽取人员部分。
- 第三轮最小修复已补结构化 guard lines：`personnel_forbidden_answer_terms`、`personnel_count_inference_forbidden=true`、`ignore_non_personnel_content_in_mixed_chunks=true`，降低模型忽略自然语言 guard 的概率。
- 第四轮最小修复已补 personnel-only safe fallback 契约：若草稿包含 forbidden terms 或隐式数量推断，应丢弃草稿并只输出 Missing Evidence / 人工复核模板。
- 第五轮最小修复已接入 runtime post-answer guard：`run_agent.py` 在最终响应持久化 / 返回前调用 `MemoryKernel.apply_personnel_answer_guard()`，违规 personnel-only 输出会被替换为 Missing Evidence / 人工复核 fallback。
- Codex C 真实终端复验已通过：Q1/Q2 personnel-only safe fallback 触发且无禁词 / 数量推断；Q3 broad qualification 未被压扁。
- 当前未改 retrieval contract、未改 memory kernel 主架构、未写 DB、未进入 rollout；本轮执行 Phase 2.38d Git baseline。
- 主仓目标测试已通过：py_compile 通过，`tests/agent/test_structured_citation_context.py tests/agent/test_session_document_scope.py` 为 `65 passed`。

## Phase 2.43d

- Day-1 Pilot 暂停点：`@主标书` 绑定阶段出现 `alias_bind_failed`，正式 Q1 变成 `alias_missing=true / retrieval_suppressed=true`；`@硬件清单`、`@C塔方案`、`@会议纪要` 在 Day-1 中稳定。
- 本轮最小修复已完成：pending current alias bind 在 retrieval 返回多个候选时采用 top document 完成绑定，并记录 `alias_bind_ambiguous_retrieval_document_ids`；title bind 多候选仍保持失败。
- `finalize_pending_alias_binding()` 现在返回 scoped filters 时保留 `version_id`，保证 resume 后 `@主标书` query 继续按 document_id/version_id 检索。
- 主仓目标测试通过：`./.venv/bin/python -m py_compile ...` 通过，`./.venv/bin/python -m pytest -o addopts='' tests/agent/test_session_document_scope.py -q` 为 `51 passed`。
- 下一步需要 Codex B review 与 Codex C Day-1 Q1 alias/session 复验；当前不 baseline、不 tag、不 push。
# TODO 最新状态

- 当前 phase：Phase 2.112f Alias Continuity Restore Fix 已实现，待 Codex B review 与测试机 OpenWebUI / 8642 复验。
- 修复：owner-scoped alias continuity restore 的 follow-up 诊断已稳定写入顶层 trace 与 `alias_resolution`；持久化 continuity 跨 store / 新 agent instance 恢复已补测试。
- 验证：py_compile 通过；session/natural import regression `77 passed`；gateway targeted stable-owner tests `3 passed`。
- 边界：未重复真实导入，未写 DB / facts / versions / OpenSearch / Qdrant，未执行 repair/backfill/reindex，未改 retrieval contract / memory kernel 主架构。
- 下一步：Codex B review；通过后再由测试机复验 OpenWebUI / 8642 import -> follow-up `@alias` retrieval + citation。

# Phase 2.56e Natural Import Real Upload Client

1. Real Hermes_memory upload client 已接入 `run_agent.py` 的 natural import runtime path。
2. Feature flag：`HERMES_NATURAL_IMPORT_REAL_UPLOAD_ENABLED=true` 时调用 `/api/v1/documents/upload`。
3. 用户授权 `.docx` real smoke 成功：`document_id=ee54b72c-b88b-4fad-be54-007240285356`，`version_id=950da5fe-dd7c-4eba-8764-916b556d14ce`。
4. 同 session alias `@C塔人力测算` retrieval smoke 只返回新导入文档 evidence。
5. 下一步等待 Codex B review；不得自动 cleanup/delete/repair/backfill/reindex 或 rollout。

# Phase 2.112e API Server Stable Owner Bridge Fix

1. API server 已从 accepted `X-Hermes-Session-Id` / whitelisted OpenWebUI conversation headers 生成 `gateway_session_key` 并传入 `AIAgent`。
2. Whitelisted headers：`X-OpenWebUI-Conversation-Id`、`X-OpenWebUI-Chat-Id`、`X-Conversation-Id`。
3. 无 stable owner 时仍 fail-closed，并在 alias-missing trace 输出 sanitized `stable_owner_missing`；不暴露 raw owner / token / path / secret / content。
4. 验证通过：py_compile；API server owner bridge targeted tests `7 passed`；natural import / upload client / session scope regression `106 passed`。
5. 下一步等待 Codex B review；通过后再做 selective runtime baseline 与测试机 OpenWebUI / 8642 验证。

# Phase 2.112g Header-only Stable Owner Restore Fix

1. 已修复 OpenWebUI / 8642 follow-up 只有 header-only `X-Hermes-Session-Id` 时 stable owner 缺失的问题。
2. `X-Hermes-Session-Id` 已加入 gateway stable owner fallback headers；accepted body/session id 与 header-only follow-up 会生成同一 safe owner。
3. 新增测试覆盖 header-only owner extraction、accepted/header-only owner equivalence、import alias continuity restore 后 `alias_resolved` / scoped filters / no `stable_owner_missing`。
4. 验证：py_compile 通过；新增 targeted gateway tests `3 passed`；natural import / upload client / session scope regression `109 passed`。
5. 本地完整 `tests/gateway/test_api_server.py` 仍因当前 `.venv` 缺 async pytest 插件 false-fail existing async tests；需 Codex B 在具备 async 插件环境复核。
6. 下一步：Codex B review；通过后再由测试机 OpenWebUI / 8642 复验 import -> follow-up `@alias` retrieval + citation。
