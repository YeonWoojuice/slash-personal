import { User, Shield, CreditCard, BarChart2, Puzzle, Cog, FolderClosed } from 'lucide-react'

export const SETTINGS_CATEGORIES = [
  { id: 'general', label: '일반', icon: Cog },
  { id: 'files', label: '파일', icon: FolderClosed },
  { id: 'account', label: '계정', icon: User },
  { id: 'privacy', label: '개인정보 보호', icon: Shield },
  { id: 'billing', label: '결제', icon: CreditCard },
  { id: 'usage', label: '사용량', icon: BarChart2 },
  { id: 'plugins', label: '연동', icon: Puzzle },
] as const

export type SettingsCategoryId = (typeof SETTINGS_CATEGORIES)[number]['id']
export const DEFAULT_SETTINGS_CATEGORY: SettingsCategoryId = 'general'

export function isSettingsCategoryId(value: string): value is SettingsCategoryId {
  return SETTINGS_CATEGORIES.some((c) => c.id === value)
}
