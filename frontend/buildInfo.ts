import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

/**
 * The build the landing page names under its title, as the define entries of the Vite and Vitest
 * configs. The image build passes APP_VERSION and APP_COMMIT_DATE as build arguments, since its
 * context has no .git; a build on the host has neither set and reads them from
 * scripts/lib/build-info.sh, the one reader of git for both.
 */
export function buildInfoDefines(): Record<string, string> {
  const { APP_VERSION, APP_COMMIT_DATE } = process.env
  const info =
    APP_VERSION !== undefined && APP_COMMIT_DATE !== undefined
      ? { APP_VERSION, APP_COMMIT_DATE }
      : readFromGit()
  return {
    __APP_VERSION__: JSON.stringify(info.APP_VERSION),
    __APP_COMMIT_DATE__: JSON.stringify(info.APP_COMMIT_DATE),
  }
}

function readFromGit(): { APP_VERSION: string; APP_COMMIT_DATE: string } {
  const script = fileURLToPath(new URL('../scripts/lib/build-info.sh', import.meta.url))
  const lines = Object.fromEntries(
    execFileSync('bash', [script], { encoding: 'utf8' })
      .trim()
      .split('\n')
      .map((line) => line.split('=', 2)),
  )
  const { APP_VERSION, APP_COMMIT_DATE } = lines
  if (APP_VERSION === undefined || APP_COMMIT_DATE === undefined) {
    throw new Error(`${script} did not print APP_VERSION and APP_COMMIT_DATE`)
  }
  return { APP_VERSION, APP_COMMIT_DATE }
}
