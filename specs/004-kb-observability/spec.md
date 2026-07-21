# Feature Specification: KB Governance Observability Platform

**Feature Branch**: `004-kb-observability`

**Created**: 2026-06-03

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Per-User Contribution Metrics (Priority: P1)

As a KB administrator, I want to see a dashboard showing each contributor's KB activity — how many entries they submitted, how many were confirmed or rejected, and their confirmation rate — so I can identify active contributors and those who need guidance.

**Why this priority**: Without per-user visibility, admins cannot assess contribution quality or identify inactive contributors. This is the core value of the feature.

**Independent Test**: Can be fully tested by running a set of `write-pending` and `confirm`/`reject` CLI commands as different users, then verifying the dashboard shows correct counts per user.

**Acceptance Scenarios**:

1. **Given** a contributor has submitted 5 pending entries and 3 were confirmed, **When** an admin opens the dashboard, **Then** that contributor's row shows pending_submitted=5, entries_confirmed=3, entries_rejected=2, confirmation_rate=60%.
2. **Given** no activity has occurred for a user, **When** the admin views the dashboard, **Then** that user does not appear in the contributor table.
3. **Given** two different contributors submitted entries in the same session, **When** viewing per-user stats, **Then** each contributor's metrics are counted independently.

---

### User Story 2 - Track KB Entry Lifecycle Events (Priority: P2)

As a KB administrator, I want a real-time event log showing every KB mutation (write-pending, confirm, reject, correction, decay, archive, update-refs) with the responsible contributor and timestamp, so I can audit changes and replay the history of any entry.

**Why this priority**: Audit trail is critical for governance trust. Without it, admins cannot investigate disputes or trace how an entry reached its current state.

**Independent Test**: Can be tested by executing each of the 7 CLI event types and verifying a corresponding event record appears in the event log with correct fields (event_type, contributor, entry_id, timestamp).

**Acceptance Scenarios**:

1. **Given** a contributor runs `holmes kb confirm <id>`, **When** the event log is queried, **Then** a `kb.confirm` event appears with the contributor name, entry ID, and confirmation timestamp within 1 minute.
2. **Given** a decay scan runs and demotes 3 entries, **When** the event log is viewed, **Then** 3 `kb.decay` events appear, each with the entry ID, old maturity, and new maturity.
3. **Given** an update-refs command references 2 entries, **When** the event log is checked, **Then** 2 `kb.update_refs` events appear, each with the session_id and contributor fields.
4. **Given** the system is offline and a contributor runs a CLI command, **When** connectivity is restored, **Then** the buffered events are forwarded and appear in the log within 5 minutes.

---

### User Story 3 - Monitor Global KB Health (Priority: P3)

As a KB administrator, I want a global health overview showing the distribution of entries by maturity level, decay activity, and pending backlog size, so I can assess the overall quality of the knowledge base at a glance.

**Why this priority**: Per-user metrics alone do not reveal systemic issues. Global health metrics give administrators early warning of KB degradation.

**Independent Test**: Can be tested by seeding the KB with entries at different maturity levels and verifying the dashboard correctly counts entries per maturity group and shows the current pending backlog count.

**Acceptance Scenarios**:

1. **Given** the KB has 10 draft, 5 verified, and 2 proven entries, **When** the admin views the health overview, **Then** the maturity distribution panel shows correct counts for each level.
2. **Given** the pending backlog contains 8 unreviewed entries, **When** the admin views the dashboard, **Then** the pending backlog metric shows 8.
3. **Given** 3 entries were decayed in the last 30 days, **When** the admin opens the decay trend panel, **Then** it shows 3 decay events in the 30-day window.

---

### User Story 4 - Contributor Activity Over Time (Priority: P4)

As a KB administrator, I want to see each contributor's activity over time (active days in the last 30 days, sessions that referenced KB entries, maturity promotions they contributed to), so I can recognize highly engaged contributors and identify those who have gone inactive.

**Why this priority**: Point-in-time counts do not reveal trends. Time-series activity shows whether the contributor base is growing, stable, or declining.

**Independent Test**: Can be tested by simulating events across multiple days for one contributor and verifying the active_days_30d counter matches the distinct days on which events were recorded.

**Acceptance Scenarios**:

1. **Given** a contributor performed KB actions on 5 distinct days in the last 30 days, **When** the admin views that contributor's profile, **Then** active_days_30d shows 5.
2. **Given** a contributor's update-refs events triggered 2 maturity promotions from verified to proven, **When** the admin views the contributor's metrics, **Then** maturity_promotions_contributed shows 2.
3. **Given** a contributor has had no activity for 31 days, **When** the admin views the dashboard, **Then** active_days_30d shows 0 for that contributor.

---

### Edge Cases

