import type { TranslationKey } from './it'

/**
 * English dictionary (spec §9). `satisfies Record<TranslationKey, string>`
 * enforces key parity with `it.ts` at compile time: a missing key fails the
 * Record check, an extra key fails excess-property checking.
 */
export const en = {
  'app.name': 'Turni',

  'common.loading': 'Loading…',
  'common.retry': 'Retry',
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.saving': 'Saving…',
  'common.saved': 'Saved',
  'common.remove': 'Remove',
  'common.copy': 'Copy',
  'common.copied': 'Copied',
  'common.previous': 'Previous',
  'common.next': 'Next',
  'common.romeTime': 'All times are Rome time.',

  'nav.schedule': 'Schedule',
  'nav.swaps': 'Swaps',
  'nav.constraints': 'Constraints',
  'nav.notifications': 'Notifications',
  'nav.settings': 'Settings',
  'nav.soon': 'Coming soon',
  'nav.admin': 'Admin',
  'nav.root': 'Users',

  'shell.logout': 'Log out',
  'shell.loggedInAs': 'Signed in as {name}',
  'language.toggleLabel': 'Language',
  'language.it': 'IT',
  'language.en': 'EN',

  'login.title': 'Sign in',
  'login.username': 'Username',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  'login.submitting': 'Signing in…',

  'week.status.open': 'Open',
  'week.status.solved': 'In review',
  'week.status.locked': 'Published',
  'week.closesIn': 'Requests open for {time}',
  'week.deadlinePassed': 'Request window closed',
  'countdown.days': 'd',
  'countdown.hours': 'h',
  'countdown.minutes': 'min',

  'schedule.title': 'Week schedule',
  'schedule.pickWeek': 'Pick a week',
  'schedule.published': 'Published',
  'schedule.notPublished.title': 'Schedule not yet published',
  'schedule.notPublished.open':
    'The request window is still open: shifts appear after it closes on Sunday at 17:00.',
  'schedule.notPublished.solved':
    'The schedule is being prepared and will be visible once published.',
  // §3.2: only admin/root see this preview — the week is solved but not yet
  // published, and workers see nothing.
  'schedule.preview': 'Preview: not yet published',
  'schedule.publish.help':
    'Review the shifts above, then publish to make them visible to everyone and trigger notifications.',
  'schedule.you': 'you',
  'schedule.empty': 'No shift in this cell',
  'slot.am': 'Morning',
  'slot.pm': 'Afternoon',
  'slot.full_day': 'All day',
  'role.bagnino': 'Lifeguard',
  'role.spiaggino': 'Beach worker',
  'role.jolly': 'Jolly (both roles)',

  'swaps.title': 'Swaps',
  'swaps.create.title': 'New swap',
  'swaps.create.step1': 'Pick one of your shifts',
  'swaps.create.step2': 'Pick the shift to receive',
  'swaps.create.submit': 'Request swap',
  'swaps.create.submitting': 'Sending…',
  'swaps.create.success': 'Request sent',
  'swaps.create.needLockedWeek': 'Swaps apply to published weeks only.',
  'swaps.create.noneOfMine': 'You have no shifts this week.',
  'swaps.create.noCandidates': 'No compatible shift to request.',
  'swaps.expiresNote': 'Requests expire after 48 hours.',
  'swaps.incoming.title': 'Incoming',
  'swaps.incoming.empty': 'No incoming requests.',
  'swaps.outgoing.title': 'Sent & history',
  'swaps.outgoing.empty': 'No sent requests.',
  'swaps.accept': 'Accept',
  'swaps.reject': 'Reject',
  'swaps.fromUser': 'From {name}',
  'swaps.toUser': 'To {name}',
  'swaps.yourShift': 'Your shift',
  'swaps.theirShift': 'Requested shift',
  'swaps.status.pending': 'Pending',
  'swaps.status.accepted': 'Accepted',
  'swaps.status.rejected': 'Rejected',
  'swaps.status.expired': 'Expired',
  'swaps.status.pending_admin': 'Awaiting admin approval',
  'swaps.status.applied': 'Applied',

  'constraints.title': 'My requests',
  'constraints.intro': 'Tell us when you cannot work. You can edit as long as the week is open.',
  'constraints.deadline': 'Closes Sunday at 17:00',
  'constraints.readOnly.solved':
    'Window closed: this week has already been solved and requests can no longer be edited.',
  'constraints.readOnly.locked':
    'Week published: requests can no longer be edited. A change now needs a swap.',
  'constraints.readOnly.deadlinePassed':
    'The Sunday 17:00 deadline has passed: wait for the schedule to be computed.',
  'constraints.noWeeks': 'No week available.',
  'constraints.day.free': 'Available',
  'constraints.day.open': 'Edit {day}',
  'constraints.day.collapse': 'Close {day}',
  'constraints.slots.label': 'When you are unavailable',
  'constraints.fullDayReplaces':
    'You picked all day: choosing morning or afternoon will replace this request.',
  'constraints.slotReplacesFullDay': 'All day replaces the slots already picked.',
  'constraints.kind.label': 'How binding',
  'constraints.kind.hard': 'Binding',
  'constraints.kind.soft': 'Preference',
  'constraints.kind.hardHelp':
    'Binding: the solver cannot break it. If no schedule is possible you will be asked to move your free day.',
  'constraints.kind.softHelp':
    'Preference: the solver tries to honour it, but may ignore it to cover the shifts.',
  'constraints.note.label': 'Note (optional)',
  'constraints.note.placeholder': 'Reason, time, details…',
  'constraints.weekend.hint':
    'Saturday and Sunday follow a fixed template the solver never solves.',
  'constraints.weekend.hardWarning':
    'A binding weekend request cannot be resolved by solving: it is recorded and forwarded to an admin, who handles it by hand.',
  'constraints.summary.hard': 'Binding',
  'constraints.summary.soft': 'Preference',

  'notifications.title': 'Notifications',
  'notifications.empty': 'No notifications.',
  'notifications.markAllRead': 'Mark all as read',
  'notifications.bell': 'Notifications, {count} unread',
  'notifications.unread': 'Unread',

  // §10 event types → one line each, rendered from the structured payload.
  'notif.schedule_published': 'Schedule published for week {week}.',
  'notif.swap_requested': 'You received a swap request: {from} for {to} ({week}).',
  'notif.swap_accepted': 'Swap accepted: {from} for {to} ({week}).',
  'notif.swap_rejected': 'Swap rejected: {from} for {to} ({week}).',
  'notif.sacrifice_proposed':
    'No schedule is possible for {week}: you have been asked to move your free day to {day}.',
  'notif.sacrifice_resolved':
    'Proposal accepted: your free day for {week} is {day}. Schedule published.',
  'notif.sacrifice_escalated': 'Unresolved conflict on week {week}: it needs manual handling.',
  'notif.weekend_hard_escalated':
    '{name} filed {day} ({slot}) as a binding unavailability: the weekend is a fixed template and needs handling by hand.',
  'notif.window_closing_24h': 'Requests for week {week} close in 24 hours.',
  'notif.admin_override': 'An admin changed the shifts for week {week}.',
  // Any event type this build does not know — never raw JSON, never a crash.
  'notif.unknown': 'New update.',
  'notif.shift': '{day} {slot} ({role})',
  'notif.conflict.title': 'Conflicting requests',
  'notif.conflict.item': '{who}: {day}, {slot}',
  'notif.conflict.you': 'Your request',
  'notif.conflict.other': 'A colleague’s request',

  'sacrifice.title': 'We need your decision',
  'sacrifice.question':
    'For week {week} there is no schedule that satisfies every binding request. Move your free day to {day}?',
  'sacrifice.keepsHard':
    'Your binding request stands either way: you will not work on the day you asked off.',
  'sacrifice.acceptConsequence':
    'If you accept, the schedule is recomputed with the moved free day and published.',
  'sacrifice.declineConsequence':
    'If you decline, the week stays unresolved and the conflict goes to an admin.',
  'sacrifice.accept': 'Accept the move',
  'sacrifice.decline': 'Decline',
  'sacrifice.working': 'Sending…',
  'sacrifice.accepted': 'Proposal accepted.',
  'sacrifice.declined': 'Proposal declined: the decision goes to an admin.',

  'settings.title': 'Settings',
  'settings.language.title': 'Language',
  'settings.language.help': 'Applies to the app and to the emails you receive.',
  'settings.account.title': 'Account',
  'settings.account.email': 'Email',
  'settings.account.noEmail': 'No email on file.',
  'settings.account.emailManaged':
    'The email address is managed by the admin who created the account.',
  'settings.account.notifications': 'Receive emails',
  'settings.account.notificationsHelp':
    'Notifications stay visible in the app even if you turn emails off.',
  'settings.password.title': 'Change password',
  'settings.password.current': 'Current password',
  'settings.password.new': 'New password',
  'settings.password.confirm': 'Confirm new password',
  'settings.password.submit': 'Update password',
  'settings.password.success': 'Password updated.',
  'settings.password.mismatch': 'The two passwords do not match.',
  'settings.ics.title': 'Calendar feed (ICS)',
  'settings.ics.help':
    'Subscribe your calendar to this address to see your published shifts. The address is personal: whoever holds it sees your shifts.',
  'settings.ics.url': 'Calendar address',
  'settings.ics.regenerate': 'Regenerate address',
  'settings.ics.regenerateWarning':
    'Regenerating breaks every calendar already subscribed: you will have to subscribe again. That is exactly the point if the address leaked.',
  'settings.ics.regenerateConfirm': 'Confirm regeneration?',
  'settings.ics.regenerated': 'New address generated.',

  'admin.title': 'Admin',
  'admin.intro':
    'Generate, publish and hand-correct the schedule. Everything done here is recorded.',
  'admin.noWeeks': 'No week available.',

  'admin.noWeekSelected':
    'No week selected: pick one above to see the controls.',
  'admin.solve.title': 'Generate schedule',
  'admin.solve.help':
    'Generating computes the schedule but does not make it visible: publishing is a separate step.',
  'admin.solve.generate': 'Generate now',
  'admin.solve.working': 'Solving…',
  'admin.solve.confirm':
    '“Generate now” closes this week’s request window early: from that moment nobody can edit their requests. The schedule is left for review and is not published.',
  'admin.solve.confirmAction': 'Close the window and generate',
  'admin.solve.result': 'Solve result',
  'admin.solve.status.optimal': 'Optimal solution',
  'admin.solve.status.feasible': 'Valid solution',
  'admin.solve.status.infeasible': 'No possible solution',
  'admin.solve.status.unknown': 'Unrecognised result',
  'admin.solve.duration': 'Solved in {seconds} s',
  'admin.solve.objective': 'Objective breakdown',
  'admin.solve.objective.softUnmet': 'Unmet preferences',
  'admin.solve.objective.alternation': 'Alternation breaks',
  'admin.solve.objective.fairness': 'Morning/afternoon imbalance',
  'admin.solve.objective.spread': 'Weekend pairs sharing a free day',
  'admin.solve.objective.jollyDays': 'Days worked by the jolly',
  'admin.solve.objective.total': 'Weighted total',
  'admin.solve.blocking': 'Conflicting binding requests',
  'admin.solve.blocking.help':
    'No schedule satisfies all of these together. If the conflict falls on a Friday for a core worker, they are offered a free-day move; otherwise the decision stays with you.',
  'admin.solve.blocking.item': '{who}: {day}, {slot}',
  'admin.solve.blocking.unknownWorker': 'A worker',
  'admin.solve.infeasibleNote': 'A week with no solution can never be published.',

  'admin.publish.title': 'Publish',
  'admin.publish.help':
    'Publishing makes the shifts visible to everyone, locks the slots and sends the notifications. After that, changes happen only through a swap or a manual change.',
  'admin.publish.submit': 'Publish the week',
  'admin.publish.working': 'Publishing…',
  'admin.publish.done': 'Week published.',
  'admin.publish.needsSolved':
    'You can only publish a week that has been solved and has no open conflict.',
  'admin.publish.alreadyPublished': 'This week is already published.',

  'admin.override.title': 'Change a shift by hand',
  'admin.override.help':
    'Change who covers an already published slot, without going through a peer swap.',
  'admin.override.needsLocked':
    'Manual changes apply to published weeks only: an unpublished week is regenerated instead.',
  'admin.override.noSlots': 'No shift to change in this week.',
  'admin.override.slot': 'Shift to change',
  'admin.override.newHolder': 'New person',
  'admin.override.pick': 'Choose…',
  'admin.override.slotOption': '{day} {slot} · {role} — {name}',
  'admin.override.warning':
    'You are changing an already published schedule that people are relying on. It takes effect immediately, it is recorded, and both the person losing the shift and the person receiving it are notified.',
  'admin.override.confirmAction': 'Confirm the change',
  'admin.override.working': 'Applying…',
  'admin.override.done': 'Shift changed. The people involved have been notified.',
  'admin.override.violations': 'Rules now broken',
  'admin.override.violations.help':
    'The change was applied anyway: the decision is yours. These situations are left for you to sort out by hand.',
  'admin.override.violation.h2': '{name}: two roles in the same slot ({day}, {slot}).',
  'admin.override.violation.h3': '{name}: no free day this week.',
  'admin.override.violation.h4': '{name}: more than one slot on the same day ({day}).',
  'admin.override.violation.other': '{name}: constraint {rule} is broken.',
  'admin.override.someone': 'A worker',

  'admin.submissions.title': 'Submitted requests',
  'admin.submissions.help': 'Every unavailability filed for this week, by person.',
  'admin.submissions.empty': 'No request for this week.',
  'admin.submissions.item': '{day} · {slot}',

  'admin.audit.title': 'Audit log',
  'admin.audit.help': 'Every state change: solves, publications, swaps and manual changes.',
  'admin.audit.empty': 'No entry in the log.',
  'admin.audit.systemActor': 'System',
  'admin.audit.systemHelp':
    '“System” entries are automated actions with no human actor: the scheduled solve, swap expiry, the nightly backup.',
  'admin.audit.range': '{from}–{to} of {total}',
  'admin.audit.filterByAction': 'Filter by action: {action}',
  'admin.audit.filterByEntity': 'Filter by entity: {entity}',
  'admin.audit.filtersActive': 'Filters active',
  'admin.audit.filtersClear': 'Clear the filters',
  'admin.audit.action.publish': 'Publish',
  'admin.audit.action.solve': 'Solve',
  'admin.audit.action.override': 'Manual change',
  'admin.audit.action.sacrifice': 'Sacrifice',
  'admin.audit.action.swap': 'Swap',
  'admin.audit.action.credential': 'Credentials',
  'admin.audit.action.escalate': 'Escalation',
  'admin.audit.entity.week': 'Week',
  'admin.audit.entity.constraint': 'Request',
  'admin.audit.entity.assignment': 'Shift',
  'admin.audit.entity.swap_request': 'Swap request',
  'admin.audit.entity.sacrifice_proposal': 'Sacrifice proposal',
  'admin.audit.entity.user': 'User',

  'root.title': 'Users',
  'root.intro': 'Create accounts, edit their details, reset passwords. There is no public signup.',
  'root.empty': 'No user.',
  'root.status.active': 'Active',
  'root.status.inactive': 'Deactivated',
  'root.badge.admin': 'Admin',
  'root.field.username': 'Username',
  'root.field.displayName': 'Display name',
  'root.field.role': 'Role',
  'root.field.email': 'Email',
  'root.field.admin': 'Admin permissions',
  'root.field.language': 'Language',
  'root.field.password': 'Initial password',
  'root.create.title': 'New user',
  'root.create.submit': 'Create user',
  'root.create.working': 'Creating…',
  'root.create.done': 'User created.',
  'root.edit.open': 'Manage {name}',
  'root.edit.close': 'Close {name}',
  'root.edit.title': 'Details',
  'root.edit.done': 'Changes saved.',
  'root.deactivate.title': 'Deactivation',
  'root.deactivate.why':
    'Accounts are never deleted. Shifts, swaps and the audit log all reference people: deleting one would either destroy the history or make the log lie about who acted. Deactivation is the only removal there is.',
  'root.deactivate.immediate':
    'Deactivation is immediate and closes any session already open, not just the next sign-in.',
  'root.deactivate.submit': 'Deactivate',
  'root.deactivate.confirmAction': 'Deactivate the account',
  'root.deactivate.working': 'Deactivating…',
  'root.deactivate.done': 'Account deactivated.',
  'root.reactivate.submit': 'Reactivate',
  'root.reactivate.done': 'Account reactivated.',
  'root.password.title': 'Reset the password',
  'root.password.help':
    'Set a new password for this person. The current one is not required — that is the whole point of a reset.',
  'root.password.new': 'New password',
  'root.password.submit': 'Reset the password',
  'root.password.working': 'Resetting…',
  'root.password.done': 'Password reset.',

  // Backend error codes (§7 `{detail: "snake_case_code"}`) → `errors.<code>`.
  'errors.generic': 'Something went wrong. Please try again.',
  'errors.network': 'No connection. Check your network.',
  'errors.not_authenticated': 'Session expired, please sign in again.',
  'errors.forbidden': 'You do not have permission for this action.',
  'errors.invalid_credentials': 'Wrong username or password.',
  'errors.rate_limited': 'Too many attempts, wait a minute.',
  'errors.week_not_found': 'Week not found.',
  'errors.week_not_monday': 'The date must be a Monday.',
  'errors.week_closed': 'The request window for this week is closed.',
  'errors.week_not_solved': 'The week has not been solved yet.',
  'errors.week_already_locked': 'The week is already published.',
  // Shared by swaps (§4) and admin override (§5/§3.4): both are post-lock
  // instruments, so the sentence must be true for either caller.
  'errors.week_not_locked': 'This action applies to published weeks only.',
  // §5/§3.4 admin override (`app/routers/admin.py`).
  'errors.override_no_change': 'That person already covers this slot.',
  'errors.override_ambiguous_slot':
    'On weekends this slot has two holders: pick the exact shift from the list.',
  'errors.override_user_not_found': 'Person not found.',
  'errors.override_user_inactive': 'That person’s account is deactivated.',
  'errors.override_role_invalid': 'That person cannot cover this role.',
  'errors.override_row_mismatch': 'That shift has changed — reload the week and try again.',
  // §5 row 7 root user management (`app/routers/root.py`).
  'errors.user_not_found': 'User not found.',
  'errors.username_taken': 'That username is already taken.',
  // Worded without naming the account: it is only ever returned to the one
  // caller who already knows which row it is (§5).
  'errors.last_root_required':
    'You cannot deactivate the only account that can manage users: nothing would be left to reactivate it.',
  'errors.sacrifice_pending': 'A sacrifice proposal is pending.',
  'errors.sacrifice_not_found': 'Proposal not found.',
  'errors.sacrifice_already_resolved': 'Proposal already resolved.',
  'errors.constraint_not_found': 'Constraint not found.',
  'errors.swap_not_found': 'Swap request not found.',
  'errors.swap_role_invalid': 'The two shifts have incompatible roles.',
  'errors.swap_h2_violation': 'The swap would give someone two roles in the same slot.',
  'errors.swap_h3_violation': 'The swap would make someone work on their free day.',
  'errors.swap_h4_violation': 'The swap would give someone two slots on the same day.',
  'errors.swap_weekend_bagnini_only': 'On weekends only lifeguard shifts can be swapped.',
  'errors.swap_already_resolved': 'Swap request already resolved.',
  'errors.swap_wrong_target': 'This request is not addressed to you.',
  // Reachable whenever the schedule moves under an open page — a swap applied
  // or an admin override since it loaded (§4 re-validates at acceptance).
  'errors.swap_wrong_holder': 'That shift has changed hands — reload the week and try again.',
  'errors.swap_assignment_not_found': 'Shift not found — reload the week.',
  'errors.swap_week_mismatch': 'The two shifts belong to different weeks.',
  'errors.swap_self': 'You cannot swap a shift with yourself.',
  'errors.feed_not_found': 'Invalid calendar address.',
  // These four are exactly what PATCH /me/settings can return (§7). They were
  // wrong once — the dictionary named codes the backend never sends, so a
  // mistyped password read as a generic failure while the right sentence sat
  // unused. Keep them in step with app/routers/auth.py.
  'errors.invalid_current_password': 'Your current password is not correct.',
  'errors.current_password_required': 'Enter your current password to change it.',
  'errors.new_password_required': 'Enter the new password.',
  'errors.new_password_too_short': 'The new password must be at least 8 characters.',
} satisfies Record<TranslationKey, string>
