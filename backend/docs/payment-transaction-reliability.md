# Fiabilité paiement & Transaction Engine (Phase D)

Ce document décrit les correctifs appliqués suite à l'audit Phase D (Client → Paiement →
Transaction → Scheduler → GatewaySim → Gateway Mobile → USSD → Résultat). Voir aussi
`backend/docs/operators-ussd-codes.md` et `backend/docs/dashboard-modernization.md` pour les
phases précédentes.

Aucune nouvelle fonctionnalité métier, aucun changement d'architecture — uniquement les
correctifs classés 🔴 Critique par l'audit.

## 1. Transaction bloquée en `failed` malgré un paiement accepté

`Transaction.sync_from_payment()` (`apps/core/models.py`) résolvait `new_status = 'pending' if
payment.status == 'accepted' and self.gateway else 'failed'` — un paiement accepté sans Gateway
assignée résolvait directement en `'failed'`, un état terminal sans transition sortante
(`TransactionStateMachine.TRANSITIONS`). Un client payé restait donc bloqué sans issue
automatique.

**Correctif** : `new_status = 'pending' if payment.status == 'accepted' else 'failed'` — le
paiement accepté reste toujours `'pending'`, `Transaction.gateway` n'entre plus dans la décision
de statut.

**Limite assumée** : ce correctif règle le blocage du *statut*, pas l'assignation effective d'une
Gateway à une transaction qui n'en a jamais eu. Ajouter une réassignation automatique dans
`sync_from_payment()` introduirait un import circulaire (`apps.core.models` → `apps.devices`) et
un risque de double-dispatch non maîtrisé — volontairement laissé hors de ce correctif minimal.
Ces transactions restent visibles et corrigeables manuellement depuis le dashboard
(`/dashboard/transactions/`).

**Tests** : `apps/core/tests.py::TransactionSyncFromPaymentTests`.

## 2. Exception non interceptée dans les webhooks (perte de l'idempotence)

`PaymentService.apply_status()` → `Transaction.sync_from_payment()` → `TransactionStateMachine
.transition()` peut lever `InvalidTransitionError` quand la transaction liée est déjà dans un
autre statut terminal (ex. annulée séparément). Non interceptée, cette exception remontait hors
du `with db_transaction.atomic()` de la vue webhook, annulant tout — y compris la ligne
`WebhookEvent` qui venait d'être insérée pour la déduplication. Un rejeu du même événement
échouait alors indéfiniment de la même façon (500 non géré).

**Correctif** : `apps/payments/webhooks.py::_apply_status_safely()` — capture
`InvalidTransitionError` autour de l'appel à `PaymentService.apply_status()`, journalise, retourne
`False` sans relancer. L'écriture du `Payment` (faite dans le bloc atomique imbriqué de
`apply_status()`) est annulée proprement à son propre savepoint ; le `WebhookEvent` de
l'appelant, lui, survit et committe normalement.

**Tests** : `apps/payments/tests.py::GeniusPayWebhookIdempotencyTests
.test_invalid_transition_is_caught_not_a_500_and_keeps_the_dedup_row`.
(CinetPay et son webhook de notify ont été retirés depuis - la couverture
équivalente pour ce cas vit désormais uniquement côté GeniusPay ci-dessus.)

## 3. Résultat USSD reporté deux fois — double comptage, course non protégée

`TransactionResultView.post()` n'avait aucune protection de concurrence (pas de
`select_for_update()`, pas de vérification d'idempotence). Deux rapports quasi simultanés pour la
même transaction (réaliste sur un réseau USSD instable) pouvaient tous deux lire la même
`TransactionAttempt` in-flight avant qu'aucun n'écrive, chacun appelant indépendamment
`ReservationManager.release()` — doublant silencieusement `GatewaySim.success_count`/
`failure_count`/`consecutive_failures` — et risquant une course « dernière écriture gagne » sur
`Transaction.status` en cas de résultats contradictoires.

