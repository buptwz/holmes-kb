/**
 * REPL — main chat interface.
 *
 * Features:
 * - Multi-line message input with Enter to send
 * - Real-time streaming token display
 * - ToolCallCard rendering for all tool events
 * - ConfirmDialog for requires_confirmation tools
 * - @ file injection
 * - /remember, /compact slash commands
 * - Ctrl+H: session history, Ctrl+K: KB browser, Ctrl+R: resolve session
 * - Esc: cancel streaming
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import TextInput from 'ink-text-input';
import * as fs from 'fs';
import * as path from 'path';
import { MessageList } from '../components/MessageList.js';
import { StatusBar } from '../components/StatusBar.js';
import { ConfirmDialog } from '../components/ConfirmDialog.js';
import type { HolmesIPCClient } from '../ipc/HolmesIPCClient.js';
import type {
  DisplayMessage,
  ToolCallDisplay,
  ConfirmState,
  TokenUsage,
  AppScreen,
  FileAttachmentDisplay,
} from '../types/index.js';
import type {
  AgentDoneParams,
  AgentErrorParams,
  AgentTokenParams,
  AgentToolConfirmParams,
  AgentToolEndParams,
  AgentToolStartParams,
  ContextUpdateParams,
  FileAttachment,
  McpServerStatus,
} from '../ipc/types.js';

let _msgCounter = 0;
const newMsgId = () => `msg-${++_msgCounter}`;

interface REPLProps {
  client: HolmesIPCClient;
  sessionId: string;
  onNavigate: (screen: AppScreen) => void;
}

export const REPL: React.FC<REPLProps> = ({ client, sessionId, onNavigate }) => {
  const { exit } = useApp();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [streamingText, setStreamingText] = useState('');
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenUsage | null>(null);
  const [mcpServers, setMcpServers] = useState<McpServerStatus[]>([]);
  // Current tool calls being built (tool_call_id -> ToolCallDisplay)
  const activeToolCalls = useRef<Map<string, ToolCallDisplay>>(new Map());
  // Pending file attachments for next message
  const [pendingAttachments, setPendingAttachments] = useState<FileAttachmentDisplay[]>([]);

  useEffect(() => {
    client.on({
      'agent/token': (params: AgentTokenParams) => {
        setStreamingText((prev) => prev + params.delta);
      },
      'agent/tool_start': (params: AgentToolStartParams) => {
        const tc: ToolCallDisplay = {
          id: params.tool_call_id,
          toolName: params.tool_name,
          input: params.input,
          status: 'running',
          startedAt: new Date().toISOString(),
        };
        activeToolCalls.current.set(params.tool_call_id, tc);
        // Add a transient "assistant" message to show the tool running
        setMessages((prev) => addToolCallToThread(prev, tc));
      },
      'agent/tool_end': (params: AgentToolEndParams) => {
        const tc = activeToolCalls.current.get(params.tool_call_id);
        if (tc) {
          const updated: ToolCallDisplay = {
            ...tc,
            output: params.output,
            status: params.status as ToolCallDisplay['status'],
            endedAt: new Date().toISOString(),
          };
          activeToolCalls.current.set(params.tool_call_id, updated);
          setMessages((prev) => updateToolCallInThread(prev, updated));
        }
      },
      'agent/tool_confirm': (params: AgentToolConfirmParams) => {
        setConfirmState({
          toolCallId: params.tool_call_id,
          toolName: params.tool_name,
          description: params.description,
          inputPreview: params.input_preview,
        });
      },
      'agent/done': (params: AgentDoneParams) => {
        // Flush streaming text as assistant message
        setStreamingText((prev) => {
          if (prev.trim()) {
            const msg: DisplayMessage = {
              id: newMsgId(),
              role: 'assistant',
              content: prev,
              timestamp: new Date().toISOString(),
            };
            setMessages((m) => [...m, msg]);
          }
          return '';
        });
        setIsStreaming(false);
        activeToolCalls.current.clear();
      },
      'agent/error': (params: AgentErrorParams) => {
        const msg: DisplayMessage = {
          id: newMsgId(),
          role: 'system',
          content: `Error: ${params.error}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, msg]);
        setStreamingText('');
        setIsStreaming(false);
      },
      'context/update': (params: ContextUpdateParams) => {
        setTokenUsage({
          used: params.used_tokens,
          max: params.max_tokens,
          warning: params.warning ?? false,
        });
      },
      'mcp/status': (params) => {
        setMcpServers((params as { servers: McpServerStatus[] }).servers);
      },
    });
  }, [client]);

  useInput((input, key) => {
    if (isStreaming) {
      if (key.escape) {
        // Cancel not yet implemented — show hint
      }
      return;
    }
    if (confirmState) return;

    if (key.ctrl && input === 'h') {
      onNavigate('session-list');
    } else if (key.ctrl && input === 'k') {
      onNavigate('knowledge-browser');
    } else if (key.ctrl && input === 'r') {
      handleResolve();
    } else if (key.ctrl && input === 'c') {
      exit();
    }
  });

  const handleResolve = useCallback(async () => {
    try {
      const result = await client.sessionResolve(sessionId);
      const msg: DisplayMessage = {
        id: newMsgId(),
        role: 'system',
        content: `Session resolved. Knowledge entry: ${result.kb_entry_id || 'pending confirmation'}\n\nPreview: ${result.summary_preview}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, msg]);
    } catch (e) {
      const msg: DisplayMessage = {
        id: newMsgId(),
        role: 'system',
        content: `Resolve failed: ${e}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, msg]);
    }
  }, [client, sessionId]);

  const handleSubmit = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) return;
      setInputValue('');

      // Handle slash commands
      if (trimmed.startsWith('/compact')) {
        await client.contextCompact(sessionId);
        return;
      }
      if (trimmed.startsWith('/remember ')) {
        const content = trimmed.slice('/remember '.length);
        await client.remember(content);
        const msg: DisplayMessage = {
          id: newMsgId(),
          role: 'system',
          content: `Saved to memory: "${content}"`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, msg]);
        return;
      }
      if (trimmed === '/') {
        // Show skill list — not yet implemented
        return;
      }
      if (trimmed.startsWith('/') && !trimmed.startsWith('//')) {
        const skillName = trimmed.slice(1).split(' ')[0];
        const args = trimmed.slice(1 + skillName.length).trim();
        await client.skillInvoke(sessionId, skillName, args);
        return;
      }

      // Parse @ file injections
      const { cleanedMessage, attachments, displayAttachments } = await parseAtMentions(trimmed);

      // Show user message immediately
      const userMsg: DisplayMessage = {
        id: newMsgId(),
        role: 'user',
        content: cleanedMessage,
        timestamp: new Date().toISOString(),
        attachments: displayAttachments,
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);

      try {
        await client.chatSend(
          sessionId,
          cleanedMessage,
          attachments.length > 0 ? attachments : undefined,
        );
      } catch (e) {
        const errMsg: DisplayMessage = {
          id: newMsgId(),
          role: 'system',
          content: `Send failed: ${e}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errMsg]);
        setIsStreaming(false);
      }
    },
    [client, sessionId],
  );

  const handleApprove = useCallback(async () => {
    if (!confirmState) return;
    await client.toolApprove(confirmState.toolCallId);
    setConfirmState(null);
  }, [client, confirmState]);

  const handleDeny = useCallback(async () => {
    if (!confirmState) return;
    await client.toolDeny(confirmState.toolCallId, 'User denied');
    setConfirmState(null);
  }, [client, confirmState]);

  return (
    <Box flexDirection="column" height="100%">
      {/* Message thread */}
      <Box flexGrow={1} flexDirection="column" paddingX={1} overflowY="hidden">
        <MessageList messages={messages} streamingText={streamingText} />
      </Box>

      {/* Confirmation dialog */}
      {confirmState && (
        <Box paddingX={1}>
          <ConfirmDialog state={confirmState} onApprove={handleApprove} onDeny={handleDeny} />
        </Box>
      )}

      {/* Input area */}
      {!isStreaming && !confirmState && (
        <Box paddingX={1} borderStyle="single" borderColor="gray">
          <Text color="cyan">› </Text>
          <TextInput
            value={inputValue}
            onChange={setInputValue}
            onSubmit={handleSubmit}
            placeholder="Ask Holmes a question... (@ to inject file)"
          />
        </Box>
      )}

      {/* Status bar */}
      <StatusBar
        connected={true}
        sessionId={sessionId}
        screen="repl"
        isStreaming={isStreaming}
        tokenUsage={tokenUsage}
        mcpServers={mcpServers}
      />
    </Box>
  );
};

