# Tasks: Import Pipeline Quality Normalization (018)

**Input**: Design documents from `specs/018-import-quality-normalizer/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks grouped by user story. Phase 2 (Foundational) blocks all user stories — schema constant must exist before Normalizer imports it. User stories US1–US8 can proceed in priority order after Phase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: Mapped user story (US1–US8)

---

## Phase 1: Setup

**Purpose**: Verify baseline before any changes.

- [X] T001 Run `python -m pytest -q` from `kb/` directory to confirm all 582 existing tests pass before any changes begin (regression baseline)

---

## Phase 2: Foundational — Category Constant Expansion

**Purpose**: Expand `VALID_PITFALL_CATEGORIES` in `schema.py` from 4 to 8 values. This is a blocking prerequisite: the Normalizer (US1) imports this constant, and all prompt updates (US2) reference its values.

**⚠️ CRITICAL**: US1 cannot implement category normalization until this task is done.

- [X] T002 In `kb/holmes/kb/schema.py`, expand `VALID_PITFALL_CATEGORIES = frozenset({"network", "system", "application", "database"})` to add `"kubernetes"`, `"messaging"`, `"cache"`, `"monitoring"` (total 8 values); the `validate_entry()` category check already uses this constant and will automatically accept new values — no other change needed in schema.py

**Checkpoint**: `python -m pytest kb/tests/test_schema.py -q` still passes (no category tests broken by addition).

---

## Phase 3: User Story 1 — Deterministic Entry Normalization (P1) 🎯 MVP

**Goal**: After importing with any model (gpt-4o or deepseek-v4-flash), pending entries always have: English section headers, title ≤60 chars, ≥3 auto-extracted tags, valid category, correct type-level structure. Fixes Root Cause A: QA-9, QA-11, QA-12, QA-14, QA-15, QA-16.

**Independent Test**: Create a draft string with `## 症状`, 95-char title, no tags, `category: kubernetes`, and `type: guideline` containing `## Symptoms`. Call `DraftNormalizer().normalize(draft, "guideline")`. Assert headers translated, title ≤60, tags ≥3, category `kubernetes` accepted (from expanded schema), `## Symptoms` section removed.

- [X] T003 [US1] Create `kb/holmes/kb/agent/normalizer.py` with `DraftNormalizer` class containing: (a) class constant `HEADER_MAP` dict mapping Chinese/non-standard headers to English equivalents (`## 症状`→`## Symptoms`, `## 根因`/`## 根本原因`→`## Root Cause`, `## 解决`/`## 解决方案`/`## 解决步骤`/`## 修复`/`## 修复步骤`/`## 处理方案`/`## 处理步骤`/`## 恢复`/`## 恢复步骤`/`## 操作步骤`/`## 诊断步骤`/`## 经验`→`## Resolution`); (b) class constant `MAX_TITLE_LENGTH = 60`; (c) class constant `MIN_TAGS = 3`, `MAX_TAGS = 8`; (d) `normalize(draft: str, kb_type: str | None = None) -> tuple[str, list[str]]` applying in order: frontmatter parse (return unchanged on failure), header translation in body text, title truncation at last word boundary ≤60 chars (generate from first 60 chars of `root_cause` if title is null/empty), tag auto-extraction via tokenize+stopword-filter+deduplicate when `len(tags) < 3`, type structural constraints (remove `## Symptoms` section for guideline; add warning if pitfall `## Resolution` is empty), category normalization using imported `VALID_PITFALL_CATEGORIES` (map unknown to `system`, log warning); serialize with `frontmatter.dumps()` and return (normalized_draft, warnings_list)

- [X] T004 [US1] In `kb/holmes/kb/agent/pipeline.py`, import `DraftNormalizer` from `holmes.kb.agent.normalizer`; in the `for kp in knowledge_map.knowledge_points` loop, after `draft = extractor.run(kp, knowledge_map, ctx)` and before the `if not draft: continue` check, insert: instantiate `DraftNormalizer()`, call `draft, norm_warnings = normalizer.normalize(draft, kb_type=kp.type_hint or "")`, append each warning as `report.warnings.append(f"{kp.id}: {w}")` — ensure Normalizer runs even on drafts that will later fail validation (normalization reduces false validation failures)

