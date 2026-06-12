/**
 * KbReadOverview — Read the KB overview (README + index summary).
 *
 * Uses isReadOnly: true. No parameters required.
 * Calls `holmes kb overview --kb-path <path> --json` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbReadOverview = buildTool({
  name: 'KbReadOverview',
  description:
    'Read the knowledge base overview: README content and index summary. ' +
    'Always call this first at the start of a troubleshooting session to understand ' +
    'what knowledge is available before searching.',
  isReadOnly: true,
  inputSchema: z.object({}),
  async execute() {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'overview',
        '--kb-path', kbPath,
        '--json',
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbReadOverview failed: ${err.message}` })
    }
  },
})
