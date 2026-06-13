/**
 * MessageList — renders the conversation thread with interleaved ToolCallCards.
 * Distinguishes LLM thinking (streaming text) from tool execution cards.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { ToolCallCard } from './ToolCallCard.js';
import type { DisplayMessage } from '../types/index.js';

interface MessageListProps {
  messages: DisplayMessage[];
  streamingText?: string;
}

const ROLE_COLORS: Record<string, string> = {
  user: 'cyan',
  assistant: 'green',
  system: 'gray',
};

const ROLE_LABELS: Record<string, string> = {
  user: 'You',
  assistant: 'Holmes',
  system: 'System',
};

interface FileAttachmentBadgeProps {
  path: string;
  lineStart?: number;
  lineEnd?: number;
  sizeBytes: number;
}

const FileAttachmentBadge: React.FC<FileAttachmentBadgeProps> = ({
  path,
  lineStart,
  lineEnd,
  sizeBytes,
}) => {
  const rangeInfo = lineStart && lineEnd ? ` L${lineStart}-${lineEnd}` : '';
  const sizeInfo = sizeBytes < 1024 ? `${sizeBytes}B` : `${(sizeBytes / 1024).toFixed(1)}KB`;
  return (
    <Box borderStyle="single" borderColor="blue" paddingX={1}>
      <Text color="blue">
        📎 {path}
        {rangeInfo} ({sizeInfo})
      </Text>
    </Box>
  );
};

export const MessageList: React.FC<MessageListProps> = ({ messages, streamingText }) => {
  return (
    <Box flexDirection="column" flexGrow={1} overflowY="hidden">
      {messages.map((msg) => (
        <Box key={msg.id} flexDirection="column" marginBottom={1}>
          {/* Message header */}
          <Box>
            <Text color={ROLE_COLORS[msg.role] ?? 'white'} bold>
              {ROLE_LABELS[msg.role] ?? msg.role}:
            </Text>
            <Text color="gray" dimColor>
              {' '}
              {new Date(msg.timestamp).toLocaleTimeString()}
            </Text>
          </Box>

          {/* File attachments */}
          {msg.attachments?.map((att, i) => (
            <FileAttachmentBadge
              key={i}
              path={att.path}
              lineStart={att.lineStart}
              lineEnd={att.lineEnd}
              sizeBytes={att.sizeBytes}
            />
          ))}

          {/* Message content */}
          {msg.content && (
            <Text wrap="wrap" color={msg.role === 'user' ? 'white' : 'gray'}>
              {msg.content}
            </Text>
          )}

          {/* Tool calls interleaved with the message */}
          {msg.toolCalls?.map((tc) => (
            <ToolCallCard key={tc.id} toolCall={tc} />
          ))}
        </Box>
      ))}

      {/* Streaming text — shown as "thinking" indicator */}
      {streamingText && (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text color="green" bold>
              Holmes:
            </Text>
            <Text color="yellow"> ● thinking</Text>
          </Box>
          <Text color="gray" wrap="wrap">
            {streamingText}
          </Text>
        </Box>
      )}
    </Box>
  );
};