- [X] T005 [P] [US1] Write `kb/tests/test_normalizer.py` with unit tests: (a) Chinese header `## 症状` translated to `## Symptoms`; (b) header `## 根因` translated to `## Root Cause`; (c) 95-char title truncated to ≤60 at word boundary; (d) null/empty title generates fallback from `root_cause`; (e) missing tags: ≥3 extracted from title+root_cause; (f) tags already ≥3: unchanged; (g) guideline with `## Symptoms`: section removed; (h) pitfall with empty `## Resolution`: warning added but header kept; (i) unknown category `team management` normalized to `system` with warning; (j) `kubernetes` category accepted (no normalization, no warning); (k) unparseable frontmatter: returns original draft with single parse-failure warning; (l) idempotency: `normalize(normalize(draft)[0])` equals `normalize(draft)`

**Checkpoint**: `python -m pytest kb/tests/test_normalizer.py -q` — all tests pass. Import any doc with deepseek-v4-flash and verify pending entry has English headers.

---

## Phase 4: User Story 2 — Expanded Category Schema (P2)

**Goal**: Update all LLM prompt strings to enumerate the 8-value category set so models naturally produce valid categories. Fixes Root Cause B: QA-4, QA-13, QA-17.

**Independent Test**: Import a Kubernetes pod eviction document. Assert pending entry has `category: kubernetes` without any override or fallback warning.

- [X] T006 [P] [US2] In `kb/holmes/kb/agent/phases/extractor.py`, update `EXTRACTOR_SYSTEM_PROMPT` category field line (currently `category: <database|network|application|system|infrastructure>`) to `category: <database|network|application|system|kubernetes|messaging|cache|monitoring>` — use the exact string values from `VALID_PITFALL_CATEGORIES`

- [X] T007 [P] [US2] In `kb/holmes/kb/agent/runner.py`, update `_IMPORT_SYSTEM_PROMPT` line that reads `"category (for pitfall: network/system/application/database)"` to include all 8 values: `"category (for pitfall: network/system/application/database/kubernetes/messaging/cache/monitoring)"`

- [X] T008 [P] [US2] In `kb/holmes/kb/agent/phases/reader.py`, update the category description string (line ~91: `"Best-guess category (e.g. database, network, application)."`) to `"Best-guess category (e.g. database, network, system, application, kubernetes, messaging, cache, monitoring)."`

- [X] T009 [P] [US2] In `kb/holmes/kb/importer.py`, update the category comment in the frontmatter template (line ~60: `category: <for pitfall: network|system|application|database; others: omit>`) to include all 8 values: `category: <for pitfall: network|system|application|database|kubernetes|messaging|cache|monitoring; others: omit>`

- [X] T010 [P] [US2] Extend `kb/tests/test_schema.py` with tests: (a) `validate_entry()` with `category: kubernetes` on a pitfall entry → `valid=True`; (b) `category: monitoring` → `valid=True`; (c) `category: cache` → `valid=True`; (d) `category: messaging` → `valid=True`; (e) `category: team management` → `valid=False` (still invalid)

**Checkpoint**: `python -m pytest kb/tests/test_schema.py -q` — new category tests pass.

---

## Phase 5: User Story 3 — Deterministic Skill Generation (P3)

**Goal**: `run.sh` content is generated by `detect_commands()`, not LLM. `{PARAM}` placeholders extracted to `SKILL.md`. 2-command entries produce suggestion only (not auto-create). Fixes Root Cause C: E-3, E-8, E-9, E-10.

**Independent Test**: Call `_run_skill_and_curation` with a resolution_text containing `kubectl delete pod {POD_NAME} -n {NAMESPACE}`. Assert `SKILL.md` has `params:` block listing `POD_NAME` and `NAMESPACE`. Assert `run.sh` contains the exact command. Run `bash -n run.sh` — passes.

