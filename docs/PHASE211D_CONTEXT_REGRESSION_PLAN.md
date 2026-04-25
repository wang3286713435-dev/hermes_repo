# Phase 2.11d Context Regression Plan

## 目标

设计一套小型综合回归验收，用于验证 Phase 2.11a/b/c 组合后不会互相污染或覆盖。

覆盖能力：active document scope、session file alias、A/B compare、tender metadata snapshot、history memory 非 evidence、missing alias suppress retrieval、多大文件 / 多项目文件切换防污染。

## 非目标

- 不写功能代码。
- 不改 retrieval contract。
- 不改 memory kernel 主架构。
- 不做 Excel/PPTX parser、OCR/ASR、facts、权限大改或 rollout。

## 当前可用数据

- 大标书 A：`@主标书`，`document_id=869d4684-0a98-4825-bc72-ada65c15cfc9`。
- 数字化交付标准：`@交付标准`，`document_id=46372530-ea3d-4442-bd67-23efeb0b70df`。
- 答疑补遗文件：`document_id=1db84714-d49f-48a2-8fa9-c6f73424dd32`。

## 新数据需求

- 第二份大型标书：用于验证多大文件切换、同类标书 metadata snapshot 防串扰、A/B compare 双大文件 evidence。
- 一份企业制度 / 合同类文件：用于验证非 tender 文件不会误触 tender metadata snapshot，并验证跨项目/跨文件类型切换防污染。

## 验收 Prompt 与判定

### 现有文件即可执行

1. `把《福田区园岭街道兄弟高登高新产业园城市更新项目施工总承包工程招标文件_V1.0_招标文件》设为 @主标书`
   - 通过：`alias_resolution.status=alias_bound`，resolved document_id 为 `869d4684-0a98-4825-bc72-ada65c15cfc9`。
   - 失败：绑定到标题相近但不同文件，或只写入 title 未绑定 document_id。

2. `围绕 @主标书 回答工程地点、建设单位、代建单位`
   - 通过：`metadata_snapshot_used=true`，`snapshot_as_answer=false`，evidence document_ids 仅包含 `@主标书`。
   - 失败：落到工程量清单章节，或 snapshot 被标成 answer evidence。

3. `建设单位是谁？`
   - 通过：沿用 active document，返回 `深圳市福升建设开发有限公司`，history memory 不作为 evidence。
   - 失败：丢失 active document，或从历史记忆伪造 evidence。

4. `把《附件十一：数字化交付标准》设为 @交付标准`
   - 通过：alias 绑定 `46372530-ea3d-4442-bd67-23efeb0b70df`。
   - 失败：仍绑定到 `@主标书` 或旧答疑补遗文件。

5. `围绕 @交付标准 回答数字化交付要求`
   - 通过：evidence document_ids 仅包含 `46372530-ea3d-4442-bd67-23efeb0b70df`。
   - 失败：混入 `@主标书` 或答疑补遗文件。

6. `对比 @主标书 和 @交付标准 的 BIM / 数字化要求`
   - 通过：compare mode 同时返回两份文件 evidence，`cross_document_allowed=true`，无第三文件。
   - 失败：只返回一份文件，或用历史会话补另一份。

7. `围绕 @不存在 回答工程地点`
   - 通过：`alias_missing=true`，`suppress_retrieval=true`，retrieval evidence 为空。
   - 失败：回退 active document 或普通检索。

8. `切到《宝安新桥东重点城市更新项目答疑补遗文件（一）》回答答疑补遗内容`
   - 通过：active document 切到 `1db84714-d49f-48a2-8fa9-c6f73424dd32`。
   - 失败：仍沿用 `@主标书` 或 `@交付标准`。

9. `刚才那份文件里有什么补遗事项？`
   - 通过：沿用答疑补遗文件，evidence 仅来自 `1db84714-d49f-48a2-8fa9-c6f73424dd32`。
   - 失败：回到 `@主标书` 或使用历史记忆替代 retrieval。

