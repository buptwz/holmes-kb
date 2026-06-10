/**
 * IPC message types for Holmes TUI <-> Agent JSON-RPC 2.0 communication.
 */

// JSON-RPC 2.0 base types
export interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: string | number;
  method: string;
  params?: unknown;
}

export interface JsonRpcResponse {
  jsonrpc: '2.0';
  id: string | number;
  result?: unknown;
  error?: JsonRpcError;
}

export interface JsonRpcNotification {
  jsonrpc: '2.0';
  method: string;
  params?: unknown;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

// Session methods
export interface SessionCreateParams {
  kb_path?: string;
}
export interface SessionCreateResult {
  session_id: string;
  created_at: string;
}

export interface SessionListParams {
  status?: 'active' | 'resolved' | 'abandoned';
  limit?: number;
}
export interface SessionListResult {
  sessions: SessionSummary[];
}

export interface SessionSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionGetParams {
  session_id: string;
}
export interface SessionGetResult {
  session: SessionDetail;
}

export interface SessionDetail extends SessionSummary {
  messages: MessageRecord[];
  tool_calls: ToolCallRecord[];
  kb_entry_id?: string;
}

export interface MessageRecord {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface ToolCallRecord {
  id: string;
  tool_name: string;
  input: Record<string, unknown>;
  output?: string;
  status: 'pending' | 'running' | 'done' | 'denied' | 'error';
  started_at: string;
  ended_at?: string;
}

export interface SessionResolveParams {
  session_id: string;
}
export interface SessionResolveResult {
  kb_entry_id: string;
  summary_preview: string;
}

// Chat methods
export interface ChatSendParams {
  session_id: string;
  message: string;
  attachments?: FileAttachment[];
}

export interface FileAttachment {
  path: string;
  content: string;
  line_start?: number;
  line_end?: number;
  size_bytes: number;
}

// KB methods
export interface KbListParams {
  type?: string;
  category?: string;
  limit?: number;
}
export interface KbListResult {
  entries: KbEntrySummary[];
}

export interface KbEntrySummary {
  id: string;
  type: string;
  title: string;
  maturity: string;
  category?: string;
  tags: string[];
  updated_at: string;
}

export interface KbGetParams {
  entry_id: string;
}
export interface KbGetResult {
  entry: KbEntryDetail;
}

export interface KbEntryDetail extends KbEntrySummary {
  body: string;
}

// Tool confirmation
export interface ToolApproveParams {
  tool_call_id: string;
}
export interface ToolDenyParams {
  tool_call_id: string;
  reason?: string;
}

// Skill
export interface SkillInvokeParams {
  session_id: string;
  skill_name: string;
  args?: string;
}

// Context
export interface ContextCompactParams {
  session_id: string;
}

// Notifications (agent → TUI)
export interface AgentTokenParams {
  session_id: string;
  delta: string;
}

export interface AgentDoneParams {
  session_id: string;
  input_tokens: number;
  output_tokens: number;
  kb_refs?: string[];
}

export interface AgentErrorParams {
  session_id: string;
  error: string;
  code?: string;
}

export interface AgentToolStartParams {
  session_id: string;
  tool_call_id: string;
  tool_name: string;
  input: Record<string, unknown>;
}

export interface AgentToolEndParams {
  session_id: string;
  tool_call_id: string;
  output: string;
  status: 'done' | 'error';
}

export interface AgentToolConfirmParams {
  session_id: string;
  tool_call_id: string;
  tool_name: string;
  description: string;
  input_preview: Record<string, unknown>;
}

export interface ContextUpdateParams {
  session_id: string;
  used_tokens: number;
  max_tokens: number;
  warning?: boolean;
}

export interface McpStatusParams {
  servers: McpServerStatus[];
}

export interface McpServerStatus {
  name: string;
  connected: boolean;
  tool_count: number;
  error?: string;
}
