# Contracts: ExtractorAgent (D-1, D-2)

## Contract: `_validate_and_repair_draft(draft) -> (repaired, warning)`

**Pre-conditions**:
- `draft` is the raw string returned by `_extract_draft()`; may be empty, malformed, or valid

**Post-conditions**:
- If `draft` is valid (parseable YAML frontmatter with `---` delimiters): returns `(draft, None)`
- If `draft` has recoverable issues (missing closing `---`, prose preamble): returns `(repaired, warning_str)`
- If `draft` is unrecoverable (empty, no `---` at all, YAML error that can't be repaired): returns `("", error_str)`
- Never raises an exception

**Invariant**:
- Returned `repaired` (when non-empty) must be parseable by `frontmatter.loads()`

---

## Contract: `EXTRACTOR_SYSTEM_PROMPT` (D-2)

**Invariant**:
- Prompt MUST contain the verbatim-copy instruction for `## Resolution` shell commands
- Prompt MUST NOT instruct the LLM to summarize or paraphrase commands
- Exact wording must include "VERBATIM" (or equivalent) for shell command lines
