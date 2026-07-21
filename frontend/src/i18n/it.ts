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
  'common.save': 'Salva',
  'common.saving': 'Salvataggio…',
  'common.saved': 'Salvato',
  'common.remove': 'Rimuovi',
  'common.copy': 'Copia',
  'common.copied': 'Copiato',

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
  'slot.full_day': 'Tutto il giorno',
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

  'constraints.title': 'Le mie richieste',
  'constraints.intro':
    'Segnala quando non puoi lavorare. Puoi modificare finché la settimana è aperta.',
  'constraints.deadline': 'Chiusura domenica alle 17:00',
  'constraints.readOnly.solved':
    'Finestra chiusa: il calendario di questa settimana è già stato calcolato e le richieste non sono più modificabili.',
  'constraints.readOnly.locked':
    'Settimana pubblicata: le richieste non sono più modificabili. Per un cambio serve uno scambio.',
  'constraints.readOnly.deadlinePassed':
    'Il termine di domenica alle 17:00 è passato: attendi il calcolo del calendario.',
  'constraints.noWeeks': 'Nessuna settimana disponibile.',
  'constraints.day.free': 'Disponibile',
  'constraints.day.open': 'Modifica {day}',
  'constraints.day.collapse': 'Chiudi {day}',
  'constraints.slots.label': 'Quando non sei disponibile',
  'constraints.fullDayReplaces':
    'Hai scelto tutto il giorno: selezionare mattina o pomeriggio sostituirà questa richiesta.',
  'constraints.slotReplacesFullDay': 'Tutto il giorno sostituisce le fasce già scelte.',
  'constraints.kind.label': 'Quanto pesa',
  'constraints.kind.hard': 'Vincolante',
  'constraints.kind.soft': 'Preferenza',
  'constraints.kind.hardHelp':
    'Vincolante: il solver non può violarla. Se non esiste un calendario possibile ti verrà proposto di spostare il tuo giorno libero.',
  'constraints.kind.softHelp':
    'Preferenza: il solver cerca di rispettarla, ma può ignorarla se serve a coprire i turni.',
  'constraints.note.label': 'Nota (facoltativa)',
  'constraints.note.placeholder': 'Motivo, orario, dettagli…',
  'constraints.weekend.hint': 'Sabato e domenica seguono un turno fisso che il solver non calcola.',
  'constraints.weekend.hardWarning':
    'Una richiesta vincolante nel weekend non può essere risolta dal solver: viene registrata e inoltrata a un amministratore, che la gestisce a mano.',
  'constraints.summary.hard': 'Vincolante',
  'constraints.summary.soft': 'Preferenza',

  'notifications.title': 'Notifiche',
  'notifications.empty': 'Nessuna notifica.',
  'notifications.markAllRead': 'Segna tutte come lette',
  'notifications.bell': 'Notifiche, {count} da leggere',
  'notifications.unread': 'Da leggere',

  // §10 event types → one line each, rendered from the structured payload.
  'notif.schedule_published': 'Turni pubblicati per la settimana {week}.',
  'notif.swap_requested': 'Hai ricevuto una richiesta di scambio: {from} per {to} ({week}).',
  'notif.swap_accepted': 'Scambio accettato: {from} per {to} ({week}).',
  'notif.swap_rejected': 'Scambio rifiutato: {from} per {to} ({week}).',
  'notif.sacrifice_proposed':
    'Nessun calendario possibile per {week}: ti è stato proposto di spostare il giorno libero a {day}.',
  'notif.sacrifice_resolved':
    'Proposta accettata: il tuo giorno libero di {week} è {day}. Turni pubblicati.',
  'notif.sacrifice_escalated':
    'Conflitto irrisolto sulla settimana {week}: serve un intervento manuale.',
  'notif.weekend_hard_escalated':
    '{name} ha chiesto {day} ({slot}) come indisponibilità vincolante: il weekend è un turno fisso, va gestito a mano.',
  'notif.window_closing_24h': 'Le richieste per la settimana {week} chiudono tra 24 ore.',
  'notif.admin_override': 'Un amministratore ha modificato i turni della settimana {week}.',
  // Any event type this build does not know — never raw JSON, never a crash.
  'notif.unknown': 'Nuovo aggiornamento.',
  'notif.shift': '{day} {slot} ({role})',
  'notif.conflict.title': 'Richieste in conflitto',
  'notif.conflict.item': '{who}: {day}, {slot}',
  'notif.conflict.you': 'La tua richiesta',
  'notif.conflict.other': 'Richiesta di un collega',

  'sacrifice.title': 'Serve una tua decisione',
  'sacrifice.question':
    'Per la settimana {week} non esiste un calendario che rispetti tutte le richieste vincolanti. Sposti il tuo giorno libero a {day}?',
  'sacrifice.keepsHard':
    'La tua richiesta vincolante resta valida in ogni caso: non lavorerai nel giorno che hai chiesto.',
  'sacrifice.acceptConsequence':
    'Se accetti, il calendario viene ricalcolato con il giorno libero spostato e pubblicato.',
  'sacrifice.declineConsequence':
    'Se rifiuti, la settimana resta da risolvere e il conflitto passa a un amministratore.',
  'sacrifice.accept': 'Accetto lo spostamento',
  'sacrifice.decline': 'Rifiuto',
  'sacrifice.working': 'Invio…',
  'sacrifice.accepted': 'Proposta accettata.',
  'sacrifice.declined': 'Proposta rifiutata: la decisione passa a un amministratore.',

  'settings.title': 'Impostazioni',
  'settings.language.title': 'Lingua',
  'settings.language.help': 'Vale per l’app e per le email che ricevi.',
  'settings.account.title': 'Account',
  'settings.account.email': 'Email',
  'settings.account.noEmail': 'Nessuna email registrata.',
  'settings.account.emailManaged':
    'L’indirizzo email è gestito dall’amministratore che ha creato l’account.',
  'settings.account.notifications': 'Ricevi email',
  'settings.account.notificationsHelp':
    'Le notifiche restano comunque visibili nell’app anche se disattivi le email.',
  'settings.password.title': 'Cambia password',
  'settings.password.current': 'Password attuale',
  'settings.password.new': 'Nuova password',
  'settings.password.confirm': 'Conferma nuova password',
  'settings.password.submit': 'Aggiorna password',
  'settings.password.success': 'Password aggiornata.',
  'settings.password.mismatch': 'Le due password non coincidono.',
  'settings.ics.title': 'Calendario (ICS)',
  'settings.ics.help':
    'Iscrivi il tuo calendario a questo indirizzo per vedere i tuoi turni pubblicati. L’indirizzo è personale: chi lo possiede vede i tuoi turni.',
  'settings.ics.url': 'Indirizzo del calendario',
  'settings.ics.regenerate': 'Rigenera indirizzo',
  'settings.ics.regenerateWarning':
    'Rigenerando l’indirizzo, ogni calendario già iscritto smette di aggiornarsi: dovrai iscriverlo di nuovo. Serve proprio a questo se l’indirizzo è finito nelle mani sbagliate.',
  'settings.ics.regenerateConfirm': 'Confermi la rigenerazione?',
  'settings.ics.regenerated': 'Nuovo indirizzo generato.',

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
  // Reachable whenever the schedule moves under an open page — a swap applied
  // or an admin override since it loaded (§4 re-validates at acceptance).
  'errors.swap_wrong_holder': 'Il turno è cambiato: ricarica la settimana e riprova.',
  'errors.swap_assignment_not_found': 'Turno non trovato: ricarica la settimana.',
  'errors.swap_week_mismatch': 'I due turni appartengono a settimane diverse.',
  'errors.swap_self': 'Non puoi scambiare un turno con te stesso.',
  'errors.feed_not_found': 'Indirizzo del calendario non valido.',
  'errors.invalid_password': 'La password attuale non è corretta.',
  'errors.password_too_short': 'La nuova password è troppo corta.',
} as const

export type TranslationKey = keyof typeof it
