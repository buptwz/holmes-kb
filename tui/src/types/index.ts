/**
 * Shared TUI types for Holmes.
 */

import type { KbEntrySummary, ToolCallRecord, MessageRecord, McpServerStatus } from '../ipc/types.js';

// Screen navigation
export type AppScreen = 'repl' | 'session-list' | 'knowledge-browser';

// Session
export interface Session {
  id: string;
  title: string;
  status: 'active' | 'resolved' | 'abandoned';
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

// Message as displayed in TUI
export type MessageRole = 'user' | 'assistant' | 'system';

export interface DisplayMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  toolCalls?: ToolCallDisplay[];
  attachments?: FileAttachmentDisplay[];
}

export interface ToolCallDisplay {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output?: string;
  status: 'pending' | 'running' | 'done' | 'denied' | 'error';
  startedAt: string;
  endedAt?: string;
}

export interface FileAttachmentDisplay {
  path: string;
  lineStart?: number;
  lineEnd?: number;
  sizeBytes: number;
}

// KB entry in browser
export type KbEntry = KbEntrySummary;

// Confirmation dialog state
export interface ConfirmState {
  toolCallId: string;
  toolName: string;
  description: string;
  inputPreview: Record<string, unknown>;
}

// Token usage
export interface TokenUsage {
  used: number;
  max: number;
  warning: boolean;
}

// App state
export interface AppState {
  screen: AppScreen;
  sessionId: string | null;
  messages: DisplayMessage[];
  tokenUsage: TokenUsage | null;
  confirmState: ConfirmState | null;
  mcpServers: McpServerStatus[];
  isStreaming: boolean;
  inputValue: string;
}