- [X] T011 [US3] In `kb/holmes/kb/agent/skill_advisor.py`, revert RECOMMENDED threshold: change `if step_count >= 2:` to `if step_count >= 3:`; update the comment from "C-2c: Lowered RECOMMENDED threshold from ≥3 to ≥2 so that two-step runbooks..." to "E-8 fix: threshold restored to ≥3; 1-2 steps → OPTIONAL (no auto-create)"

- [X] T012 [US3] In `kb/holmes/kb/skill/manager.py`, update `create_skill()` signature to add `param_names: Optional[list[str]] = None` parameter; when `param_names` is non-empty, write `params:` block to the SKILL.md frontmatter with each param as `- name: {NAME}\n  description: {NAME}\n  required: false\n  default: ""` — the block must appear after `timeout:` in the frontmatter; also update the env-var section in `run.sh` template to define `{NAME}="${SKILL_PARAM_{NAME}:-}"` for each param

- [X] T013 [US3] In `kb/holmes/kb/agent/runner.py` `_run_skill_and_curation()`, after `extracted_commands = detect_commands(resolution_text)`, add `_PARAM_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")` and collect param names: `param_names = list(dict.fromkeys(p for cmd in extracted_commands for p in _PARAM_RE.findall(cmd)))`; pass `param_names=param_names` through the `create_skill_for_entry` call (add `param_names` key to `tool_input` dict passed to the tool, or call `create_skill()` directly with it)

- [X] T014 [P] [US3] In `kb/holmes/kb/agent/runner.py` `_dispatch_tool()`, for the `create_skill_for_entry` branch: before calling the tool function, if `tool_input.get("resolution_commands")` is empty or missing, look up the entry from `self._created_entry_contents` using the `entry_id` in `tool_input`, call `detect_commands(self._extract_resolution_section(content))`, and inject the result as `tool_input["resolution_commands"]` — this ensures the LLM-driven path uses the same deterministic command extraction as the fallback path

- [X] T015 [P] [US3] Extend `kb/tests/test_skill_advisor.py` with tests: (a) 3 commands → `RECOMMENDED`; (b) 2 commands → `OPTIONAL` (not RECOMMENDED); (c) 1 command → `OPTIONAL`; (d) 0 commands → `SKIP`; confirm threshold change from previous ≥2

- [X] T016 [P] [US3] Extend `kb/tests/test_skill_manager.py` with tests: (a) `create_skill(kb_root, "test-skill", "desc", param_names=["POD_NAME", "NAMESPACE"])` → SKILL.md contains `params:` block with both params; (b) `run.sh` contains `POD_NAME="${SKILL_PARAM_POD_NAME:-}"` line; (c) `bash -n run.sh` exits 0 (syntax valid); (d) `create_skill()` with `param_names=[]` → no `params:` block in SKILL.md

**Checkpoint**: `python -m pytest kb/tests/test_skill_advisor.py kb/tests/test_skill_manager.py -q` — all pass.

---

## Phase 6: User Story 4 — Document Type Pre-Classification (P4)

**Goal**: Before Reader runs, a single LLM call classifies document type. Non-KB documents (meeting notes, tables) are rejected with 0 entries. Runbooks/multi-incident docs get KP granularity guidance. Fixes Root Cause D: QA-3, QA-5, D-3.

**Independent Test**: (a) Pass meeting notes to classifier → `doc_type=non_kb`, pipeline returns with `report.warnings` containing rejection reason, 0 entries created. (b) Pass runbook → `doc_type=runbook`, `granularity_hint` contains "3–8", Reader receives the hint.

