/**
 * Italian dictionary — the source of truth for the key set (spec §9).
 * `en.ts` must mirror it 1:1; `satisfies Record<TranslationKey, string>` there
 * makes any drift a compile error in both directions.
 *
 * Flat keys, dot-namespaced. `{placeholders}` are interpolated by `useT()`.
 */
export const it = {
  'app.name': 'Turni',

  'common.loading': 'Caricamento…',
  'common.retry': 'Riprova',
  'common.cancel': 'Annulla',

  'nav.schedule': 'Turni',
  'nav.swaps': 'Scambi',
  'nav.constraints': 'Vincoli',
  'nav.notifications': 'Notifiche',
  'nav.settings': 'Impostazioni',
  'nav.soon': 'In arrivo',

  'shell.logout': 'Esci',
  'shell.loggedInAs': 'Connesso come {name}',
  'language.toggleLabel': 'Lingua',
  'language.it': 'IT',
  'language.en': 'EN',

  'login.title': 'Accedi',
  'login.username': 'Nome utente',
  'login.password': 'Password',
  'login.submit': 'Entra',
  'login.submitting': 'Accesso…',

  'week.status.open': 'Aperta',
  'week.status.solved': 'In revisione',
  'week.status.locked': 'Pubblicata',
  'week.closesIn': 'Richieste aperte ancora {time}',
  'week.deadlinePassed': 'Finestra richieste chiusa',
  'countdown.days': 'g',
  'countdown.hours': 'h',
  'countdown.minutes': 'min',

  'schedule.title': 'Turni della settimana',
  'schedule.pickWeek': 'Scegli la settimana',
  'schedule.published': 'Pubblicato',
  'schedule.notPublished.title': 'Turni non ancora pubblicati',
  'schedule.notPublished.open':
    'La finestra richieste è ancora aperta: i turni arrivano dopo la chiusura di domenica alle 17:00.',
  'schedule.notPublished.solved':
    'Il calendario è in preparazione e sarà visibile alla pubblicazione.',
  'schedule.you': 'tu',
  'schedule.empty': 'Nessun turno in questa casella',
  'slot.am': 'Mattina',
  'slot.pm': 'Pomeriggio',
  'role.bagnino': 'Bagnino',
  'role.spiaggino': 'Spiaggino',

  'swaps.title': 'Scambi',
  'swaps.create.title': 'Nuovo scambio',
  'swaps.create.step1': 'Scegli un tuo turno',
  'swaps.create.step2': 'Scegli il turno da ricevere',
  'swaps.create.submit': 'Richiedi scambio',
  'swaps.create.submitting': 'Invio…',
  'swaps.create.success': 'Richiesta inviata',
  'swaps.create.needLockedWeek': 'Gli scambi riguardano solo settimane pubblicate.',
  'swaps.create.noneOfMine': 'Non hai turni in questa settimana.',
  'swaps.create.noCandidates': 'Nessun turno compatibile da richiedere.',
  'swaps.expiresNote': 'Le richieste scadono dopo 48 ore.',
  'swaps.incoming.title': 'Ricevute',
  'swaps.incoming.empty': 'Nessuna richiesta ricevuta.',
  'swaps.outgoing.title': 'Inviate e storico',
  'swaps.outgoing.empty': 'Nessuna richiesta inviata.',
  'swaps.accept': 'Accetta',
  'swaps.reject': 'Rifiuta',
  'swaps.fromUser': 'Da {name}',
  'swaps.toUser': 'A {name}',
  'swaps.yourShift': 'Il tuo turno',
  'swaps.theirShift': 'Turno richiesto',
  'swaps.status.pending': 'In attesa',
  'swaps.status.accepted': 'Accettata',
  'swaps.status.rejected': 'Rifiutata',
  'swaps.status.expired': 'Scaduta',
  'swaps.status.pending_admin': 'Attende approvazione admin',
  'swaps.status.applied': 'Applicata',

  // Backend error codes (§7 `{detail: "snake_case_code"}`) → `errors.<code>`.
  'errors.generic': 'Qualcosa è andato storto. Riprova.',
  'errors.network': 'Connessione assente. Controlla la rete.',
  'errors.not_authenticated': 'Sessione scaduta, accedi di nuovo.',
  'errors.forbidden': 'Non hai i permessi per questa azione.',
  'errors.invalid_credentials': 'Nome utente o password errati.',
  'errors.rate_limited': 'Troppi tentativi, aspetta un minuto.',
  'errors.week_not_found': 'Settimana non trovata.',
  'errors.week_not_monday': 'La data deve essere un lunedì.',
  'errors.week_closed': 'La finestra richieste per questa settimana è chiusa.',
  'errors.week_not_solved': 'La settimana non è ancora stata calcolata.',
  'errors.week_already_locked': 'La settimana è già pubblicata.',
  'errors.week_not_locked': 'Gli scambi valgono solo per settimane pubblicate.',
  'errors.sacrifice_pending': 'C’è una proposta di sacrificio in sospeso.',
  'errors.sacrifice_not_found': 'Proposta non trovata.',
  'errors.sacrifice_already_resolved': 'Proposta già decisa.',
  'errors.constraint_not_found': 'Vincolo non trovato.',
  'errors.swap_not_found': 'Richiesta di scambio non trovata.',
  'errors.swap_role_invalid': 'I ruoli dei due turni non sono compatibili.',
  'errors.swap_h2_violation': 'Lo scambio darebbe due ruoli nella stessa fascia a una persona.',
  'errors.swap_h3_violation': 'Lo scambio farebbe lavorare qualcuno nel suo giorno libero.',
  'errors.swap_h4_violation': 'Lo scambio darebbe due fasce nello stesso giorno a una persona.',
  'errors.swap_weekend_bagnini_only': 'Nel weekend si scambiano solo i turni dei bagnini.',
  'errors.swap_already_resolved': 'Richiesta di scambio già decisa.',
  'errors.swap_wrong_target': 'Questa richiesta non è indirizzata a te.',
} as const

export type TranslationKey = keyof typeof it
