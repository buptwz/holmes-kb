/**
 * TokenUsageBar — displays current/max token usage.
 * Turns yellow/red when approaching context limit.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { TokenUsage } from '../types/index.js';

interface TokenUsageBarProps {
  usage: TokenUsage;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export const TokenUsageBar: React.FC<TokenUsageBarProps> = ({ usage }) => {
  const { used, max, warning } = usage;
  const ratio = max > 0 ? used / max : 0;
  const pct = Math.round(ratio * 100);

  let color = 'gray';
  if (ratio >= 0.9) color = 'red';
  else if (ratio >= 0.8) color = 'yellow';

  return (
    <Box>
      <Text color={color}>
        {formatTokens(used)}/{formatTokens(max)} tokens ({pct}%)
      </Text>
      {warning && (
        <Text color="yellow" bold>
          {' '}
          ⚠ context near limit — /compact to compress
        </Text>
      )}
    </Box>
  );
};