- [X] T017 [US4] Create `kb/holmes/kb/agent/phases/classifier.py` with: (a) `DocumentType` enum with values `single_incident`, `multi_incident`, `runbook`, `guideline`, `non_kb`; (b) `ClassificationResult` dataclass with fields `doc_type: DocumentType`, `reason: str`, `granularity_hint: str`; (c) `GRANULARITY_HINTS` dict mapping each `DocumentType` to the hint string (single_incident: `""`, multi_incident: `"Extract one knowledge point per distinct incident. Do not merge incidents."`, runbook: `"Extract 3–8 high-level operational procedure KPs. Do not split individual command steps into separate KPs."`, guideline: `"Extract one knowledge point per rule or principle."`, non_kb: `""`); (d) `DocumentClassifier` class with `__init__(self, provider: LLMProvider, model: str)` and `classify(self, source_text: str) -> ClassificationResult` that makes one LLM call with a concise system prompt asking for JSON `{"doc_type": "...", "reason": "..."}`, parses the response, returns `ClassificationResult`; on any exception or parse failure returns `ClassificationResult(doc_type=DocumentType.single_incident, reason="classification failed — default", granularity_hint="")`

- [X] T018 [US4] In `kb/holmes/kb/agent/pipeline.py` `run()`, import `DocumentClassifier` and `DocumentType` from `holmes.kb.agent.phases.classifier`; inject classifier call at the top of `run()` before `ReaderAgent.run()`: instantiate `DocumentClassifier(provider=self._provider, model=self.cfg.model)`, call `classification = classifier.classify(source_text)`, append `f"Classifier: {classification.doc_type.value} — {classification.reason}"` to `report.phase_traces`; if `classification.doc_type == DocumentType.non_kb`, append `f"non-kb document: {classification.reason} — skipped"` to `report.warnings` and `return report`; otherwise store `ctx["granularity_hint"] = classification.granularity_hint`

- [X] T019 [US4] In `kb/holmes/kb/agent/phases/reader.py` `ReaderAgent.run()`, read `granularity_hint = ctx.get("granularity_hint", "")` from context; if non-empty, prepend `f"Document granularity guidance: {granularity_hint}\n\n"` to the user prompt passed to the LLM — position this before the main source text in the prompt

- [X] T020 [P] [US4] Write `kb/tests/test_classifier.py` with unit tests using a mock `LLMProvider`: (a) LLM returns `{"doc_type": "runbook", "reason": "sequential steps"}` → `ClassificationResult.doc_type == DocumentType.runbook` and `granularity_hint` contains "3–8"; (b) LLM returns `{"doc_type": "non_kb", "reason": "meeting notes"}` → `doc_type == non_kb`, empty `granularity_hint`; (c) LLM raises exception → `doc_type == single_incident`, `reason == "classification failed — default"`; (d) LLM returns malformed JSON → same default fallback; (e) `multi_incident` → hint contains "one knowledge point per distinct incident"; (f) `single_incident` → empty granularity_hint

**Checkpoint**: `python -m pytest kb/tests/test_classifier.py -q` — all pass. Import a meeting notes file and verify 0 entries created with warning.

---

## Phase 7: User Story 5 — Extractor Verbatim Command Copy + Verifier Fallback (P5)

**Goal**: Extractor is instructed to copy commands verbatim. When Verifier CLEARs `pitfall` Resolution anyway, deterministic fallback restores commands from source text. Fixes Root Cause E: D-2 (persisting), QA-16 (remaining cases).

**Independent Test**: Create a pipeline with a mock extractor that returns a pitfall draft with empty `## Resolution`. Assert the pipeline injects commands from the source text slice and adds a warning containing "auto-recovered from source".

- [X] T021 [US5] In `kb/holmes/kb/agent/phases/extractor.py`, locate `EXTRACTOR_SYSTEM_PROMPT` and add to the "IMPORTANT RULES" section: `"- All commands in the ## Resolution section MUST be copied verbatim character-for-character from the source text. Do NOT paraphrase, reorder, summarize, or reconstruct commands. If you cannot find the exact commands in your assigned section, write only the commands that appear word-for-word in the source, and omit the rest."` — add this after the existing rule about field content needing source text support

