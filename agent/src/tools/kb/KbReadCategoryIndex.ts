/**
 * KbReadCategoryIndex — Read the _index.md for a specific KB type.
 *
 * Uses isReadOnly: true.
 * Calls `holmes kb read-category <type> --kb-path <path> --json` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbReadCategoryIndex = buildTool({
  name: 'KbReadCategoryIndex',
  description:
    'Read the index table for a specific KB entry type. ' +
    'Returns a Markdown table of all entries in that category with ID, title, maturity, and tags. ' +
    'Use after KbReadOverview to browse entries by type before reading specific entries.',
  isReadOnly: true,
  inputSchema: z.object({
    type: z.enum(['pitfall', 'model', 'guideline', 'process', 'decision']).describe(
      'KB entry type to browse'
    ),
  }),
  async execute({ type }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'read-category', type,
        '--kb-path', kbPath,
        '--json',
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbReadCategoryIndex failed: ${err.message}` })
    }
  },
})
