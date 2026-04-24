# Phase 2.11c Tender Metadata Retrieval Plan

## 目标

解决大型标书中“文件作用域正确，但基础信息章节召回不准”的质量尾项。

已知问题：`@主标书` 可正确解析到目标 `document_id`，但询问工程地点、建设单位、代建单位时，retrieval 可能落到工程量清单章节，未命中招标公告或投标人须知前附表。

## 增强对象

- 工程名称
- 工程地点
- 招标人 / 建设单位
- 代建单位
- 最高投标限价
- 工期
- 项目编号 / 标段信息

## 路线评审

### A. Retrieval Query Profile / Section Boost

做法：

- 为基础信息类 query 识别 `tender_basic_info` profile。
- 对以下章节标题加权：
  - 招标公告
  - 投标人须知前附表
  - 工程概况
  - 项目概况
  - 招标范围
- 对工程量清单、技术规范等易误召回章节降权。

优点：

- 改动小，仍沿用当前 sparse/OpenSearch 检索。
- 可直接改善“章节没打准”问题。

风险：

- 对长标书标题层级依赖较强。
- 如果基础信息分散在多个章节，单纯 boost 仍可能不稳定。

### B. Document-level Metadata / Front-matter Snapshot

做法：

- 在 ingestion 或后处理阶段，为每份标书建立轻量 metadata snapshot。
- snapshot 字段只记录基础信息候选值、来源 chunk、来源章节。
- 查询基础信息时先使用 snapshot 定位候选章节，再执行 scoped retrieval 验证。

优点：

- 更适合大型标书的稳定导航。
- 可把“工程地点 / 建设单位 / 代建单位”等高频基础字段从正文海量 chunk 中提前定位。
- 对文件 alias / active document scope 兼容。

风险：

- 需要定义 snapshot 生成与更新时机。
- 抽取不应被误用为最终 evidence。

## 建议

优先做 B 的轻量 metadata snapshot，再配合 A 的 query profile / section boost。

原因：

- 当前问题不是文件作用域，而是基础信息字段在大型标书内被深层正文稀释。
- metadata snapshot 能先缩小章节导航范围。
- query boost 可作为 fallback 和精排辅助。

## 最小实现边界

- 建立 document-level `tender_metadata_snapshot`。
- 字段建议：
  - `document_id`
  - `version_id`
  - `field_name`
  - `field_value`
  - `confidence`
  - `source_chunk_ids`
  - `source_headings`
  - `updated_at`
- 支持字段：
  - `project_name`
  - `project_location`
  - `tenderer`
  - `construction_unit`
  - `agent_or_delegate_unit`
  - `price_ceiling`
  - `duration`
  - `project_number`
  - `bid_section`
- 查询时 snapshot 只用于定位候选章节和 chunk，不直接生成最终回答。
- 最终回答仍必须来自本轮 retrieval evidence。

## Trace 设计

- `metadata_snapshot_used`
- `metadata_fields_matched`
- `evidence_required=true`
- `source_chunk_ids`
- `metadata_snapshot_document_id`
- `metadata_snapshot_version_id`
- `metadata_snapshot_status`
- `metadata_guided_query_profile`

## 最小实现状态

- Hermes_memory 已完成轻量 `tender_metadata_snapshot` 最小实现。
- snapshot 当前只用于基础信息 query 的来源 chunk 导航与 boost，不直接作为回答 evidence。
- 真实大标书直接复测中，工程地点、建设单位、代建单位 query 均命中目标 `document_id`，top1 已锚定对应 source chunk，不再由工程量清单章节占首位。
- Hermes 主仓库当前不需要改 memory kernel 主架构，只需消费 retrieval trace 并进入真实终端验收。
- 终端 trace 语义已修正：`metadata_snapshot_used=true` 只表示使用 snapshot 导航，`snapshot_as_answer=false` 必须保持不变，最终回答仍必须来自本轮 retrieval evidence。

## 真实终端验收

- `@主标书` 绑定通过，目标 `document_id=869d4684-0a98-4825-bc72-ada65c15cfc9`。
- 基础信息召回通过：`metadata_snapshot_used=true`，工程地点 / 建设单位 / 代建单位均返回对应 `metadata_source_chunk_ids`。
- trace 语义通过：`evidence_required=true`、`snapshot_as_answer=false`、`retrieval_evidence_document_ids` 仅包含目标大标书，`contamination_flags=[]`。
- 建设单位单字段追问通过，答案为 `深圳市福升建设开发有限公司`，仍由 retrieval evidence 支撑。

## 验收样本

1. 围绕 `@主标书` 查询工程名称，应命中招标公告或前附表相关 chunk。
2. 围绕 `@主标书` 查询工程地点，应命中基础信息章节，不应落到工程量清单章节。
3. 围绕 `@主标书` 查询建设单位，应返回带 source chunk 的 evidence。
4. 围绕 `@主标书` 查询代建单位，应返回可引用 evidence；若无字段，应明确未检出。
5. 查询最高投标限价，应优先命中前附表 / 限价信息章节。
6. 查询工期，应能在前附表 / 工期要求中稳定命中。
7. 查询项目编号 / 标段信息，应命中招标公告或前附表。

## 非目标

- 不改 retrieval contract。
- 不改 memory kernel 主架构。
- 不把 metadata snapshot 当作最终 evidence。
- 不实现完整 facts 层。
- 不实现完整审标自动化。
- 不做权限体系大改。
- 不推进生产级 rollout。
