/**
 * Route table. Everything except /login sits behind the auth guard inside the
 * shell; later-phase views (constraints, notifications, settings, admin, root)
 * get their routes when their phases land.
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'

import { useAuth } from './auth/AuthContext'
import { LoadingIndicator } from './components/common'
import { Shell } from './components/Shell'
import { LoginView } from './views/LoginView'
import { ScheduleView } from './views/ScheduleView'
import { SwapsView } from './views/SwapsView'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth()
  if (initializing) {
    return (
      <div className="grid min-h-screen place-items-center">
        <LoadingIndicator />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return children
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginView />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route index element={<ScheduleView />} />
        <Route path="/swaps" element={<SwapsView />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
