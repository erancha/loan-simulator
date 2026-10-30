import { ApiException } from '../api/client.ts'
import { NOT_A_NUMBER, refused, saveFailed } from './copy.ts'

/**
 * The inline message for a failed save: a refused value (a 422, or the local input check, whose
 * English reason is logged) or any other failure. Anything that is not an Error propagates.
 */
export function rejectionText(error: unknown): string {
  if (error instanceof RangeError) {
    console.error(error)
    return refused(NOT_A_NUMBER)
  }
  if (error instanceof ApiException && error.status === 422) return refused(error.message)
  if (error instanceof Error) return saveFailed(error.message)
  throw error
}
