/**
 * ToolCallCard — displays a tool call with status indicator, input summary,
 * and collapsible full input/output detail.
 *
 * Used for both regular tools and bash command execution (US7, US13).
 */

import React, { useState } from 'react';
import { Box, Text } from 'ink';
import type { ToolCallDisplay } from '../types/index.js';

interface ToolCallCardProps {
  toolCall: ToolCallDisplay;
}

const STATUS_ICONS: Record<string, string> = {
  pending: '○',
  running: '◐',
  done: '●',
  denied: '✗',
  error: '!',
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'gray',
  running: 'yellow',
  done: 'green',
  denied: 'red',
  error: 'red',
};

function formatInputPreview(input: Record<string, unknown>): string {
  const entries = Object.entries(input);
  if (entries.length === 0) return '(no input)';
  const preview = entries
    .slice(0, 3)
    .map(([k, v]) => {
      const val = typeof v === 'string' ? v.slice(0, 40) : JSON.stringify(v).slice(0, 40);
      return `${k}: ${val}`;
    })
    .join(', ');
  return entries.length > 3 ? `${preview}, ...` : preview;
}

function formatOutput(output: string, toolName: string): string {
  const MAX_LINES = 20;
  const lines = output.split('\n');
  if (lines.length <= MAX_LINES) return output;
  return lines.slice(0, MAX_LINES).join('\n') + `\n... (${lines.length - MAX_LINES} more lines)`;
}

export const ToolCallCard: React.FC<ToolCallCardProps> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);
  const { toolName, status, input, output } = toolCall;

  const icon = STATUS_ICONS[status] ?? '?';
  const color = STATUS_COLORS[status] ?? 'white';
  const isBash = toolName === 'bash_execute';

  return (
    <Box flexDirection="column" borderStyle="single" borderColor={color} paddingX={1} marginY={0}>
      <Box>
        <Text color={color}>{icon} </Text>
        <Text bold>{toolName}</Text>
        <Text color="gray"> — {formatInputPreview(input)}</Text>
        {!expanded && (
          <Text color="gray" dimColor>
            {' '}
            (Tab to expand)
          </Text>
        )}
      </Box>

      {expanded && (
        <Box flexDirection="column" marginTop={1}>
          <Text color="cyan" bold>
            Input:
          </Text>
          <Text color="gray">{JSON.stringify(input, null, 2)}</Text>

          {output !== undefined && (
            <Box flexDirection="column" marginTop={1}>
              <Text color="cyan" bold>
                {isBash ? 'Output:' : 'Result:'}
              </Text>
              {status === 'error' ? (
                <Text color="red">{formatOutput(output, toolName)}</Text>
              ) : status === 'denied' ? (
                <Text color="yellow">{output}</Text>
              ) : (
                <Text color="white">{formatOutput(output, toolName)}</Text>
              )}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
};