10. `再围绕 @主标书 回答最高投标限价或工期`
    - 通过：alias 优先于当前 active document，回到 `869d4684-0a98-4825-bc72-ada65c15cfc9`。
    - 失败：被刚才 active document 污染。

### 需要新增第二份大型标书

11. `把《第二份大型标书标题》设为 @二号标书`
    - 通过：绑定新大标书 document_id，且不覆盖 `@主标书`。
    - 失败：alias 冲突不可诊断，或绑定到旧大标书。

12. `对比 @主标书 和 @二号标书 的工程地点、建设单位、工期`
    - 通过：两份大标书分别触发 metadata snapshot；evidence 只包含两份大标书。
    - 失败：metadata_source_chunk_ids 串到另一份文件，或第三文件混入。

13. `切换 @主标书 -> @二号标书 -> @主标书，分别追问建设单位`
    - 通过：三次 document_id 与答案均随 alias 切换。
    - 失败：后一次追问沿用上一份大标书。

### 需要新增企业制度 / 合同类文件

14. `把《企业制度或合同文件标题》设为 @制度文件，并回答适用范围`
    - 通过：不触发 tender metadata snapshot；evidence 仅来自制度/合同文件。
    - 失败：误用 tender snapshot 或混入标书文件。

15. `对比 @制度文件 和 @主标书 中关于违约责任的描述`
    - 通过：compare mode 只允许制度文件与主标书两组 evidence，history memory 不替代缺失 evidence。
    - 失败：第三文件混入，或缺一方 evidence 时仍强答。

## 回归输出字段

每条 prompt 至少记录：`alias_resolution.status`、`active_document_id`、`compare_document_ids`、`metadata_snapshot_used`、`metadata_fields_matched`、`metadata_source_chunk_ids`、`retrieval_evidence_document_ids`、`history_memory_as_evidence`、`suppress_retrieval`、`contamination_flags`。

## 收口标准

- 现有文件 10 条必须全部通过。
- 新增第二份大型标书后，11-13 必须通过才能认为多大文件切换已补证。
- 新增制度 / 合同文件后，14-15 必须通过才能认为跨文件类型防污染已补证。
- 任一场景出现 history memory 替代 retrieval evidence、missing alias 回退 active document、compare 第三文件混入，均判定回归失败。

## 执行结果

- 本轮新增文件已入库：
  - `@对比标书`：香港中文大学（深圳）医学院项目智能化工程Ⅰ标招标文件，`document_id=a47a409f-cb8a-4d29-b938-43c10767802d`，`chunk_count=613`。
  - `@交付标准新版`：3-1 数字化交付标准（V1.0版），`document_id=60d9601a-e797-47c9-a421-61dba6f88c7c`，`chunk_count=20`。
  - `@会议纪要`：会议纪要汇编 (2)，`document_id=92051cc6-56b5-4930-bdf0-119163c83a75`，`chunk_count=17`。
- 回归文件池已固定：
  - `@主标书`：`869d4684-0a98-4825-bc72-ada65c15cfc9`
  - `@对比标书`：`a47a409f-cb8a-4d29-b938-43c10767802d`
  - `@答疑文件`：`1db84714-d49f-48a2-8fa9-c6f73424dd32`
  - `@交付标准旧版`：`46372530-ea3d-4442-bd67-23efeb0b70df`
  - `@交付标准新版`：`60d9601a-e797-47c9-a421-61dba6f88c7c`
  - `@会议纪要`：`92051cc6-56b5-4930-bdf0-119163c83a75`
- 综合回归执行结果：15/15 通过。
- 已验证：两份大型标书互不污染、两份数字化交付标准互不污染、会议纪要不污染标书条款、missing alias 抑制 retrieval、history memory 不替代 evidence。
- 已验证：基础信息 metadata snapshot 使用时 `snapshot_as_answer=false`，最终 evidence 来自目标文档 chunk。
- 观察项：multi-document compare 顶层 trace 暂不聚合每份文档的 metadata snapshot 字段，但 `retrieval_evidence_document_ids`、`compare_document_ids` 与防污染结果通过。
