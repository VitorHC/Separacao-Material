import type { Extraction, Group, Project, Shipment } from './types'
export async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, { method, signal, headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Não foi possível conectar ao servidor. Confira se o sistema está em execução e tente novamente.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail) ? detail.map((e: {loc?: string[]; msg?: string}) => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ') : detail
    throw new Error(typeof message === 'string' ? message : 'Não foi possível concluir a operação. Tente novamente.')
  }
  if (data === null) throw new Error('O servidor retornou uma resposta inválida.')
  return data as T
}
export const api = {
  projects: (signal?: AbortSignal) => request<Project[]>('/projetos', 'GET', undefined, signal),
  groups: (signal?: AbortSignal) => request<Group[]>('/consolidado?somente_pendentes=false', 'GET', undefined, signal),
  shipments: (signal?: AbortSignal) => request<Shipment[]>('/remessas', 'GET', undefined, signal),
  extract: (file: File) => { const body = new FormData(); body.append('arquivo', file); return request<Extraction>('/documentos/extrair', 'POST', body) },
}
