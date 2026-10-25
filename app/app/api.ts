export type ErrorDetails = {stage?:string;http_status?:number;reason?:string;timeout_seconds?:number}
export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number, public details:ErrorDetails={}) { super(message) }
}

export async function api(path: string, method = 'GET', data?: unknown) {
  const response = await fetch('/api' + path, {
    method,
    headers: data === undefined ? {} : {'Content-Type': 'application/json'},
    body: data === undefined ? undefined : JSON.stringify(data),
  })
  if (!response.ok) {
    const result = await response.json().catch(() => ({detail: 'Request failed'}))
    const detail = result.detail
    throw new ApiError(typeof detail === 'string' ? detail : detail?.message || 'Invalid request', detail?.code || '', response.status,
      detail&&typeof detail==='object'?{stage:detail.stage,http_status:detail.http_status,reason:detail.reason,timeout_seconds:detail.timeout_seconds}:{})
  }
  return response
}
