/**
 * Live countdown to a §3 submission deadline (Sun 17:00 Europe/Rome).
 * The deadline is an absolute instant from the backend — no client timezone
 * math beyond subtraction. Ticks once a minute.
 */
import { useEffect, useState } from 'react'

import { countdownTo, type Countdown } from '../lib/dates'

export function useCountdown(deadlineIso: string | null): Countdown | null {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    if (!deadlineIso) return
    const timer = setInterval(() => {
      setNow(new Date())
    }, 60_000)
    return () => {
      clearInterval(timer)
    }
  }, [deadlineIso])

  return deadlineIso ? countdownTo(deadlineIso, now) : null
}
