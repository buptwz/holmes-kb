/**
 * KbSearch — Full-text search across KB entries.
 *
 * Uses isReadOnly: true.
 * Calls `holmes kb search <query> --kb-path <path> --limit <n> --json` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbSearch = buildTool({
  name: 'KbSearch',
  description:
    'Search the knowledge base by keywords. Returns a ranked list of matching entries ' +
    'with their IDs, titles, types, and short snippets. ' +
    'Use this after KbReadOverview to find relevant troubleshooting entries.',
  isReadOnly: true,
  inputSchema: z.object({
    query: z.string().describe('Search keywords or short phrase describing the issue'),
    limit: z.number().optional().describe('Maximum number of results (default: 5)'),
  }),
  async execute({ query, limit = 5 }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'search', query,
        '--kb-path', kbPath,
        '--limit', String(limit),
        '--json',
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbSearch failed: ${err.message}` })
    }
  },
})
