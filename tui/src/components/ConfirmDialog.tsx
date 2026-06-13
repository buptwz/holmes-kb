/**
 * ConfirmDialog — shown when the agent requests execution of a tool that
 * requires user confirmation (writes, bash commands, etc.).
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import type { ConfirmState } from '../types/index.js';

interface ConfirmDialogProps {
  state: ConfirmState;
  onApprove: () => void;
  onDeny: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({ state, onApprove, onDeny }) => {
  useInput((input, key) => {
    if (input === 'y' || input === 'Y') {
      onApprove();
    } else if (input === 'n' || input === 'N' || key.escape) {
      onDeny();
    }
  });

  const previewStr = JSON.stringify(state.inputPreview, null, 2);

  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor="yellow"
      paddingX={2}
      paddingY={1}
      marginY={1}
    >
      <Text color="yellow" bold>
        ⚠ Tool Execution Confirmation
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Box>
          <Text color="white" bold>
            Tool:{' '}
          </Text>
          <Text color="cyan">{state.toolName}</Text>
        </Box>
        <Box marginTop={1}>
          <Text color="white" bold>
            Description:{' '}
          </Text>
          <Text color="gray">{state.description}</Text>
        </Box>
        {Object.keys(state.inputPreview).length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text color="white" bold>
              Preview:
            </Text>
            <Text color="gray">{previewStr}</Text>
          </Box>
        )}
      </Box>
      <Box marginTop={1}>
        <Text color="green" bold>
          [y]{' '}
        </Text>
        <Text>Allow   </Text>
        <Text color="red" bold>
          [n/Esc]{' '}
        </Text>
        <Text>Deny</Text>
      </Box>
    </Box>
  );
};
