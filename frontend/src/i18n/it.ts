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
  'common.previous': 'Precedenti',
  'common.next': 'Successive',
  'common.romeTime': 'Tutti gli orari sono in ora di Roma.',

  'nav.schedule': 'Turni',
  'nav.swaps': 'Scambi',
  'nav.constraints': 'Vincoli',
  'nav.notifications': 'Notifiche',
  'nav.settings': 'Impostazioni',
  'nav.soon': 'In arrivo',
  'nav.admin': 'Amministrazione',
  'nav.root': 'Utenti',

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
  // §3.2: solo admin/root vedono questa anteprima — la settimana è risolta ma
  // non ancora pubblicata, e i lavoratori non vedono nulla.
  'schedule.preview': 'Anteprima: non ancora pubblicata',
  'schedule.publish.help':
    'Controlla i turni qui sopra, poi pubblica per renderli visibili a tutti e avviare le notifiche.',
  'schedule.you': 'tu',
  'schedule.empty': 'Nessun turno in questa casella',
  'slot.am': 'Mattina',
  'slot.pm': 'Pomeriggio',
  'slot.full_day': 'Tutto il giorno',
  'role.bagnino': 'Bagnino',
  'role.spiaggino': 'Spiaggino',
  'role.jolly': 'Jolly',

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

  'admin.title': 'Amministrazione',
  'admin.intro':
    'Generazione, pubblicazione e correzioni manuali del calendario. Ogni azione qui è registrata.',
  'admin.noWeeks': 'Nessuna settimana disponibile.',

  'admin.noWeekSelected':
    'Nessuna settimana selezionata: scegline una qui sopra per vedere i controlli.',
  'admin.solve.title': 'Genera calendario',
  'admin.solve.help':
    'Generare calcola il calendario ma non lo rende visibile: la pubblicazione è un passo separato.',
  'admin.solve.generate': 'Genera ora',
  'admin.solve.working': 'Calcolo in corso…',
  'admin.solve.confirm':
    '«Genera ora» chiude in anticipo la finestra richieste di questa settimana: da quel momento nessuno può più modificare le proprie richieste. Il calendario resta da rivedere e non viene pubblicato.',
  'admin.solve.confirmAction': 'Chiudi la finestra e genera',
  'admin.solve.result': 'Esito del calcolo',
  'admin.solve.status.optimal': 'Soluzione ottima',
  'admin.solve.status.feasible': 'Soluzione valida',
  'admin.solve.status.infeasible': 'Nessuna soluzione possibile',
  'admin.solve.status.unknown': 'Esito non riconosciuto',
  'admin.solve.duration': 'Calcolato in {seconds} s',
  'admin.solve.objective': 'Dettaglio obiettivo',
  'admin.solve.objective.softUnmet': 'Preferenze non soddisfatte',
  'admin.solve.objective.alternation': 'Interruzioni di alternanza',
  'admin.solve.objective.fairness': 'Squilibrio mattina/pomeriggio',
  'admin.solve.objective.spread': 'Coppie del weekend con lo stesso giorno libero',
  'admin.solve.objective.jollyDays': 'Giornate lavorate dal jolly',
  'admin.solve.objective.total': 'Totale pesato',
  'admin.solve.blocking': 'Richieste vincolanti in conflitto',
  'admin.solve.blocking.help':
    'Non esiste un calendario che rispetti tutte queste richieste insieme. Se il conflitto cade di venerdì su un lavoratore stabile, gli viene proposto di spostare il giorno libero; altrimenti la decisione resta a te.',
  'admin.solve.blocking.item': '{who}: {day}, {slot}',
  'admin.solve.blocking.unknownWorker': 'Un lavoratore',
  'admin.solve.infeasibleNote': 'Una settimana senza soluzione non può essere pubblicata.',

  'admin.publish.title': 'Pubblica',
  'admin.publish.help':
    'La pubblicazione rende i turni visibili a tutti, blocca le fasce e invia le notifiche. Da quel momento si cambia solo con uno scambio o con una modifica manuale.',
  'admin.publish.submit': 'Pubblica la settimana',
  'admin.publish.working': 'Pubblicazione…',
  'admin.publish.done': 'Settimana pubblicata.',
  'admin.publish.needsSolved':
    'Puoi pubblicare solo una settimana già calcolata e senza conflitti aperti.',
  'admin.publish.alreadyPublished': 'Questa settimana è già pubblicata.',

  'admin.override.title': 'Modifica manuale di un turno',
  'admin.override.help':
    'Cambia chi copre una fascia già pubblicata, senza passare dallo scambio tra colleghi.',
  'admin.override.needsLocked':
    'La modifica manuale vale solo per le settimane pubblicate: una settimana non ancora pubblicata si rigenera.',
  'admin.override.noSlots': 'Nessun turno da modificare in questa settimana.',
  'admin.override.slot': 'Turno da modificare',
  'admin.override.newHolder': 'Nuova persona',
  'admin.override.pick': 'Scegli…',
  'admin.override.slotOption': '{day} {slot} · {role} — {name}',
  'admin.override.warning':
    'Stai cambiando un calendario già pubblicato su cui le persone contano. La modifica ha effetto subito, viene registrata, e sia chi perde il turno sia chi lo riceve ricevono una notifica.',
  'admin.override.confirmAction': 'Conferma la modifica',
  'admin.override.working': 'Modifica in corso…',
  'admin.override.done': 'Turno modificato. Le persone coinvolte sono state avvisate.',
  'admin.override.violations': 'Regole ora non rispettate',
  'admin.override.violations.help':
    'La modifica è stata applicata comunque: la decisione è tua. Queste situazioni restano da sistemare a mano.',
  'admin.override.violation.h2': '{name}: due ruoli nella stessa fascia ({day}, {slot}).',
  'admin.override.violation.h3': '{name}: nessun giorno libero in settimana.',
  'admin.override.violation.h4': '{name}: più di una fascia nello stesso giorno ({day}).',
  'admin.override.violation.other': '{name}: vincolo {rule} non rispettato.',
  'admin.override.someone': 'Un lavoratore',

  'admin.submissions.title': 'Richieste ricevute',
  'admin.submissions.help': 'Tutte le indisponibilità inviate per questa settimana, per persona.',
  'admin.submissions.empty': 'Nessuna richiesta per questa settimana.',
  'admin.submissions.item': '{day} · {slot}',

  'admin.audit.title': 'Registro',
  'admin.audit.help':
    'Ogni cambiamento di stato: calcoli, pubblicazioni, scambi, modifiche manuali.',
  'admin.audit.empty': 'Nessuna voce nel registro.',
  'admin.audit.systemActor': 'Sistema',
  'admin.audit.systemHelp':
    'Le voci di «Sistema» sono azioni automatiche senza autore umano: calcolo pianificato, scadenza degli scambi, backup notturno.',
  'admin.audit.range': '{from}–{to} di {total}',
  'admin.audit.filterByAction': 'Filtra per azione: {action}',
  'admin.audit.filterByEntity': 'Filtra per oggetto: {entity}',
  'admin.audit.filtersActive': 'Filtri attivi',
  'admin.audit.filtersClear': 'Rimuovi i filtri',
  'admin.audit.action.publish': 'Pubblicazione',
  'admin.audit.action.solve': 'Calcolo',
  'admin.audit.action.override': 'Modifica manuale',
  'admin.audit.action.sacrifice': 'Sacrificio',
  'admin.audit.action.swap': 'Scambio',
  'admin.audit.action.credential': 'Credenziali',
  'admin.audit.action.escalate': 'Segnalazione',
  'admin.audit.entity.week': 'Settimana',
  'admin.audit.entity.constraint': 'Richiesta',
  'admin.audit.entity.assignment': 'Turno',
  'admin.audit.entity.swap_request': 'Richiesta di scambio',
  'admin.audit.entity.sacrifice_proposal': 'Proposta di sacrificio',
  'admin.audit.entity.user': 'Utente',

  'root.title': 'Utenti',
  'root.intro':
    'Creazione degli account, modifica dei dati, reimpostazione delle password. Non c’è registrazione pubblica.',
  'root.empty': 'Nessun utente.',
  'root.status.active': 'Attivo',
  'root.status.inactive': 'Disattivato',
  'root.badge.admin': 'Amministratore',
  'root.field.username': 'Nome utente',
  'root.field.displayName': 'Nome visualizzato',
  'root.field.role': 'Ruolo',
  'root.field.email': 'Email',
  'root.field.admin': 'Permessi da amministratore',
  'root.field.language': 'Lingua',
  'root.field.password': 'Password iniziale',
  'root.create.title': 'Nuovo utente',
  'root.create.submit': 'Crea utente',
  'root.create.working': 'Creazione…',
  'root.create.done': 'Utente creato.',
  'root.edit.open': 'Gestisci {name}',
  'root.edit.close': 'Chiudi {name}',
  'root.edit.title': 'Dati',
  'root.edit.done': 'Modifiche salvate.',
  'root.deactivate.title': 'Disattivazione',
  'root.deactivate.why':
    'Gli account non si eliminano mai. Turni, scambi e registro fanno riferimento alle persone: cancellarne una distruggerebbe lo storico oppure renderebbe falso il registro. La disattivazione è l’unica rimozione prevista.',
  'root.deactivate.immediate':
    'La disattivazione ha effetto subito e chiude anche le sessioni già aperte, non solo il prossimo accesso.',
  'root.deactivate.submit': 'Disattiva',
  'root.deactivate.confirmAction': 'Disattiva l’account',
  'root.deactivate.working': 'Disattivazione…',
  'root.deactivate.done': 'Account disattivato.',
  'root.reactivate.submit': 'Riattiva',
  'root.reactivate.done': 'Account riattivato.',
  'root.password.title': 'Reimposta la password',
  'root.password.help':
    'Imposta una nuova password per questa persona. Non serve quella attuale: è proprio questo il senso di una reimpostazione.',
  'root.password.new': 'Nuova password',
  'root.password.submit': 'Reimposta la password',
  'root.password.working': 'Reimpostazione…',
  'root.password.done': 'Password reimpostata.',

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
  // Shared by swaps (§4) and admin override (§5/§3.4): both are post-lock
  // instruments, so the sentence must be true for either caller.
  'errors.week_not_locked': 'Questa azione vale solo per le settimane pubblicate.',
  // §5/§3.4 admin override (`app/routers/admin.py`).
  'errors.override_no_change': 'Questa persona copre già questa fascia.',
  'errors.override_ambiguous_slot':
    'Nel weekend questa fascia ha due assegnatari: scegli il turno preciso dall’elenco.',
  'errors.override_user_not_found': 'Persona non trovata.',
  'errors.override_user_inactive': 'L’account di questa persona è disattivato.',
  'errors.override_role_invalid': 'Questa persona non può coprire questo ruolo.',
  'errors.override_row_mismatch': 'Il turno è cambiato: ricarica la settimana e riprova.',
  // §5 row 7 root user management (`app/routers/root.py`).
  'errors.user_not_found': 'Utente non trovato.',
  'errors.username_taken': 'Questo nome utente è già in uso.',
  // Worded without naming the account: it is only ever returned to the one
  // caller who already knows which row it is (§5).
  'errors.last_root_required':
    'Non puoi disattivare l’unico account che può gestire gli utenti: resteresti senza modo di riattivarlo.',
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
  // These four are exactly what PATCH /me/settings can return (§7). They were
  // wrong once — the dictionary named codes the backend never sends, so a
  // mistyped password read as a generic failure while the right sentence sat
  // unused. Keep them in step with app/routers/auth.py.
  'errors.invalid_current_password': 'La password attuale non è corretta.',
  'errors.current_password_required': 'Inserisci la password attuale per cambiarla.',
  'errors.new_password_required': 'Inserisci la nuova password.',
  'errors.new_password_too_short': 'La nuova password deve avere almeno 8 caratteri.',
} as const

export type TranslationKey = keyof typeof it
