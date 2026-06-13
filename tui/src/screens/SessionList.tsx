/**
 * SessionList — browse past sessions. Ctrl+H from REPL to open.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import type { HolmesIPCClient } from '../ipc/HolmesIPCClient.js';
import type { AppScreen, Session } from '../types/index.js';

interface SessionItemProps {
  session: Session;
  selected: boolean;
}

const SessionItem: React.FC<SessionItemProps> = ({ session, selected }) => {
  const date = new Date(session.updatedAt).toLocaleString();
  const statusColor =
    session.status === 'resolved' ? 'green' : session.status === 'active' ? 'yellow' : 'gray';
  return (
    <Box paddingX={1}>
      <Text color={selected ? 'cyan' : 'white'} bold={selected}>
        {selected ? '▶ ' : '  '}
      </Text>
      <Text color={statusColor}>[{session.status}] </Text>
      <Text color={selected ? 'cyan' : 'white'}>{session.title.slice(0, 50)}</Text>
      <Text color="gray" dimColor>
        {' '}
        {date} ({session.messageCount} msgs)
      </Text>
    </Box>
  );
};

interface SessionListProps {
  client: HolmesIPCClient;
  onNavigate: (screen: AppScreen) => void;
}

export const SessionList: React.FC<SessionListProps> = ({ client, onNavigate }) => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const result = await client.sessionList();
        setSessions(
          result.sessions.map((s) => ({
            id: s.id,
            title: s.title,
            status: s.status as Session['status'],
            createdAt: s.created_at,
            updatedAt: s.updated_at,
            messageCount: s.message_count,
          })),
        );
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [client]);

  useInput((input, key) => {
    if (key.escape) {
      onNavigate('repl');
    } else if (key.upArrow) {
      setSelected((s) => Math.max(0, s - 1));
    } else if (key.downArrow) {
      setSelected((s) => Math.min(sessions.length - 1, s + 1));
    }
  });

  if (loading) {
    return (
      <Box padding={1}>
        <Text color="yellow">Loading sessions...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      <Box paddingX={1} paddingY={1} borderStyle="single" borderColor="cyan">
        <Text bold color="cyan">
          Session History
        </Text>
        <Text color="gray" dimColor>
          {' '}
          — Esc to return
        </Text>
      </Box>
      <Box flexDirection="column" flexGrow={1}>
        {sessions.length === 0 ? (
          <Box padding={1}>
            <Text color="gray">No sessions found.</Text>
          </Box>
        ) : (
          sessions.map((s, i) => <SessionItem key={s.id} session={s} selected={i === selected} />)
        )}
      </Box>
    </Box>
  );
};
