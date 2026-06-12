/**
 * KbExtractAndSave — Extract troubleshooting knowledge from conversation and save to pending.
 *
 * Uses isReadOnly: false — triggers Holmes Agent permission confirmation before writing.
 * Calls `holmes kb write-pending --content <str> --kb-path <path>` via subprocess.
 */

import { execFile } from 'child_process'
import { promisify } from 'util'
import { buildTool } from '../../utils/buildTool.js'
import { z } from 'zod'

const execFileAsync = promisify(execFile)

export const KbExtractAndSave = buildTool({
  name: 'KbExtractAndSave',
  description:
    'Extract troubleshooting experience from the current session and save it to ' +
    'the KB pending area for review. Use this when the user confirms an issue is resolved. ' +
    'Provide a structured summary with Symptoms, Root Cause, and Resolution.',
  isReadOnly: false,
  inputSchema: z.object({
    summary: z.string().describe(
      'Structured Markdown with YAML frontmatter. Must include: type, title, category, ' +
      'tags, and body sections (## Symptoms, ## Root Cause, ## Resolution).'
    ),
    type: z.enum(['pitfall', 'model', 'guideline', 'process', 'decision']).optional().describe(
      'KB entry type (default: pitfall)'
    ),
    category: z.string().optional().describe(
      'Pitfall subcategory: network|system|application|database'
    ),
  }),
  async execute({ summary, type = 'pitfall', category }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    if (!kbPath) {
      return JSON.stringify({ error: 'HOLMES_KB_PATH not set. Run: holmes setup --kb-path <path>' })
    }

    // Build minimal frontmatter if summary doesn't already contain it.
    let content = summary
    if (!content.startsWith('---')) {
      const catLine = category ? `category: ${category}` : ''
      content = [
        '---',
        `type: ${type}`,
        'title: (auto-extracted)',
        'maturity: draft',
        catLine,
        'tags: []',
        'created_at: ""',
        'updated_at: ""',
        '---',
        '',
        summary,
      ].filter(Boolean).join('\n')
    }

    try {
      const { stdout } = await execFileAsync('holmes', [
        'kb', 'write-pending',
        '--content', content,
        '--kb-path', kbPath,
      ])
      return stdout
    } catch (err: any) {
      return JSON.stringify({ error: `KbExtractAndSave failed: ${err.message}` })
    }
  },
})
