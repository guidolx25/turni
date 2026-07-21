/**
 * Data-fetching lives in hooks, components stay presentational (project
 * convention). `useResource` is the one loading/error/reload state machine;
 * the per-endpoint hooks below memoize their loader on its inputs.
 */
import { useCallback, useEffect, useState } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import {
  adminApi,
  constraintsApi,
  rootApi,
  scheduleApi,
  swapsApi,
  weeksApi,
} from '../api/endpoints'
import type {
  AdminConstraintsOut,
  AuditPageOut,
  AuditQuery,
  ConstraintOut,
  ScheduleOut,
  SwapRequestOut,
  UserAdminOut,
  WeekOut,
} from '../api/types'
import type { TranslationKey } from '../i18n'

export interface Resource<T> {
  data: T | null
  loading: boolean
  errorKey: TranslationKey | null
  reload: () => void
}

type Loader<T> = () => Promise<T>

interface Settled<T> {
  // Which (loader, reload-generation) produced this result: results from a
  // superseded loader are ignored at render time instead of being cleared by
  // an effect, so there is no setState-in-effect cascade.
  load: Loader<T>
  version: number
  data: T | null
  errorKey: TranslationKey | null
}

export function useResource<T>(load: Loader<T> | null): Resource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!load) return
    let cancelled = false
    load()
      .then((result) => {
        if (!cancelled) {
          setSettled({ load, version, data: result, errorKey: null })
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSettled({ load, version, data: null, errorKey: toErrorKey(error) })
        }
      })
    return () => {
      cancelled = true
    }
  }, [load, version])

  const reload = useCallback(() => {
    setVersion((v) => v + 1)
  }, [])

  // Same loader, any generation: the last value this loader produced.
  const forThisLoad = load && settled && settled.load === load ? settled : null
  // Same loader AND the current generation: a settled, up-to-date result.
  const current = forThisLoad && forThisLoad.version === version ? forThisLoad : null

  return {
    // A RELOAD keeps the previous value on screen while the refetch is in
    // flight; a change of loader (a different week) does not, because that value
    // answers a different question. Without this, every write-then-reload blanks
    // its own page for a frame — and in the admin panel it went further: the
    // week list re-read after a solve unmounted the panel holding the solve
    // result, discarding it.
    data: (current ?? forThisLoad)?.data ?? null,
    errorKey: current?.errorKey ?? null,
    loading: load !== null && current === null,
    reload,
  }
}

export function useWeeks(): Resource<WeekOut[]> {
  const load = useCallback(() => weeksApi.list(), [])
  return useResource(load)
}

export function useSchedule(week: string | null): Resource<ScheduleOut> {
  const load = useCallback(() => scheduleApi.get(week ?? ''), [week])
  return useResource(week ? load : null)
}

export function useConstraints(week: string | null): Resource<ConstraintOut[]> {
  const load = useCallback(() => constraintsApi.list(week ?? ''), [week])
  return useResource(week ? load : null)
}

export function useSwaps(week: string | null): Resource<SwapRequestOut[]> {
  const load = useCallback(() => swapsApi.list(week ?? ''), [week])
  return useResource(week ? load : null)
}

/**
 * §7 `GET /admin/constraints?week=`. `enabled` is the §5 capability gate: a
 * caller without `view_all_constraints` must not even issue the request, so the
 * hook returns the idle resource rather than a 403 the view has to swallow.
 */
export function useAdminConstraints(
  week: string | null,
  enabled: boolean,
): Resource<AdminConstraintsOut> {
  const load = useCallback(() => adminApi.constraints(week ?? ''), [week])
  return useResource(week && enabled ? load : null)
}

export function useAudit(query: AuditQuery, enabled: boolean): Resource<AuditPageOut> {
  const { limit, offset, action, entity } = query
  const load = useCallback(
    () => adminApi.audit({ limit, offset, action, entity }),
    [limit, offset, action, entity],
  )
  return useResource(enabled ? load : null)
}

export function useRootUsers(enabled: boolean): Resource<UserAdminOut[]> {
  const load = useCallback(() => rootApi.list(), [])
  return useResource(enabled ? load : null)
}
