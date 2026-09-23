import Clarity from '@microsoft/clarity'

export function initClarity() {
  const projectId = import.meta.env.VITE_CLARITY_PROJECT_ID
  if (!import.meta.env.PROD || !projectId) return
  Clarity.init(projectId)
}
