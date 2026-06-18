---

description: "Task list for Multi-Provider LLM Configuration"
---

# Tasks: Multi-Provider LLM Configuration

**Input**: Design documents from `specs/014-multi-provider-llm/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Verify environment and create new package skeleton

- [X] T001 Verify `openai` SDK is available (`pip show openai`); add to `kb/requirements.txt` if missing
- [X] T002 Create `kb/holmes/kb/agent/provider/` package directory with empty `__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core abstractions that ALL user stories depend on — config field + provider interface

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Add `provider: str = "anthropic"` field to `HolmesConfig` in `kb/holmes/config.py` with backward-compatible `from_dict` default
- [X] T004 Define `ToolCall` dataclass and `LLMProvider` ABC (methods: `complete`, `simple_complete`, `append_tool_results`) in `kb/holmes/kb/agent/provider/base.py`
- [X] T005 Create stub `factory.py` in `kb/holmes/kb/agent/provider/factory.py` that raises `NotImplementedError` (to be filled per US)
- [X] T006 Export `LLMProvider`, `ToolCall`, `create_provider` from `kb/holmes/kb/agent/provider/__init__.py`

**Checkpoint**: Foundation ready — provider interface exists, config carries `provider` field

---

## Phase 3: User Story 1 — Configure Anthropic Provider (Priority: P1) 🎯 MVP

**Goal**: Existing Anthropic users continue to work with zero config changes; runner uses provider interface instead of bare SDK.

**Independent Test**: Mock `AnthropicProvider.complete` → run `holmes import` → import completes and produces KB entry via Anthropic path.

### Implementation for User Story 1

- [X] T007 [US1] Implement `AnthropicProvider` (wraps `anthropic.Anthropic`; `complete`, `simple_complete`, `append_tool_results`) in `kb/holmes/kb/agent/provider/anthropic_provider.py`
- [X] T008 [US1] Update `factory.py` to return `AnthropicProvider(cfg)` when `cfg.provider == "anthropic"` in `kb/holmes/kb/agent/provider/factory.py`
- [X] T009 [US1] Refactor `ImportAgentRunner.__init__` in `kb/holmes/kb/agent/runner.py` to replace `anthropic.Anthropic(...)` with `create_provider(cfg)`, store as `self._provider`
- [X] T010 [US1] Refactor tool-use loop in `ImportAgentRunner.run` in `kb/holmes/kb/agent/runner.py` to use `self._provider.complete()` and `self._provider.append_tool_results()`
- [X] T011 [US1] Pass `provider=self._provider` in the `ctx` dict inside `ImportAgentRunner.run` in `kb/holmes/kb/agent/runner.py` (replacing `client` key)
- [X] T012 [P] [US1] Update `compare_root_cause` in `kb/holmes/kb/agent/tools.py` to use `provider.simple_complete()` instead of `client.messages.create`
- [X] T013 [P] [US1] Update `verify_content` in `kb/holmes/kb/agent/tools.py` to use `provider.simple_complete()` instead of `client.messages.create`
- [X] T014 [US1] Add integration test `test_import_with_anthropic_provider` in `kb/tests/test_integration.py` mocking `AnthropicProvider.complete` — verifies import completes via Anthropic path
- [X] T015 [US1] Add test `test_backward_compat_no_provider_field` in `kb/tests/test_integration.py` — config without `provider` key defaults to `anthropic`

**Checkpoint**: US1 complete — Anthropic import path works end-to-end; all existing tests pass

---

## Phase 4: User Story 2 — Configure OpenAI-Compatible Provider (Priority: P1)

**Goal**: Users with OpenAI, Azure, or Ollama endpoints can run `holmes import` through the same pipeline.

**Independent Test**: Mock `OpenAIProvider.complete` → run `holmes import` → import completes and produces KB entry via OpenAI path.

### Implementation for User Story 2

- [X] T016 [US2] Implement `OpenAIProvider` (wraps `openai.OpenAI`; converts Anthropic tool-def format to OpenAI format internally; implements `complete`, `simple_complete`, `append_tool_results`) in `kb/holmes/kb/agent/provider/openai_provider.py`
- [X] T017 [US2] Update `factory.py` to return `OpenAIProvider(cfg)` when `cfg.provider == "openai"`, raise `ValueError` for unknown values in `kb/holmes/kb/agent/provider/factory.py`
- [X] T018 [US2] Add integration test `test_import_with_openai_provider` in `kb/tests/test_integration.py` mocking `OpenAIProvider.complete` — verifies import completes via OpenAI path
- [X] T019 [US2] Add unit test `test_openai_tool_def_conversion` in `kb/tests/test_integration.py` — verifies Anthropic `input_schema` format is correctly converted to OpenAI `parameters` format

**Checkpoint**: US2 complete — OpenAI path works end-to-end; both provider paths tested

---

## Phase 5: User Story 3 — Switch Between Providers (Priority: P2)

**Goal**: Users can switch providers by running `holmes setup --provider <value>`; next import uses new provider.