**Correctif** : verrouillage de la ligne `Transaction` (`select_for_update()`) pour toute la durée
du traitement, puis vérification `TransactionStateMachine.is_terminal(tx.status)` (nouvelle
méthode) avant de ré-exécuter `ReservationManager.release()`/`RetryManager
.handle_failed_attempt()` — un rapport dupliqué pour une transaction déjà résolue est ignoré
proprement (log + réponse normale), jamais retraité.

**Tests** : `apps/devices/tests.py::NewTransactionEngineIntegrationTests
.test_duplicate_result_report_does_not_double_count_sim_stats_or_double_log`,
`.test_duplicate_result_with_a_conflicting_outcome_is_ignored_not_raced`.

## 4. Retry automatique jamais câblé à un ordonnanceur

`RetryManager.dispatch_due_retries()` et `ReservationManager.release_expired()` existaient,
testés, mais n'avaient aucun appelant en dehors des tests — aucun cron, aucune tâche RQ/Celery,
aucune entrée dans `docker-compose.yml`. Si `USE_NEW_TRANSACTION_ENGINE` est activé sans cela, un
échec réessayable resterait bloqué en `'pending'` indéfiniment, silencieusement.

**Correctif** : `apps/devices/management/commands/dispatch_due_transaction_retries.py` — nouvelle
commande de gestion, même famille que `check_gateway_health`/`reconcile_pending_payments` déjà
existantes. Ne duplique aucune logique — expose uniquement les méthodes déjà écrites et testées.
Sûre à exécuter en boucle (ex. chaque minute via cron).

**Déploiement** : ajouter à la configuration cron de production, par exemple :
```
* * * * * cd /path/to/backend && python manage.py dispatch_due_transaction_retries
```

**Tests** : `apps/devices/tests.py` (voir les appels à
`call_command('dispatch_due_transaction_retries', ...)`).

## 5. Aucune vérification opérateur ↔ SIM physique au moment du dial

Confirmé par l'audit : `SimResolver.resolveSubscriptionId()` (mobile Android) ne fait
correspondre que l'index physique du slot, jamais l'opérateur réel de la carte présente. Deux
scénarios concrets : (a) une SIM échangée entre la réservation backend et le dial (fenêtre de
course, heartbeat rafraîchit `GatewaySim.operator` toutes les ~20s) ; (b) permission
`READ_PHONE_STATE` absente → repli silencieux sur la SIM par défaut du téléphone, en ignorant le
slot demandé.

**Correctif** (additif au protocole Gateway existant, jamais un remplacement) :
- Backend : `gateway_task_payload()` envoyait déjà `operator` dans le payload — inchangé.
- Mobile Dart : `PendingTransaction.operator` (nouveau champ, parsé depuis `json['operator']`),
  propagé jusqu'à `dialUssd(code, simSlot, operator)`. Nouvelle colonne `operator` dans la file
  locale sqflite (`transaction_tasks`), migration de schéma v1→v2 avec `onUpgrade` (ALTER TABLE,
  aucune perte de données sur un appareil déjà déployé).
- Mobile Kotlin : `SimResolver.matchesExpectedOperator()` compare le `carrierName` de
  l'abonnement réellement résolu contre l'opérateur attendu (tolérant à la casse et aux variantes
  de nommage). `TelephonyGateway.sendUssdChecked()` refuse le dial
  (`OperatorMismatchException`) si la correspondance ne peut pas être positivement confirmée —
  y compris quand l'information n'est pas lisible du tout (permission manquante), contrairement
  au comportement précédent qui composait à l'aveugle dans ce cas.
- `operator` absent/null (ancien build, ou `USE_NEW_TRANSACTION_ENGINE` désactivé côté backend)
  désactive la vérification entièrement — additif, aucune régression pour ce cas.

**Tests** : côté Dart, `test/background/gateway_loop_test.dart` (propagation de `operator` de bout
en bout) et `test/services/local_queue_repository_test.dart` (persistance en base locale). Côté
Kotlin : non testable automatiquement dans cet environnement (aucun appareil/émulateur Android
réel disponible) — vérifié par relecture et par une tentative de compilation Gradle complète (voir
le rapport final pour le résultat exact).
