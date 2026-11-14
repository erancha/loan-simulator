import { INVITE_MESSAGE } from './copy.ts'

/** The wa.me composer with the invite filled in, leaving only the pick of a contact or group.
 * The page's own address closes the message, so the invite names whichever deployment sent it. */
export function whatsAppInviteUrl(): string {
  const message = [...INVITE_MESSAGE, window.location.origin].join('\n')
  return `https://wa.me/?text=${encodeURIComponent(message)}`
}
