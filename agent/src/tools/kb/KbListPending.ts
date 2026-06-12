/**
 * KbListPending — List all pending KB entries awaiting confirmation.
 *
 * Uses isReadOnly: true.
 * Calls `holmes kb pending --kb-path <path> --json` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbListPending = buildTool({
  name: 'KbListPending',
  description:
    'List all pending KB entries waiting for confirmation. ' +
    'Returns entry IDs, types, titles, and creation dates. ' +
    'Use this to show the user what knowledge is awaiting review.',
  isReadOnly: true,
  inputSchema: z.object({}),
  async execute() {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'pending',
        '--kb-path', kbPath,
        '--json',
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbListPending failed: ${err.message}` })
    }
  },
})
