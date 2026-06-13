/**
 * StatusBar — bottom bar showing connection status, session state,
 * token usage, MCP status, and keyboard shortcuts.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { TokenUsageBar } from './TokenUsageBar.js';
import type { TokenUsage, AppScreen } from '../types/index.js';
import type { McpServerStatus } from '../ipc/types.js';

interface StatusBarProps {
  connected: boolean;
  sessionId: string | null;
  screen: AppScreen;
  isStreaming: boolean;
  tokenUsage: TokenUsage | null;
  mcpServers: McpServerStatus[];
}

export const StatusBar: React.FC<StatusBarProps> = ({
  connected,
  sessionId,
  screen,
  isStreaming,
  tokenUsage,
  mcpServers,
}) => {
  const connColor = connected ? 'green' : 'red';
  const connLabel = connected ? '⬤ connected' : '⬤ disconnected';

  const connectedMcp = mcpServers.filter((s) => s.connected);
  const mcpLabel =
    connectedMcp.length > 0 ? `MCP: ${connectedMcp.length} server(s)` : null;

  const shortcuts =
    screen === 'repl'
      ? 'Ctrl+H: history  Ctrl+K: KB  Ctrl+R: resolve  Esc: cancel'
      : screen === 'session-list'
        ? 'Esc: back  Enter: open'
        : 'Esc: back  Enter: view';

  return (
    <Box
      flexDirection="row"
      justifyContent="space-between"
      borderStyle="single"
      borderColor="gray"
      paddingX={1}
    >
      <Box gap={2}>
        <Text color={connColor}>{connLabel}</Text>
        {sessionId && <Text color="gray">#{sessionId.slice(0, 8)}</Text>}
        {isStreaming && <Text color="yellow">● thinking...</Text>}
        {mcpLabel && <Text color="blue">{mcpLabel}</Text>}
      </Box>
      <Box gap={2}>
        {tokenUsage && <TokenUsageBar usage={tokenUsage} />}
        <Text color="gray" dimColor>
          {shortcuts}
        </Text>
      </Box>
    </Box>
  );
};
