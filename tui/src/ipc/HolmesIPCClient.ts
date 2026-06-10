/**
 * Holmes IPC client — JSON-RPC 2.0 over Unix domain socket.
 *
 * Connects to the agent process and handles all request/response cycles
 * plus incoming notification callbacks.
 */

import * as net from 'net';
import type {
  AgentDoneParams,
  AgentErrorParams,
  AgentTokenParams,
  AgentToolConfirmParams,
  AgentToolEndParams,
  AgentToolStartParams,
  ContextUpdateParams,
  JsonRpcError,
  McpStatusParams,
  SessionCreateResult,
  SessionListResult,
  SessionGetResult,
  SessionResolveResult,
  ChatSendParams,
  KbListResult,
  KbGetResult,
  FileAttachment,
} from './types.js';

type NotificationHandlers = {
  'agent/token'?: (params: AgentTokenParams) => void;
  'agent/done'?: (params: AgentDoneParams) => void;
  'agent/error'?: (params: AgentErrorParams) => void;
  'agent/tool_start'?: (params: AgentToolStartParams) => void;
  'agent/tool_end'?: (params: AgentToolEndParams) => void;
  'agent/tool_confirm'?: (params: AgentToolConfirmParams) => void;
  'context/update'?: (params: ContextUpdateParams) => void;
  'mcp/status'?: (params: McpStatusParams) => void;
};

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: JsonRpcError) => void;
}

export class HolmesIPCClient {
  private socket: net.Socket | null = null;
  private buffer = '';
  private nextId = 1;
  private pending = new Map<number | string, PendingRequest>();
  private handlers: NotificationHandlers = {};
  private connected = false;

  constructor(private readonly socketPath: string) {}

  /**
   * Connect to the agent's Unix domain socket.
   */
  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new net.Socket();
      socket.connect(this.socketPath, () => {
        this.connected = true;
        resolve();
      });
      socket.on('data', (data) => this.onData(data.toString()));
      socket.on('error', (err) => {
        if (!this.connected) {
          reject(err);
        }
        // Reject all pending requests
        for (const [, pending] of this.pending) {
          pending.reject({ code: -32000, message: err.message });
        }
        this.pending.clear();
      });
      socket.on('close', () => {
        this.connected = false;
      });
      this.socket = socket;
    });
  }

  /** Disconnect from the agent. */
  disconnect(): void {
    this.socket?.destroy();
    this.socket = null;
    this.connected = false;
  }

  /** Register notification handlers. */
  on(handlers: NotificationHandlers): void {
    Object.assign(this.handlers, handlers);
  }

  /** Create a new session. */
  async sessionCreate(kbPath?: string): Promise<SessionCreateResult> {
    return this.call('session.create', kbPath ? { kb_path: kbPath } : {});
  }

  /** List sessions. */
  async sessionList(status?: string, limit?: number): Promise<SessionListResult> {
    return this.call('session.list', { status, limit });
  }

  /** Get a session by ID. */
  async sessionGet(sessionId: string): Promise<SessionGetResult> {
    return this.call('session.get', { session_id: sessionId });
  }

  /** Resolve a session and trigger knowledge extraction. */
  async sessionResolve(sessionId: string): Promise<SessionResolveResult> {
    return this.call('session.resolve', { session_id: sessionId });
  }

  /**
   * Send a chat message. Responses come as notifications (agent/token, agent/done, etc.).
   * This call returns as soon as the agent begins processing.
   */
  async chatSend(
    sessionId: string,
    message: string,
    attachments?: FileAttachment[],
  ): Promise<void> {
    const params: ChatSendParams = { session_id: sessionId, message };
    if (attachments?.length) {
      params.attachments = attachments;
    }
    await this.call('chat.send', params);
  }

  /** List KB entries. */
  async kbList(type?: string, limit?: number): Promise<KbListResult> {
    return this.call('kb.list', { type, limit });
  }

  /** Get a KB entry by ID. */
  async kbGet(entryId: string): Promise<KbGetResult> {
    return this.call('kb.get', { entry_id: entryId });
  }

  /** Approve a pending tool confirmation. */
  async toolApprove(toolCallId: string): Promise<void> {
    await this.call('tool.approve', { tool_call_id: toolCallId });
  }

  /** Deny a pending tool confirmation. */
  async toolDeny(toolCallId: string, reason?: string): Promise<void> {
    await this.call('tool.deny', { tool_call_id: toolCallId, reason });
  }

  /** Invoke a skill. */
  async skillInvoke(sessionId: string, skillName: string, args?: string): Promise<void> {
    await this.call('skill.invoke', { session_id: sessionId, skill_name: skillName, args });
  }

  /** Compact the context. */
  async contextCompact(sessionId: string): Promise<void> {
    await this.call('context.compact', { session_id: sessionId });
  }

  /** Save a memory note. */
  async remember(content: string): Promise<void> {
    await this.call('/remember', { content });
  }

  private call<T>(method: string, params: unknown = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.socket || !this.connected) {
        reject({ code: -32000, message: 'Not connected' });
        return;
      }
      const id = this.nextId++;
      const request = {
        jsonrpc: '2.0',
        id,
        method,
        params,
      };
      this.pending.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
      });
      const line = JSON.stringify(request) + '\n';
      this.socket.write(line);
    });
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    const lines = this.buffer.split('\n');
    this.buffer = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const msg = JSON.parse(trimmed);
        this.handleMessage(msg);
      } catch {
        // ignore malformed JSON
      }
    }
  }

  private handleMessage(msg: Record<string, unknown>): void {
    if ('id' in msg) {
      // Response to a request
      const id = msg['id'] as number | string;
      const pending = this.pending.get(id);
      if (!pending) return;
      this.pending.delete(id);
      if ('error' in msg) {
        pending.reject(msg['error'] as JsonRpcError);
      } else {
        pending.resolve(msg['result']);
      }
    } else if ('method' in msg) {
      // Notification
      const method = msg['method'] as string;
      const params = msg['params'];
      const handler = this.handlers[method as keyof NotificationHandlers];
      if (handler) {
        (handler as (p: unknown) => void)(params);
      }
    }
  }
}
