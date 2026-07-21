/**
 * Route table. Everything except /login sits behind the auth guard inside the
 * shell; the admin and root panels get their routes when Phase 6 lands.
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'

import { useAuth } from './auth/AuthContext'
import { LoadingIndicator } from './components/common'
import { Shell } from './components/Shell'
import { ConstraintsView } from './views/ConstraintsView'
import { LoginView } from './views/LoginView'
import { NotificationsView } from './views/NotificationsView'
import { ScheduleView } from './views/ScheduleView'
import { SettingsView } from './views/SettingsView'
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
        <Route path="/constraints" element={<ConstraintsView />} />
        <Route path="/notifications" element={<NotificationsView />} />
        <Route path="/settings" element={<SettingsView />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
