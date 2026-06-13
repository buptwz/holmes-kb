/**
 * Holmes TUI entry point.
 *
 * Starts the agent subprocess, establishes IPC, creates a session,
 * and renders the REPL screen.
 */

import React, { useEffect, useState } from 'react';
import { render, Box, Text } from 'ink';
import { spawn, type ChildProcess } from 'child_process';
import * as os from 'os';
import * as path from 'path';
import { HolmesIPCClient } from './ipc/HolmesIPCClient.js';
import { REPL } from './screens/REPL.js';
import { SessionList } from './screens/SessionList.js';
import { KnowledgeBrowser } from './screens/KnowledgeBrowser.js';
import type { AppScreen } from './types/index.js';

const AGENT_START_TIMEOUT_MS = 5000;
const SOCKET_PATH = path.join(os.tmpdir(), `holmes-${process.pid}.sock`);

interface AppProps {
  socketPath: string;
}

const App: React.FC<AppProps> = ({ socketPath }) => {
  const [client] = useState(() => new HolmesIPCClient(socketPath));
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [screen, setScreen] = useState<AppScreen>('repl');
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      if (cancelled) return;
      // Retry connecting until socket is ready (agent may still be starting)
      const MAX_RETRIES = 30;
      let lastError: unknown;
      for (let i = 0; i < MAX_RETRIES; i++) {
        try {
          await client.connect();
          const result = await client.sessionCreate();
          if (!cancelled) {
            setSessionId(result.session_id);
            setReady(true);
          }
          return;
        } catch (e) {
          lastError = e;
          client.disconnect();
          await sleep(200);
        }
      }
      if (!cancelled) {
        setError(`Failed to connect to agent: ${lastError}`);
      }
    };
    init();
    return () => {
      cancelled = true;
      client.disconnect();
    };
  }, [client]);

  if (error) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="red" bold>
          Holmes failed to start
        </Text>
        <Text color="gray">{error}</Text>
        <Text color="gray" dimColor>
          Make sure the agent process is running. Try: holmes agent start
        </Text>
      </Box>
    );
  }

  if (!ready || !sessionId) {
    return (
      <Box padding={1}>
        <Text color="yellow">● Starting Holmes agent...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      {screen === 'repl' && (
        <REPL client={client} sessionId={sessionId} onNavigate={setScreen} />
      )}
      {screen === 'session-list' && (
        <SessionList client={client} onNavigate={setScreen} />
      )}
      {screen === 'knowledge-browser' && (
        <KnowledgeBrowser client={client} onNavigate={setScreen} />
      )}
    </Box>
  );
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---- CLI entry ----

const args = process.argv.slice(2);
const socketArg = args.find((a) => a.startsWith('--socket='));
const socketPath = socketArg ? socketArg.split('=')[1] : SOCKET_PATH;

render(<App socketPath={socketPath} />);
