/**
 * Route table. Everything except /login sits behind the auth guard inside the
 * shell; /admin and /root sit behind a further §5 capability guard.
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'

import { useAuth } from './auth/AuthContext'
import { canManageUsers, hasAdminPanelAccess } from './auth/capabilities'
import { LoadingIndicator } from './components/common'
import { Shell } from './components/Shell'
import { AdminView } from './views/AdminView'
import { ConstraintsView } from './views/ConstraintsView'
import { LoginView } from './views/LoginView'
import { NotificationsView } from './views/NotificationsView'
import { RootView } from './views/RootView'
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

/**
 * §5 capability guard. A worker who reaches /admin or /root by typing the URL
 * gets the schedule, not a panel and not an error page: the capability is the
 * whole authorization story on the client, and the server enforces it again on
 * every request the panel would make.
 */
function RequireCapability({ allowed, children }: { allowed: boolean; children: ReactNode }) {
  const { initializing } = useAuth()
  if (initializing) {
    return (
      <div className="grid min-h-screen place-items-center">
        <LoadingIndicator />
      </div>
    )
  }
  if (!allowed) return <Navigate to="/" replace />
  return children
}

function AdminRoute() {
  const { user } = useAuth()
  return (
    <RequireCapability allowed={hasAdminPanelAccess(user?.capabilities)}>
      <AdminView />
    </RequireCapability>
  )
}

function RootRoute() {
  const { user } = useAuth()
  return (
    <RequireCapability allowed={canManageUsers(user?.capabilities)}>
      <RootView />
    </RequireCapability>
  )
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
        <Route path="/admin" element={<AdminRoute />} />
        <Route path="/root" element={<RootRoute />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
