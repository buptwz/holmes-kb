/**
 * KnowledgeBrowser — browse KB entries. Ctrl+K from REPL to open.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import type { HolmesIPCClient } from '../ipc/HolmesIPCClient.js';
import type { AppScreen, KbEntry } from '../types/index.js';

const MATURITY_COLORS: Record<string, string> = {
  draft: 'gray',
  verified: 'yellow',
  proven: 'green',
};

interface KbEntryItemProps {
  entry: KbEntry;
  selected: boolean;
}

const KbEntryItem: React.FC<KbEntryItemProps> = ({ entry, selected }) => {
  const matColor = MATURITY_COLORS[entry.maturity] ?? 'white';
  const tagStr = entry.tags.slice(0, 3).join(', ');
  return (
    <Box paddingX={1}>
      <Text color={selected ? 'cyan' : 'white'} bold={selected}>
        {selected ? '▶ ' : '  '}
      </Text>
      <Text color="gray">{entry.id} </Text>
      <Text color={matColor}>[{entry.maturity}] </Text>
      <Text color={selected ? 'cyan' : 'white'}>{entry.title.slice(0, 45)}</Text>
      {tagStr && (
        <Text color="gray" dimColor>
          {' '}
          {tagStr}
        </Text>
      )}
    </Box>
  );
};

interface KnowledgeBrowserProps {
  client: HolmesIPCClient;
  onNavigate: (screen: AppScreen) => void;
}

export const KnowledgeBrowser: React.FC<KnowledgeBrowserProps> = ({ client, onNavigate }) => {
  const [entries, setEntries] = useState<KbEntry[]>([]);
  const [selected, setSelected] = useState(0);
  const [detail, setDetail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const result = await client.kbList(undefined, 100);
        setEntries(result.entries as KbEntry[]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [client]);

  useInput(async (input, key) => {
    if (detail) {
      if (key.escape || input === 'q') setDetail(null);
      return;
    }
    if (key.escape) {
      onNavigate('repl');
    } else if (key.upArrow) {
      setSelected((s) => Math.max(0, s - 1));
    } else if (key.downArrow) {
      setSelected((s) => Math.min(entries.length - 1, s + 1));
    } else if (key.return) {
      const entry = entries[selected];
      if (entry) {
        const result = await client.kbGet(entry.id);
        setDetail(`${result.entry.title}\n\n${(result.entry as any).body ?? ''}`);
      }
    }
  });

  if (loading) {
    return (
      <Box padding={1}>
        <Text color="yellow">Loading knowledge base...</Text>
      </Box>
    );
  }

  if (detail) {
    return (
      <Box flexDirection="column" height="100%">
        <Box paddingX={1} paddingY={1} borderStyle="single" borderColor="green">
          <Text bold color="green">
            Entry Detail
          </Text>
          <Text color="gray" dimColor>
            {' '}
            — Esc/q to return
          </Text>
        </Box>
        <Box flexGrow={1} paddingX={1} overflowY="hidden">
          <Text wrap="wrap">{detail}</Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      <Box paddingX={1} paddingY={1} borderStyle="single" borderColor="green">
        <Text bold color="green">
          Knowledge Browser
        </Text>
        <Text color="gray" dimColor>
          {' '}
          — Esc: back, ↑↓: navigate, Enter: view
        </Text>
      </Box>
      <Box flexDirection="column" flexGrow={1}>
        {entries.length === 0 ? (
          <Box padding={1}>
            <Text color="gray">No knowledge entries found. Import some with: holmes import</Text>
          </Box>
        ) : (
          entries.map((e, i) => <KbEntryItem key={e.id} entry={e} selected={i === selected} />)
        )}
      </Box>
    </Box>
  );
};
