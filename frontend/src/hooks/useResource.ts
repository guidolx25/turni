/**
 * Data-fetching lives in hooks, components stay presentational (project
 * convention). `useResource` is the one loading/error/reload state machine;
 * the per-endpoint hooks below memoize their loader on its inputs.
 */
import { useCallback, useEffect, useState } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { constraintsApi, scheduleApi, swapsApi, weeksApi } from '../api/endpoints'
import type { ConstraintOut, ScheduleOut, SwapRequestOut, WeekOut } from '../api/types'
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

  const current =
    load && settled && settled.load === load && settled.version === version ? settled : null

  return {
    data: current?.data ?? null,
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