- When a CLI command fails (exit code non-zero), no event is written — only successful mutations are recorded.
- How does the system handle duplicate events if the local buffer is forwarded twice due to a network retry?
- What happens if a contributor ID is not set in the user's environment — which identity is used?
- How does the dashboard behave when the observability backend is unreachable?
- When the buffer reaches the 500 MB limit, oldest events are dropped and a `buffer_overflow` event is written. The drop count is visible in the dashboard so admins know data loss occurred.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST record an event each time one of the 7 KB mutation commands completes successfully (exit code 0): write-pending, confirm, reject, correction (confirm --corrects), decay, archive-orphan, update-refs. Failed command executions MUST NOT produce an event record.
- **FR-002**: Each event record MUST include: event_type, contributor identity, entry_id (where applicable), timestamp (UTC ISO 8601), and any relevant state change (e.g., old_maturity → new_maturity).
- **FR-003**: Event recording MUST NOT add perceptible latency to CLI command execution; the CLI command must complete first and event writing must be asynchronous or fire-and-forget.
- **FR-004**: The system MUST buffer events locally on the user's machine when the observability backend is unavailable, and forward buffered events when connectivity is restored. Flush is attempted twice: once asynchronously when the CLI command exits, and once every 5 minutes by a background process.
- **FR-013**: The local buffer MUST enforce a configurable maximum file size (default: 500 MB). When the limit is exceeded, the system MUST asynchronously discard the oldest events and append a synthetic `buffer_overflow` warning event containing the count of dropped records. The discard operation MUST NOT block event writing or flushing.
- **FR-005**: The system MUST deduplicate forwarded events so that a network retry or double-flush does not double-count any event.
- **FR-006**: The admin dashboard MUST display per-user metrics: pending_submitted, entries_confirmed, entries_rejected, confirmation_rate, corrections_submitted, sessions_referencing_kb, entries_referenced, maturity_promotions_contributed, active_days_30d. All metrics MUST be filterable by one of four preset time windows: last 7 days, last 30 days, last 90 days, or all time.
- **FR-007**: The admin dashboard MUST display global KB health metrics: entry count by maturity level (draft/verified/proven), pending backlog size, decay events in the last 30 days and 90 days. Global metrics MUST also support the same four preset time windows.
- **FR-008**: The admin dashboard MUST be accessible via a web browser without installing additional software on the viewer's machine.
- **FR-009**: The observability backend MUST be deployable with a single command on any machine with a container runtime available.
- **FR-010**: The system MUST allow the observability backend endpoint to be configured per-user so contributors in different environments can point to different collectors.
- **FR-011**: If a contributor identity is not configured, the system MUST use a deterministic fallback identity (e.g., system hostname) and record a warning alongside the event.
- **FR-012**: The system MUST retain raw event data for at least 90 days before automatic expiry.

### Key Entities

- **KBEvent**: A single KB mutation event — fields: event_type, contributor, entry_id, session_id, timestamp, metadata (type-specific payload such as old_maturity, new_maturity, corrects_id).
- **ContributorMetrics**: Aggregated per-user view — fields: contributor_id, pending_submitted, entries_confirmed, entries_rejected, confirmation_rate, corrections_submitted, sessions_referencing_kb, entries_referenced, maturity_promotions_contributed, active_days_30d.
- **KBHealthSnapshot**: Point-in-time global health — fields: draft_count, verified_count, proven_count, pending_backlog, decay_30d, decay_90d, snapshot_time.
- **LocalBuffer**: On-disk queue of unforwarded events — fields: events (list of KBEvent), last_flush_attempt, flush_status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every KB mutation CLI command execution produces a corresponding event visible in the admin dashboard within 5 minutes of the command completing.
- **SC-002**: KB CLI command execution time increases by no more than 50 milliseconds due to observability instrumentation (measured as p99 latency overhead).
- **SC-003**: An admin can determine the complete contribution history of any KB entry — all events touching that entry — by querying the dashboard without accessing the server directly.
- **SC-004**: The observability backend starts successfully and the dashboard loads within 2 minutes of running the deployment command on a machine with a container runtime.
- **SC-005**: Events buffered during up to 7 days of offline CLI usage are successfully forwarded and appear correctly in the dashboard within 10 minutes of connectivity being restored.
- **SC-006**: No event is counted more than once in per-user metrics, even if the local buffer is flushed multiple times for the same event.
- **SC-007**: The dashboard shows contributor activity data with no more than 5-minute staleness under normal operating conditions.

## Clarifications

### Session 2026-06-03

- Q: 预期团队规模和事件流量是多少？ → A: 中型团队，≤200 贡献者，≤10,000 事件/天
- Q: 本地缓冲区刷新策略是什么？ → A: 定时 + 命令后触发：CLI 命令退出时异步尝试一次刷新，同时后台进程每 5 分钟兜底刷新
- Q: Dashboard 支持哪种时间范围筛选？ → A: 预设固定窗口：7天 / 30天 / 90天 / 全部 可切换
- Q: 本地缓冲区溢出策略是什么？ → A: 默认上限 500 MB（可配置），超出时异步丢弃最旧事件并追加 buffer_overflow 警告事件，丢弃操作不阻塞正常事件写入和上报
- Q: CLI 命令失败时是否记录事件？ → A: 只记录成功事件（exit code 0），失败不写入缓冲区，避免污染贡献率统计

## Assumptions

- The system is deployed in a trusted internal network; no authentication is required on the dashboard for v1.
- Contributors are identified by a user-configurable string (e.g., their GitHub handle or name) stored in `~/.holmes/config.json`; this is set during `holmes setup`.
- Agent-side KB reads are not tracked — only CLI-invoked mutations are observable.
- The observability backend is managed by a single team administrator; individual contributors only need to configure the collector endpoint.
- The local buffer file is stored in the user's Holmes home directory (`~/.holmes/telemetry.jsonl`) and is not shared between users.
- The system is sized for up to 200 contributors and up to 10,000 KB mutation events per day; a single-node deployment is sufficient at this scale.
- The deployment environment supports at least 2 GB RAM for the containerized backend stack.
- Data retention beyond 90 days is out of scope for v1; no archival or export feature is included.
- Mobile or native app dashboards are out of scope; a web browser is the only required client.
