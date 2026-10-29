/**
 * Typed API client generated from the backend's OpenAPI spec.
 * Regenerate types with `npm run gen:api` after backend schema changes;
 * an incompatible change then fails `tsc` instead of failing in production.
 */
import createClient from 'openapi-fetch'
import { snapshotFetch, useSnapshot } from '../snapshot'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type Meta = Schemas['Meta']

export const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export const api = createClient<paths>({
  baseUrl,
  // Served from static files when the snapshot fallback is active.
  fetch: (req: Request) => (useSnapshot.getState().active ? snapshotFetch(req) : fetch(req)),
})

/** Problem details (RFC 7807) returned by the API on errors. */
export interface Problem {
  type: string
  title: string
  status: number
  detail?: string
  request_id?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly problem: Problem | undefined

  constructor(status: number, problem: Problem | undefined) {
    super(problem?.detail ?? problem?.title ?? `API error ${status}`)
    this.status = status
    this.problem = problem
  }
}

/** Unwrap an openapi-fetch result, throwing ApiError on failure. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data
  throw new ApiError(result.response.status, result.error as Problem | undefined)
}
