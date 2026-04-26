# Phase 2.19b Alias Stale Version Plan

## 1. Goal

Phase 2.19b focuses on Hermes session file alias integration with Hermes_memory version governance.

The goal is to make stale alias bindings diagnosable when an alias points to a superseded document version.

## 2. Current State

Current Hermes alias state already supports:

1. `FileAliasBinding.version_id`
2. persisted alias state in Hermes state file
3. alias trace fields such as `alias_version_id` and `alias_stale_version`
4. compare mode trace with `compare_aliases` and `compare_document_ids`

Current gaps:

1. `DocumentScopeState` stores active `document_id/title`, but not active `version_id`.
2. Binding by title or same-turn retrieval can preserve `version_id`.
3. Binding from an existing active document can lose `version_id`.
4. Hermes_memory retrieval already returns `version_scope.stale_version` and `latest_version_id`, but Hermes alias trace does not yet consistently surface them.

## 3. Minimum Integration Boundary

Phase 2.19b should only implement:

1. Preserve alias `version_id` when binding from title, retrieval evidence, or active document where available.
2. When alias has `version_id`, inject it as an explicit retrieval filter for alias-scoped retrieval.
3. Surface Hermes_memory `version_scope.stale_version`, `latest_version_id`, and `superseded_by_version_id` into Hermes alias trace.
4. If alias points to an old version, keep retrieval explicit to that old version but warn with `alias_stale_version=true`.
5. If user did not explicitly ask for the old version, answer should recommend switching alias to latest.
6. In compare mode, stale status must be visible per alias side.

## 4. Acceptance Design

Use a small v1/v2 test document:

1. Upload v1.
2. Bind `@版本测试` to v1.
3. Upload v2 as the latest version of the same document.
4. Ask with `@版本测试`.

Expected result:

1. Retrieval can still query v1 explicitly.
2. Trace includes `alias_stale_version=true`.
3. Trace includes `latest_version_id=<v2>`.
4. Evidence does not silently switch versions.
5. User-facing context indicates the alias points to an older version.

Compare acceptance:

1. Bind one alias to an old version and another alias to latest.
2. Compare both aliases.
3. Trace exposes stale status for the stale side without third-document contamination.

## 5. Non-goals

1. No retrieval contract change.
2. No memory kernel architecture rewrite.
3. No complex version diff.
4. No version management admin UI.
5. No automatic merge of historical documents with different `document_id`.
6. No facts implementation.
7. No rollout.

## 6. Recommended Next Step

Phase 2.19b minimum implementation is complete.

Hermes_memory should remain stateless and only provide existing version trace through retrieval responses.

## 7. Implementation Result

Implemented in Hermes main repository:

1. `DocumentScopeState` now preserves `active_document_version_id`.
2. Alias binding from title, current active document, or same-turn retrieval preserves `version_id`.
3. Alias scoped retrieval injects explicit `version_id` when the alias has one.
4. Hermes_memory `version_scope` is surfaced into Hermes alias trace.
5. Stale alias trace includes `alias_stale_version=true`, `latest_version_id`, and `superseded_by_version_id`.
6. Compare mode carries per-alias version filters and reports stale status for the affected side.
7. Context block now warns that stale alias points to a historical version and should switch to latest unless the user explicitly asked for history.

## 8. Validation

Targeted assertions:

1. Active document stores `version_id`.
2. Current document alias binding preserves `version_id`.
3. Stale alias maps `version_scope.stale_version` to alias trace.
4. Latest alias does not report stale.
5. Compare mode surfaces one-sided stale alias trace.

Live smoke:

1. Uploaded a small v1/v2 test document pair.
2. Bound `@版本测试` to v1.
3. Uploaded v2 as latest.
4. Querying `@版本测试` continued to retrieve v1 explicitly.
5. Trace showed `alias_stale_version=true`.
6. Trace showed `latest_version_id=<v2>`.
7. Context block included stale alias warning.
