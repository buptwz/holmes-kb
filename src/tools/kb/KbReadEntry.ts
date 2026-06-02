/**
 * KbReadEntry — Read the full content of a specific KB entry by ID.
 *
 * Uses isReadOnly: true.
 * Calls `holmes kb show <id> --kb-path <path>` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbReadEntry = buildTool({
  name: 'KbReadEntry',
  description:
    'Read the complete Markdown content of a KB entry by its ID (e.g. PT-DB-001). ' +
    'Returns the full entry including frontmatter, symptoms, root cause, and resolution. ' +
    'Use this after identifying a promising entry from KbSearch or KbReadCategoryIndex.',
  isReadOnly: true,
  inputSchema: z.object({
    entry_id: z.string().describe('KB entry ID (e.g. PT-DB-001, MD-SVC-003)'),
  }),
  async execute({ entry_id }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'show', entry_id,
        '--kb-path', kbPath,
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbReadEntry failed: ${err.message}` })
    }
  },
})