**Independent Test**: Run `holmes setup --provider anthropic`, verify config; run `holmes setup --provider openai`, verify config updated.

### Implementation for User Story 3

- [X] T020 [US3] Add `--provider [anthropic|openai]` option (default `anthropic`) to `setup_cmd` in `kb/holmes/cli.py`, persist to `HolmesConfig`
- [X] T021 [US3] Add test `test_setup_saves_provider_field` in `kb/tests/test_integration.py` — `holmes setup --provider openai` writes `"provider": "openai"` to config.json
- [X] T022 [US3] Add test `test_setup_switches_provider` in `kb/tests/test_integration.py` — setup anthropic then openai; second config has `provider=openai`

**Checkpoint**: US3 complete — provider switching works; config persists correctly

---

## Phase 6: User Story 4 — Provider-Specific Error Guidance (Priority: P2)

**Goal**: All auth/connectivity error messages include the configured provider name so users can diagnose without documentation.

**Independent Test**: Configure with wrong key for each provider; run `holmes import`; verify error output contains provider name.

### Implementation for User Story 4

- [X] T023 [US4] Update auth/config error messages in `import_cmd` in `kb/holmes/cli.py` to include `cfg.provider` dynamically (e.g., `"provider: anthropic"` or `"provider: openai"`)
- [X] T024 [US4] Update dry-run hint message in `import_cmd` in `kb/holmes/cli.py` to reference `--provider` flag
- [X] T025 [P] [US4] Add test `test_error_message_includes_provider_anthropic` in `kb/tests/test_integration.py` — no api_key + `provider=anthropic` → error contains "anthropic"
- [X] T026 [P] [US4] Add test `test_error_message_includes_provider_openai` in `kb/tests/test_integration.py` — no api_key + `provider=openai` → error contains "openai"

**Checkpoint**: US4 complete — all error messages are provider-aware

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, integration validation, final cleanup

- [X] T027 [P] Update `docs/user-guide.md` — add `--provider` option to setup section, update LLM configuration instructions
- [X] T028 [P] Update `docs/quickstart.md` — add provider configuration step to quickstart flow
- [X] T029 Run `pytest kb/tests/` to confirm all tests pass (including all 447+ existing tests)
- [X] T030 Run quickstart.md scenarios 1–6 manually (or via mock) to validate end-to-end flows documented in `specs/014-multi-provider-llm/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — start after foundational
- **US2 (Phase 4)**: Depends on Phase 3 (runner refactor must be complete before OpenAI provider is wired in)
- **US3 (Phase 5)**: Depends on Phase 2 — independent of US1/US2 (only touches cli.py + config)
- **US4 (Phase 6)**: Depends on Phase 5 (needs `--provider` option to exist for test fixtures)
- **Polish (Phase 7)**: Depends on all story phases complete

### User Story Dependencies

- **US1 (P1)**: Requires Foundational (Phase 2) — implements Anthropic provider and runner refactor
- **US2 (P1)**: Requires US1 (Phase 3) — runner must use provider interface before OpenAI can be plugged in
- **US3 (P2)**: Requires Foundational (Phase 2) — touches only cli.py and config; independent of US1/US2 implementation
- **US4 (P2)**: Requires US3 (Phase 5) — error messages need `--provider` flag and `cfg.provider` to exist

### Within Each Phase

- T012 and T013 (tools.py updates) can run in parallel as they touch different functions
- T025 and T026 (error message tests) can run in parallel as they test independent scenarios

### Parallel Opportunities

```bash
# Phase 3 parallel tasks (different functions, same file):
T012: Update compare_root_cause in tools.py
T013: Update verify_content in tools.py

# Phase 6 parallel tests:
T025: test_error_message_includes_provider_anthropic
T026: test_error_message_includes_provider_openai

# Phase 7 parallel docs:
T027: docs/user-guide.md
T028: docs/quickstart.md
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T006)
3. Complete Phase 3: US1 Anthropic Provider (T007–T015)
4. **STOP and VALIDATE**: Run `pytest kb/tests/` — all existing tests must pass
5. Anthropic users have zero-regression experience; provider abstraction is in place

### Incremental Delivery

1. Setup + Foundational → provider interface exists
2. US1 → Anthropic path works through abstraction (zero regression)
3. US2 → OpenAI path added (new users unblocked)
4. US3 → Provider switching via `holmes setup --provider`
5. US4 → Provider-aware error messages
6. Polish → Docs and final validation

---

## Notes

- T003 (`config.py`) is the single most critical task — all provider logic flows from `cfg.provider`
- T009–T010 (`runner.py` refactor) must be done atomically — do not leave the runner in a half-migrated state
- T012 and T013 (`tools.py`) change `ctx["client"]` → `ctx["provider"]`; update all references consistently
- Existing tests use `patch("holmes.kb.agent.runner.ImportAgentRunner.run", ...)` — these do not need updating
- Tests that mock the old `anthropic.Anthropic` client will need updating to mock at the provider level