- [X] T022 [US5] In `kb/holmes/kb/agent/pipeline.py`, add module-level helper functions: `_is_resolution_empty(draft: str) -> bool` (parses frontmatter body, checks if `## Resolution` section exists and is non-empty after stripping whitespace; returns `True` if missing or empty) and `_inject_resolution(draft: str, commands: list[str]) -> str` (parses frontmatter, finds or creates `## Resolution` section in body, inserts `[auto-recovered from source]\n` + commands joined by newline; returns serialized draft); in the extraction loop, after `repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)`, add: if `kp.type_hint == "pitfall"` (or parsed type is `pitfall`) AND `_is_resolution_empty(repaired)`, call `source_slice = source_text[kp.section_start:kp.section_end]`, `recovered = detect_commands(source_slice)` (import from `holmes.kb.skill.manager`), if `recovered`: `repaired = _inject_resolution(repaired, [c.command for c in recovered])`, `report.warnings.append(f"{kp.id}: resolution auto-recovered from source ({len(recovered)} commands)")`

- [X] T023 [P] [US5] Extend `kb/tests/test_pipeline.py` with tests: (a) mock extractor returning pitfall draft with empty `## Resolution` + source containing `kubectl rollout restart deployment/api` → assert pending draft's `## Resolution` contains `[auto-recovered from source]` and the kubectl command, assert `report.warnings` contains "auto-recovered"; (b) mock extractor returning pitfall with non-empty `## Resolution` → no recovery, no warning; (c) mock extractor returning guideline with no Resolution → no recovery attempted (only pitfall triggers fallback)

**Checkpoint**: `python -m pytest kb/tests/test_pipeline.py -q` — all pass (existing + new).

---

## Phase 8: User Story 6 — Skill Lifecycle Correctness (P6)

**Goal**: Fix three Skill lifecycle bugs: single-doc Runbook entries now trigger Skill generation (E-1); importing same-topic document links to existing Skill instead of creating duplicate (E-11); interactive mode prompts before creating Skill (E-12).

**Independent Test**: (a) Run `_finalize_skill_generation` on a report where `skills_generated=["existing-skill"]` plus one unprocessed pitfall entry with resolution_text → assert Skill generation runs for the unprocessed entry. (b) Create a skill named "api-recovery", then call `SkillAdvisor.advise()` with a description matching it → assert `recommendation=LINK`. (c) Call `_dispatch_tool("create_skill_for_entry", ...)` with `no_interactive=False` + mock prompt returning "n" → assert `created=False`.

- [X] T024 [US6] In `kb/holmes/kb/agent/runner.py` `_finalize_skill_generation()`, remove the early-return block `if report.skills_generated or report.skills_linked: return` (lines ~429-430) and the `already_suggested` early-return block; the method should unconditionally iterate all `self._created_entry_contents` entries and call `_run_skill_and_curation()` for each with non-empty resolution_text — per-entry duplicate detection is handled by `SkillAdvisor._find_existing_skill()` checking `skill_refs` frontmatter

- [X] T025 [US6] In `kb/holmes/kb/agent/skill_advisor.py`, add method `_find_similar_skill(self, kb_root: Path, description: str) -> Optional[str]` that: scans `sorted((kb_root / "skills").glob("*/SKILL.md"))` if the directory exists, for each file loads frontmatter and reads `description` field, computes Jaccard token-overlap `len(set_a & set_b) / len(set_a | set_b)` where sets are lowercase non-stopword tokens (split on whitespace+punctuation), returns the skill's directory name if ratio ≥ 0.7, else `None`; call this method at the start of `advise()` after the `_find_existing_skill` check and before generating a new slug: if `_find_similar_skill` returns a name, return `SkillAdvice(recommendation=Recommendation.LINK, suggested_name=name, reason=f"similar skill found: {name}", existing_skill=name)`

- [X] T026 [P] [US6] In `kb/holmes/kb/agent/runner.py` `_dispatch_tool()`, locate the `elif name == "create_skill_for_entry":` branch; before it proceeds to call the tool or record the skill, add an interactive gate check: `if not self.no_interactive:` call `confirmed = self._gate_skill_create(skill_name)`, if not confirmed return `{"created": False, "linked": False, "action": "skipped (user declined)", "skill_dir": None}` as the tool result without calling the underlying tool function

