/**
 * KbWriteEntry — Write a complete KB entry (with frontmatter) directly to pending.
 *
 * Uses isReadOnly: false — triggers Holmes Agent permission confirmation before writing.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbWriteEntry = buildTool({
  name: 'KbWriteEntry',
  description:
    'Write a fully-formed KB entry (Markdown with YAML frontmatter) to the pending area. ' +
    'Use this when you have a complete, well-structured entry ready for review. ' +
    'Returns the pending_id for use with `holmes kb confirm`.',
  isReadOnly: false,
  inputSchema: z.object({
    content: z.string().describe(
      'Complete Markdown document with YAML frontmatter (id, type, title, maturity, ' +
      'category, tags, created_at, updated_at) and the appropriate body sections.'
    ),
  }),
  async execute({ content }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }
    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'write-pending',
        '--content', content,
        '--kb-path', kbPath,
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbWriteEntry failed: ${err.message}` })
    }
  },
})