// ---- Helpers ----

function addToolCallToThread(
  messages: DisplayMessage[],
  tc: ToolCallDisplay,
): DisplayMessage[] {
  // Attach to last assistant message or create a new transient one
  const lastMsg = messages[messages.length - 1];
  if (lastMsg && lastMsg.role === 'assistant') {
    return messages.map((m, i) =>
      i === messages.length - 1
        ? { ...m, toolCalls: [...(m.toolCalls ?? []), tc] }
        : m,
    );
  }
  const agentMsg: DisplayMessage = {
    id: newMsgId(),
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    toolCalls: [tc],
  };
  return [...messages, agentMsg];
}

function updateToolCallInThread(
  messages: DisplayMessage[],
  tc: ToolCallDisplay,
): DisplayMessage[] {
  return messages.map((m) => {
    if (!m.toolCalls) return m;
    const idx = m.toolCalls.findIndex((t) => t.id === tc.id);
    if (idx === -1) return m;
    const newToolCalls = [...m.toolCalls];
    newToolCalls[idx] = tc;
    return { ...m, toolCalls: newToolCalls };
  });
}

const FILE_INJECT_LIMIT_BYTES = 1024 * 1024; // 1MB
const FILE_INJECT_LIMIT_LINES = 500;

async function parseAtMentions(message: string): Promise<{
  cleanedMessage: string;
  attachments: FileAttachment[];
  displayAttachments: FileAttachmentDisplay[];
}> {
  const attachments: FileAttachment[] = [];
  const displayAttachments: FileAttachmentDisplay[] = [];
  const atRegex = /@([\S]+)/g;
  let cleaned = message;

  let match;
  while ((match = atRegex.exec(message)) !== null) {
    const rawPath = match[1];
    const absPath = path.resolve(rawPath);
    try {
      const stat = fs.statSync(absPath);
      if (!stat.isFile()) continue;
      const sizeBytes = stat.size;
      const content = fs.readFileSync(absPath, 'utf8');
      const lines = content.split('\n');
      let finalContent = content;
      let lineStart: number | undefined;
      let lineEnd: number | undefined;

      if (sizeBytes > FILE_INJECT_LIMIT_BYTES || lines.length > FILE_INJECT_LIMIT_LINES) {
        // Inject last 500 lines by default for large files
        lineStart = Math.max(1, lines.length - FILE_INJECT_LIMIT_LINES + 1);
        lineEnd = lines.length;
        finalContent = lines.slice(lineStart - 1).join('\n');
      }

      attachments.push({
        path: absPath,
        content: finalContent,
        line_start: lineStart,
        line_end: lineEnd,
        size_bytes: sizeBytes,
      });
      displayAttachments.push({
        path: absPath,
        lineStart,
        lineEnd,
        sizeBytes,
      });
      cleaned = cleaned.replace(match[0], `[attached: ${path.basename(absPath)}]`);
    } catch {
      // File not found or unreadable — leave @ mention as-is
    }
  }

  return { cleanedMessage: cleaned, attachments, displayAttachments };
}
