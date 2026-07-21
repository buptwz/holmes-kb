# Feature Specification: Multi-Provider LLM Configuration

**Feature Branch**: `014-multi-provider-llm`

**Created**: 2026-06-08

**Status**: Draft

**Input**: User description: "允许用户配置自己的 LLM provider：支持 Anthropic 原生 API（anthropic SDK）和 OpenAI 兼容 API（openai SDK，兼容 OpenAI、Azure OpenAI、本地 Ollama 等）。用户通过 `holmes setup` 或配置文件指定 provider 类型（anthropic / openai）、model、api_key、api_base_url。import agent 根据 provider 选择对应 SDK 建立连接，工具调用循环（tool-use loop）在两种 provider 下均可工作。错误提示应明确说明当前 provider 类型。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure Anthropic Provider (Priority: P1)

A user with an Anthropic API key wants to use the `holmes import` command. They run `holmes setup`, specify `anthropic` as their provider, enter their API key and preferred model. After setup, all import operations work using the Anthropic service.

**Why this priority**: Existing users may already have Anthropic keys. This story also validates that the provider selection mechanism works end-to-end and provides the foundation for all other provider support.

**Independent Test**: Can be fully tested by running `holmes setup` with Anthropic credentials and then running `holmes import` on a sample document. Success = import completes without errors and produces a KB entry.

**Acceptance Scenarios**:

1. **Given** no prior configuration exists, **When** the user runs `holmes setup` and selects `anthropic`, enters a valid API key and model name, **Then** the configuration is saved and subsequent `holmes import` commands use the Anthropic service.
2. **Given** an Anthropic configuration is saved, **When** the user runs `holmes import doc.md`, **Then** the import completes successfully using the configured Anthropic provider.
3. **Given** an Anthropic configuration with an invalid API key, **When** the user runs `holmes import doc.md`, **Then** the error message explicitly names `anthropic` as the configured provider.

---

### User Story 2 - Configure OpenAI-Compatible Provider (Priority: P1)

A user with an OpenAI, Azure OpenAI, or self-hosted Ollama service wants to use `holmes import`. They run `holmes setup`, specify `openai` as their provider, enter their API key, base URL, and model name. After setup, all import operations — including the interactive tool-use loop — work through their chosen endpoint.

**Why this priority**: This is the primary new capability. Users who previously could not use `holmes import` due to provider lock-in gain full access.

**Independent Test**: Can be fully tested by configuring an OpenAI-compatible provider and running `holmes import` on a sample document. Success = import completes with KB entry written, all tool calls resolved correctly.

**Acceptance Scenarios**:

1. **Given** no prior configuration, **When** the user runs `holmes setup` with provider `openai`, a valid API key, model, and optional base URL, **Then** the configuration is saved with all provided values.
2. **Given** an OpenAI-compatible configuration, **When** the user runs `holmes import doc.md`, **Then** the tool-use loop executes to completion and a KB entry is written.
3. **Given** an Azure OpenAI configuration with a custom base URL, **When** the user runs `holmes import doc.md`, **Then** all LLM calls are directed to the Azure endpoint and import succeeds.
4. **Given** a local Ollama configuration with `api_base_url=http://localhost:11434`, **When** the user runs `holmes import doc.md`, **Then** the import agent communicates with the local endpoint.
5. **Given** an OpenAI-compatible configuration with an invalid API key, **When** the user runs `holmes import doc.md`, **Then** the error message explicitly names `openai` as the configured provider.

---

### User Story 3 - Switch Between Providers (Priority: P2)

A user previously configured one provider and now wants to switch to another. They run `holmes setup` again with different provider details. All subsequent commands use the new provider.

**Why this priority**: Users may have multiple keys or may be evaluating different providers. The reconfiguration path must be simple and reliable.

**Independent Test**: Can be tested by configuring provider A, running a successful import, then reconfiguring to provider B and running another import. Success = second import uses provider B.

**Acceptance Scenarios**:

1. **Given** an existing Anthropic configuration, **When** the user runs `holmes setup` with provider `openai`, **Then** the configuration is updated and the old provider details are replaced.
2. **Given** a newly switched configuration, **When** the user runs `holmes import doc.md`, **Then** the command uses the new provider without requiring any additional steps.

---

### User Story 4 - Provider-Specific Error Guidance (Priority: P2)

When an import fails due to an authentication or connectivity issue, the error message tells the user which provider is configured and what they need to fix.