**Checkpoint**: `python -m pytest kb/tests/test_agent_runner.py -q` — all pass.

---

## Phase 9: User Story 7 — CLI Output Clarity (P7)

**Goal**: `--dry-run` shows estimated KP count from a Reader-only pass. `--dir` batch import shows entry title in `[N/M]` line, not pending ID. Fixes: E-4, E-6.

**Independent Test**: (a) Run `import_cmd` with `dry_run=True` on a mock pipeline that returns a report with `knowledge_map.knowledge_points = [kp1]` → assert output contains "~1 knowledge points estimated". (b) Run batch import where first file creates `title: "Nginx 502"` → assert `[1/N]` line contains "Nginx 502", not a pending ID.

- [X] T027 [US7] In `kb/holmes/kb/agent/pipeline.py` `run()`, add dry-run early-exit path: when `self.dry_run is True`, run DocumentClassifier and ReaderAgent (both are read-only) but skip the Extractor/Verifier/Writer phases; after `reader.run()`, set `report.knowledge_map = knowledge_map` and return the report immediately; in `kb/holmes/kb/agent/report.py` `format_dry_run_plan()`, update to: if `self.warnings` contains "non-kb", show `"  Would reject: non-kb document — {reason}"`; elif `self.knowledge_map` is set, show `"  Would process: (~{N} knowledge points estimated)"` where N is `len(self.knowledge_map.knowledge_points)`; else show existing fallback

- [X] T028 [P] [US7] In `kb/holmes/cli.py`, add helper function `_get_pending_title(pending_id: str, kb_root: Path) -> Optional[str]` that reads `kb_root / "contributions" / "pending" / f"{pending_id}.md"`, parses frontmatter, returns `str(post.metadata.get("title", ""))` or `None` if file not found/parse error; in the per-file progress output in the `--dir` batch import loop, after the report is processed, call `_get_pending_title(report.created[0], kb_root)` if `report.created` is non-empty, and use the result (or source filename fallback) as the display label in the `[N/M] <label> — ...` line

**Checkpoint**: `holmes import runbook.md --dry-run 2>&1 | grep "Would process"` returns non-empty output.

---

## Phase 10: User Story 8 — API Error User-Friendly Messages (P8)

**Goal**: Authentication errors, rate limits, and server errors produce human-readable messages with suggested actions instead of raw JSON. Fixes: E-5.

**Independent Test**: Mock `openai.AuthenticationError`; call `openai_provider.complete()`; assert `RuntimeError` is raised with message containing "Authentication failed" and "holmes config set api_key".

- [X] T029 [US8] In `kb/holmes/kb/agent/provider/openai_provider.py`, wrap the `self._client.chat.completions.create(...)` call in the `complete()` method with: `except openai.AuthenticationError: raise RuntimeError("Authentication failed — API key rejected. Check your key with: holmes config set api_key <KEY>") from None`; `except openai.RateLimitError: raise RuntimeError("Rate limit reached. Wait a moment and retry, or check your plan quota.") from None`; `except openai.APIStatusError as exc: raise RuntimeError(f"LLM provider returned a server error (HTTP {exc.status_code}). Check provider status or retry.") from None` — place these handlers inside the existing try/except if one exists, otherwise add a new try/except block around the client call; the raw exception (including JSON body) must NOT propagate

**Checkpoint**: Set `INVALID_KEY`, run import, confirm output shows human-readable error without JSON.

---

## Phase 11: Polish — Full Regression Validation

**Purpose**: Confirm all 582 existing tests + new tests pass after all 8 user stories are complete.

