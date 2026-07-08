# Extraction Design: What to Extract for Each KB Type

## Design Principle: Backward from Consumption

The KB is consumed by an AI agent via MCP in a progressive disclosure pattern:

```
kb_browse (title + brief + tags)     → "Is this relevant?"
    ↓
kb_read summary (type-specific)      → "Does this match my situation?"
    ↓
kb_read full (complete Markdown)     → "How do I act on this?"
```

Each extraction field must serve one of these three moments.
Anything that doesn't help the agent at any of these moments is noise.

---

## Per-Type Extraction Strategy

### pitfall — "Something broke. What is it and how do I fix it?"

Agent workflow: Engineer reports a problem → agent matches symptoms → confirms
root cause → guides through resolution steps.

**Extraction dimensions:**

| Dimension | What to extract | Why the agent needs it |
|-----------|----------------|----------------------|
| **Matching signals** | Error messages verbatim, log patterns, CLI output anomalies, LED/indicator states, metric thresholds that are abnormal | kb_browse: agent matches engineer's description against symptoms. The more specific the symptom ("`Memory ECC Error` from slot A1/DIMM 0"), the better the match vs vague ("memory has issues"). |
| **Applicable context** | Platform, component model/version, firmware version, environmental conditions (load, temperature, duration) | kb_read summary: agent checks "does this apply to the engineer's setup?" A fix for DDR5 on Sapphire Rapids may not apply to DDR4 on EPYC. |
| **Root cause chain** | The cause→effect reasoning, not just the conclusion. "Single-bit errors accumulate under sustained high-temp load → exceed BIOS uncorrectable threshold → system reboot" | kb_read summary: agent explains WHY to the engineer, building trust. Also helps disambiguate: two problems may have the same symptom but different root causes. |
| **Diagnostic checkpoints** | The tests that CONFIRM the root cause. "Swap DIMM → if error follows DIMM → confirmed DIMM body fault, not slot" | kb_read full: agent guides engineer through confirmation before committing to a fix path. |
| **Branch conditions** | The observable condition that determines which resolution path to take. "lspci sees nothing → Path A; sees device but degraded → Path B" | kb_read full: agent asks engineer "what do you see?" and routes to correct branch. |
| **Resolution steps** | Ordered steps with exact commands, physical actions, and decision points. Each step: what to do + what to expect + what to do if unexpected | kb_read full: agent walks engineer through fix one step at a time. |
| **Verification** | How to confirm the problem is actually fixed. "72h burn-in, ECC count = 0" | kb_read full: agent tells engineer how to verify after fix. |
| **Lessons/thresholds** | Experience-based rules of thumb. "ECC > 500/h is suspicious" "burn-in < 72h is insufficient" | kb_read full: agent provides expert-level judgment guidance. |

**Single-branch vs multi-branch:**
- Single-branch: Linear cause→fix. Extract the full chain faithfully.
- Multi-branch: The BRANCH CONDITIONS are the most critical extraction.
  Without clear branch conditions, the agent can't route the engineer.
  Extract: "when you see X → path A" as structured data, not prose.

**What NOT to extract for pitfall:**
- Narrative filler ("we then proceeded to investigate")
- Organizational context ("the NOC team was notified")
- Duplicate restatements of the same fact

---

### model — "How does X work? What do these numbers mean?"

Agent workflow: During troubleshooting, agent needs to understand a mechanism
to interpret observations or make recommendations.

**Extraction dimensions:**

| Dimension | What to extract | Why the agent needs it |
|-----------|----------------|----------------------|
| **Concept definitions** | One-sentence definition of each concept. "PROCHOT is an Intel signal indicating the processor has reached Tjunction max" | kb_browse: agent determines if this model is relevant to current situation |
| **Mechanisms** | How each mechanism works: trigger condition → behavior → consequence. "PROCHOT asserted → CPU drops to min P-state → 50-80% performance loss" | kb_read full: agent explains to engineer what's happening and why |
| **Key parameters** | Quantitative specs: thresholds, limits, ranges, timeouts. "Tjunction max = 100-105C" "PL2 window = 28 seconds" | kb_read full: agent uses these numbers to help engineer interpret their observations. "Your CPU is at 102C — that's above Tjunction max, PROCHOT should be active" |
| **Relationships** | How concepts interact: hierarchy, sequence, conflicts. "RAPL→PROCHOT→THERMTRIP form layered defense" | kb_read full: agent understands the system holistically |
| **Diagnostic relevance** | How to observe/measure this mechanism. "rdmsr 0x19C bit 0 = PROCHOT active" | kb_read full: agent provides concrete commands to check mechanism state |
| **NPI implications** | What this means for validation. "Test at max inlet temp" "Verify PROCHOT activates before THERMTRIP in fan-failure mode" | kb_read full: agent recommends validation actions |

**What NOT to extract for model:**
- Textbook-level basics the agent already knows
- Historical evolution of a technology
- Marketing-level descriptions

---

### guideline — "What rules must I follow?"

Agent workflow: Before or during an operation, agent checks if the engineer
is following established rules. Or agent proactively warns about rules.

**Extraction dimensions:**