**Why this priority**: Without provider-specific error context, users cannot distinguish between a wrong key type (e.g., OpenAI key used with `anthropic` provider) and an expired key.

**Independent Test**: Can be tested by deliberately misconfiguring each provider type and running `holmes import`. Success = error output contains the provider name.

**Acceptance Scenarios**:

1. **Given** `provider=anthropic` and an invalid key, **When** the user runs `holmes import doc.md`, **Then** the error output contains the word `anthropic` and instructs the user how to reconfigure.
2. **Given** `provider=openai` and an invalid key, **When** the user runs `holmes import doc.md`, **Then** the error output contains the word `openai` and instructs the user how to reconfigure.
3. **Given** `provider=openai` and an unreachable `api_base_url`, **When** the user runs `holmes import doc.md`, **Then** the error output identifies the unreachable endpoint and mentions the configured provider.

---

### Edge Cases

- What happens when `provider` is not set in the config file? → System falls back to `anthropic` as the default (backward-compatible with existing configurations).
- What happens when `api_base_url` is not set for `openai` provider? → System uses the official OpenAI endpoint as default.
- What happens when the selected model does not support tool/function calling? → Import fails with a clear error identifying that the configured model must support tool calling.
- What happens when the user provides an OpenAI-format key with `provider=anthropic`? → Authentication fails; error message names the provider and hints at checking the key type.
- What happens when the config file is missing or corrupted? → System reports that no provider is configured and instructs the user to run `holmes setup`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to select provider type (`anthropic` or `openai`) when running `holmes setup`.
- **FR-002**: Users MUST be able to specify `model`, `api_key`, and optionally `api_base_url` for either provider type.
- **FR-003**: The system MUST persist the provider type alongside the existing configuration fields.
- **FR-004**: The `holmes import` command MUST use the configured provider for all LLM interactions, including the tool-use loop.
- **FR-005**: The tool-use loop MUST work correctly with both `anthropic` and `openai` provider types (functional parity for tool calling).
- **FR-006**: When no provider is configured, the system MUST default to `anthropic` to preserve backward compatibility with existing configurations.
- **FR-007**: When `api_base_url` is not set for the `openai` provider, the system MUST use the official OpenAI endpoint by default.
- **FR-008**: All authentication and connectivity error messages MUST explicitly identify the configured provider by name.
- **FR-009**: Error messages for configuration problems MUST instruct the user how to reconfigure (e.g., "Run `holmes setup` to update your provider settings").
- **FR-010**: Users MUST be able to re-run `holmes setup` at any time to change provider or update credentials; subsequent imports use the updated configuration.

### Key Entities

- **Provider Configuration**: Represents a user's LLM provider setup. Attributes: provider type (`anthropic` | `openai`), api_key, model name, optional api_base_url. Stored in the existing user config file.
- **Import Session**: An invocation of `holmes import`. Reads the Provider Configuration to establish an LLM connection and execute the full tool-use loop to completion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with an OpenAI-compatible configuration can complete the full import workflow (from `holmes setup` to a written KB entry) with zero provider-related errors.
- **SC-002**: Users who already have an Anthropic configuration experience no change in import behavior after this feature ships — zero regressions in existing functionality.
- **SC-003**: When an authentication error occurs, 100% of error messages include the configured provider name, enabling users to diagnose the issue without consulting documentation.
- **SC-004**: A user can switch providers by running a single `holmes setup` command; the next import uses the new provider without additional steps.
- **SC-005**: The tool-use loop completes the same set of tool calls with an OpenAI-compatible provider as it does with Anthropic for an equivalent import task (functional parity across providers).

## Assumptions

- The existing configuration file format will be extended with a `provider` field; no migration script is required because existing configurations without a `provider` field will default to `anthropic`.
- The `openai` provider type covers all OpenAI-compatible APIs (OpenAI, Azure OpenAI, Ollama, etc.) through a single parameterized code path controlled by `api_base_url`.
- Tool/function calling capability is a prerequisite for using either provider with `holmes import`; models that do not support tool calling are out of scope for this feature.
- The `holmes setup` command is the primary configuration interface; direct editing of the config file is a supported but secondary path.
- Batch import (`--dir`) uses the same provider configuration as single-file import; per-file provider override is out of scope.
- Provider credential validation happens at import time, not at setup time — `holmes setup` does not make a test API call.