- [X] T030 [P] Run full test suite `python -m pytest -q` from `kb/` directory; confirm all tests pass including `test_normalizer.py`, `test_classifier.py`, and all extended existing test files with zero failures; fix any regressions before marking complete

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1 ✅ — blocks US1 Normalizer (T003 imports VALID_PITFALL_CATEGORIES)
- **US1 (Phase 3)**: Depends on Phase 2 (schema constant must exist)
- **US2 (Phase 4)**: Depends on Phase 2 (can start parallel with US1 — all different files)
- **US3 (Phase 5)**: Independent of US1/US2 — can start after Phase 2
- **US4 (Phase 6)**: Independent of US1–US3 — can start after Phase 2
- **US5 (Phase 7)**: T022 imports `detect_commands` from `skill/manager.py` (already exists); independent of US1–US4
- **US6 (Phase 8)**: T025 depends on `SkillAdvisor` (already exists); independent of US1–US5
- **US7 (Phase 9)**: T027 modifies `pipeline.py` — if US1 and US4 also modify pipeline.py, coordinate merge carefully (different sections)
- **US8 (Phase 10)**: Fully independent
- **Polish (Phase 11)**: Depends on all phases complete

### Within Each Phase

- T003 → T004 (US1): create module first, then inject
- T011 → T012 → T013 (US3): threshold first, then create_skill signature, then runner caller
- T017 → T018 → T019 (US4): create classifier, inject into pipeline, update reader
- T021 → T022 (US5): prompt update, then fallback implementation
- T024, T025, T026 (US6): all independent of each other within phase

### pipeline.py Coordination

Three user stories modify `pipeline.py` (US1-T004, US4-T018, US5-T022, US7-T027). Each touches a different section:
- T004: extraction loop (after extractor.run)
- T018: top of run() before ReaderAgent
- T022: extraction loop (after repair step)
- T027: dry-run early-exit path

Implement in order: T018 (top of run) → T004 (extraction loop, Normalizer) → T022 (extraction loop, fallback) → T027 (dry-run path). Each adds to different sections of the same method.

### Parallel Opportunities

```
[P2]  T002 ──────────────────────────────────────────────────────────────────►
[US1] T003 → T004                    T005 [P] ►
[US2] T006 [P] T007 [P] T008 [P] T009 [P] T010 [P] ►
[US3] T011 → T012 → T013            T014 [P] T015 [P] T016 [P] ►
[US4] T017 → T018 → T019            T020 [P] ►
[US5] T021 → T022                   T023 [P] ►
[US6] T024     T025     T026 [P] ►
[US7] T027                          T028 [P] ►
[US8] T029 ►
[P11] T030 [P] ►
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only — Root A + B)

1. Complete Phase 2: T002 (schema expansion)
2. Complete Phase 3: T003, T004 (Normalizer create + inject) + T005 [P]
3. Complete Phase 4: T006–T010 (prompt updates + schema tests) [all parallel]
4. **STOP and VALIDATE**: `python -m pytest kb/tests/test_normalizer.py kb/tests/test_schema.py -q`
5. Manual check: import doc with deepseek → pending entry has English headers, tags ≥3, valid category

### Incremental Delivery

1. US1+US2 → eliminates Chinese-header and empty-tags failures (highest QA impact)
2. US3 → eliminates model-dependent Skill generation
3. US4 → prevents non-KB content import + fixes Runbook over-splitting
4. US5 → fixes empty Resolution in pitfall entries
5. US6 → fixes Skill lifecycle (trigger, LINK, interactive gate)
6. US7 → dry-run preview + batch title display
7. US8 → API error messages
8. Polish → full regression validation

---

## Notes

- [P] tasks touch different files with no cross-dependency
- pipeline.py is modified by US1/US4/US5/US7 — implement in order: T018 (top) → T004 (loop Normalizer) → T022 (loop fallback) → T027 (dry-run path)
- runner.py is modified by US3 (T013, T014) and US6 (T024, T026) — different methods, no conflict
- skill_advisor.py is modified by US3 (T011) and US6 (T025) — different methods, no conflict
- T030 (full regression) must NOT be run until T001–T029 are all complete
- New test files (`test_normalizer.py`, `test_classifier.py`) are fully parallel with their implementation tasks
