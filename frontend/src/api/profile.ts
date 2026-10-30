import { apiGet, apiPut } from './client.ts'
import type { ProfileUpdate, ProfileView } from './types.ts'

export function getProfile(): Promise<ProfileView> {
  return apiGet('/api/profile')
}

export function updateProfile(update: ProfileUpdate): Promise<ProfileView> {
  return apiPut('/api/profile', update)
}