| Dimension | What to extract | Why the agent needs it |
|-----------|----------------|----------------------|
| **Scope** | When/where/who this guideline applies to. "All NPI team members in the lab environment" | kb_browse: agent determines if this guideline is relevant to current operation |
| **Rules** | Each rule as a specific, actionable statement. "Must wear ESD wristband before touching any electronic component" — not "be careful with ESD" | kb_read summary: agent presents rules the engineer must follow |
| **Quantitative criteria** | Measurable standards. "Wristband resistance 1MΩ ± 10%" "Ion fan decay < 2 seconds" "Residual voltage < ±25V" | kb_read full: agent can verify compliance with specific numbers |
| **Rationale** | Why each rule exists — the consequence of violation. "ESD-damaged components may pass initial tests but fail weeks later at customer site → high RMA cost" | kb_read full: agent explains WHY to the engineer (people follow rules better when they understand the reason) |
| **Verification method** | How to check compliance. "Daily wristband resistance test" "Weekly ion fan calibration" | kb_read full: agent recommends how to verify |
| **Severity** | Which rules are hard (must) vs soft (should). "Wireless wristband is NOT acceptable" (hard) vs "Recommended to use anti-static tray" (soft) | kb_read full: agent prioritizes warnings |

**What NOT to extract for guideline:**
- Organizational reporting structure
- Training schedule logistics
- Generic safety disclaimers not specific to the technical domain

---

### process — "Walk me through this procedure step by step"

Agent workflow: Engineer needs to perform an operation. Agent acts as a
GPS navigator, guiding each step and confirming completion before advancing.

**Extraction dimensions:**

| Dimension | What to extract | Why the agent needs it |
|-----------|----------------|----------------------|
| **Purpose & scope** | What this procedure accomplishes, when to use it | kb_browse: agent determines if this is the right procedure |
| **Prerequisites** | What must be true before starting. Tools needed, access required, approval needed, maintenance window | kb_read summary: agent verifies prerequisites are met before starting |
| **Risk warnings** | What can go wrong, what's irreversible. "Failed BMC flash → bricked management controller → physical board replacement" | kb_read summary: agent warns engineer about stakes |
| **Ordered steps with commands** | Each step: action + exact command + expected output. Must preserve step ordering. | kb_read full: agent presents one step at a time |
| **Checkpoints** | After each major step, how to verify success before proceeding. "Verify firmware version matches target" "Confirm BMC is responsive after reboot" | kb_read full: agent confirms each step succeeded |
| **Critical warnings** | Mid-process points of no return. "Do NOT power cycle during flash" | kb_read full: agent warns at the right moment, not at the beginning |
| **Completion criteria** | What the final state should look like. "BMC at target version, sensors readable, server powers on, network intact" | kb_read full: agent verifies procedure completed successfully |
| **Rollback** | What to do if the procedure fails. Recovery steps, alternative paths | kb_read full: agent guides recovery if something goes wrong |

**What NOT to extract for process:**
- Explanations of WHY each step works (that's model territory)
- Alternative approaches not part of this procedure
- Historical context of why this procedure was created

---

### decision — "Why did we choose this? Should we reconsider?"

Agent workflow: Engineer questions a design choice, or faces a similar
decision. Agent explains the rationale and applicability.

**Extraction dimensions:**

| Dimension | What to extract | Why the agent needs it |
|-----------|----------------|----------------------|
| **Problem statement** | What situation required a decision. Constraints, requirements, timeline pressure | kb_browse: agent determines if this decision is relevant to engineer's question |
| **Options considered** | Each alternative with specific pros and cons. Not vague — "Option A: Gen5 for all → Pro: max speed, Con: 15% failure rate on slots 3-6" | kb_read summary: agent presents the options that were weighed |
| **Chosen option** | Which option was selected, with implementation details (commands, configuration) | kb_read full: agent explains the current state and how to apply it |
| **Key trade-off** | The decisive factor. "Stability over speed: 15% random failure wastes more engineering time than Gen4 performance gap" | kb_read full: agent communicates the reasoning, not just the conclusion |
| **Scope & constraints** | Where this decision applies. "Granite platform, Rev B PCB, until Rev C arrives" | kb_read full: agent knows when this decision is/isn't applicable |
| **Revisit triggers** | When to reconsider. "Revisit when Rev C PCB arrives (2024-Q3)" | kb_read full: agent can proactively flag that conditions may have changed |

**What NOT to extract for decision:**
- Meeting process details (who attended, how many rounds of discussion)
- Emotional reasoning ("the team felt that...")
- Options that were considered but had zero viability

---

## Cross-Type Extraction Principles

1. **Specificity > generality**: "ECC error > 500/h from slot A1/DIMM 0" beats
   "memory errors detected". Specific facts are what enable the agent to MATCH
   correctly and ACT precisely.

2. **Self-contained facts**: Each extracted item should be understandable alone,
   without needing to read other items for context. The agent may retrieve and
   present individual facts, not the whole list.

3. **Commands are sacred**: Every command, code block, config snippet, and API
   call must be extracted verbatim. These are the most actionable part of the KB.
   The agent will present them directly to the engineer.

4. **Preserve cause-effect chains**: Don't just extract conclusions ("it was a
   DIMM fault"). Extract the reasoning chain ("swap DIMM → error followed →
   confirmed DIMM body fault"). The chain IS the knowledge.

5. **Extract for retrieval, not for reading**: Key facts are optimized for the
   agent to find and match against engineer's questions, not for human reading
   pleasure. Completeness and precision > prose quality.
