# Dashboard — modernisation visuelle et tableaux de bord opérationnels (Étapes 3/4)

Ce document décrit le Back Office ajouté/refondu en Étapes 3 et 4, qui font suite au module
Opérateurs/Codes USSD (Étapes 1/2, voir `backend/docs/operators-ussd-codes.md`). Aucune API
existante n'a été modifiée ; seuls `apps/dashboard/` (vues, urls, templates) et deux fonctions de
service (`GatewayManager.gateway_state()` étendue, voir plus bas) ont changé.

## Navigation

La sidebar (`templates/base.html`) est réorganisée en 4 sections, 11 destinations au total :

| Section | Pages |
|---|---|
| Pilotage | Vue d'ensemble, Transactions, Paiements |
| Infrastructure Gateway | Gateways, SIM, Scheduler |
| Configuration métier | Opérateurs, Services / Forfaits, Codes USSD |
| Supervision | Logs / Événements, Santé du système |

Volontairement absents de la sidebar (URLs conservées, pages toujours accessibles directement,
juste retirées du menu) : Remboursements, Clients, Rapports, Notifications, Paramètres — hors du
périmètre demandé pour ce Back Office technique et métier. Aucun profil utilisateur, aucun écran
de paramètres utilisateur n'a été ajouté.

Toutes les URLs pré-existantes (Étapes 1/2 et les 8 pages d'origine) restent aux mêmes chemins —
`/dashboard/audit/` reste `/dashboard/audit/` même si son contenu et son libellé de menu
("Logs / Événements") ont changé.

## Vue d'ensemble (`dashboard_index`)

Étend l'existant : mêmes calculs (transactions du jour, montants, commission, taux de
réussite/échec/attente, dernières transactions), plus :

- Répartition **par opérateur** (nouvelle requête, symétrique à `services_distribution` déjà
  présente).
- Compteurs Gateways en ligne/hors ligne (`GatewayManager.pool_stats()`), SIM disponibles,
  paiements réussis/en attente.
- L'ancien flux d'activité fabriquait un texte de remplissage (`'Paiement reçu - CinetPay -
  1 000 FCFA'`) quand moins de 3 transactions existaient. Remplacé par les 8 derniers
  `TransactionEvent` réels — liste vide honnête plutôt que contenu inventé.

## Transactions (`transactions_list` / `transaction_detail`)

Liste : recherche (référence/téléphone), filtres (statut/opérateur/service), tri (date/montant/
statut), pagination. Colonne SIM : la dernière `TransactionAttempt` ayant réellement une
`gateway_sim` assignée (même `Prefetch` que `PendingTransactionsView`, pas `Gateway.host` qui est
l'UUID de l'appareil, pas une SIM).

Détail (`/dashboard/transactions/<id>/`) : fiche transaction, paiement associé, tentatives
(`TransactionAttempt`), et l'historique = les vraies lignes `TransactionEvent` de cette
transaction. **Aucun deuxième système d'historique** n'a été créé.

## Paiements (`payments_list`)

Construit sur `PaymentService.funnel_summary()` (déjà présent dans le code, explicitement prévu
pour un dashboard, jamais branché avant). Liste filtrable par provider/statut. N'affiche jamais
`Payment.provider_payload` ni aucune donnée brute de réponse fournisseur — uniquement des champs
structurés connus (référence, montant, statut, lien de checkout). Voir l'audit de paiement
ci-dessous pour l'alerte GeniusPay affichée sur cette page.

## Gateways (`gateways_list`)

Construit sur `GatewayManager.pool_stats()` et `GatewayManager.gateway_state()` — **aucune
nouvelle logique**, ces deux méthodes existaient déjà avec la mention explicite "for the
dashboard" dans leur docstring. `gateway_state()` a été étendu (ajout de `temperature`,
`ram_available_mb`, `storage_available_mb`, `ip_address` dans le dict retourné) pour exposer des
champs qui existent déjà sur le modèle `Gateway` mais n'étaient pas dans la projection
d'origine — changement additif, aucun appelant existant n'est affecté (vérifié : seuls les tests
et cette nouvelle vue l'appellent).

## SIM (`gateway_sims_list`)

Liste des `GatewaySim`, filtrable par opérateur/statut. Colonne "Score" : appel direct à
`GatewayScoreService.score()` (l'algorithme réel du Scheduler, non réimplémenté), avec la même
annotation `in_flight` que `GatewayManager.eligible_sims()` pour que le composant "charge" du
score reflète l'état réel — étiqueté comme indicatif dans l'interface, puisque les autres filtres
d'éligibilité ne sont pas appliqués ici (cette page ne fait qu'afficher, jamais sélectionner).

## Scheduler (`scheduler_monitor`)

Vue de consultation pure sur `TransactionAttempt`/`TransactionEvent` déjà écrits par
`Scheduler`/`ReservationManager`/`RetryManager` — **aucune logique de sélection dupliquée**.
Affiche explicitement l'état du flag `USE_NEW_TRANSACTION_ENGINE` : quand il est désactivé (valeur
par défaut), un bandeau prévient que les données affichées ne reflètent que de l'activité
historique/test, pas un flux de production réel (le chemin legacy `_select_gateway()` ne produit
ni `TransactionAttempt` ni ces `TransactionEvent`).

## Services / Forfaits (`services_list` + CRUD)

Nouveau module, calqué exactement sur le CRUD Opérateurs de l'Étape 2 : `Service.is_active`
(nouveau champ, migration `0013_service_is_active.py`), recherche/filtre, création/édition/
suppression (bloquée si des transactions existent, désactivation proposée à la place), historique
via `AuditLog` (`action__startswith='service.'`), écriture protégée par `@staff_member_required`.

## Codes USSD — vue globale (`ussd_codes_all`)

Nouveau point d'entrée listant tous les `UssdCode` de tous les opérateurs sur une seule page
(recherche, filtres opérateur/service/actif). Réutilise à l'identique les vues d'édition/
suppression/activation de l'Étape 2 — pas de deuxième implémentation.

## Logs / Événements (`audit_logs`, URL `/dashboard/audit/` inchangée)

Trois onglets sur trois modèles réels existants — **aucun nouveau modèle** :

1. **Actions admin** — `AuditLog` (comportement identique à l'ancienne page).
2. **Cycle de vie transactions** — `TransactionEvent`, filtrable par `event_type`.
3. **Webhooks** — `WebhookEvent`. Rappel affiché dans l'état vide : CinetPay ne journalise
   aujourd'hui aucun `WebhookEvent` (voir audit de paiement), seul GeniusPay le fait.

## Santé du système (`system_health`)

Réutilise **exactement** les fonctions de `apps/core/health.py` (`check_database`, `check_redis`,
`check_provider_reachable`, `gateway_summary`) et le même helper de parallélisation
(`_run_concurrently`, importé depuis `apps.core.views`) que `/api/health/` — aucune nouvelle
vérification inventée. N'affiche jamais "OK" sans avoir réellement exécuté le contrôle
correspondant à l'instant du chargement de la page. Précise explicitement que Redis est configuré
mais optionnel aujourd'hui (RQ ne reçoit aucune tâche réelle, le verrou distribué se dégrade
proprement sans lui).

## Tests

`apps/dashboard/tests.py` — 43 nouveaux tests couvrant : filtres/recherche/tri sur chaque liste,
la fiche transaction (événements + tentatives), le CRUD Services (miroir exact des tests
Opérateurs), la protection `@staff_member_required` sur les écritures, la non-exposition de
`provider_payload` sur la page Paiements, le reflet honnête de `USE_NEW_TRANSACTION_ENGINE` sur la
page Scheduler, et un test de fumée sur les 11 destinations de la sidebar. Les tests
`SystemHealthViewTests` mockent `check_redis`/`check_provider_reachable` (même discipline que
`apps.core.tests.HealthEndpointTests`) pour ne jamais dépendre d'un réseau/Redis réel en test.

## Dettes techniques connues

- Les pages Remboursements/Clients/Rapports/Notifications/Paramètres restent des stubs
  pré-existants (hors périmètre de cette demande) — leurs URLs fonctionnent toujours, elles ne
  sont simplement plus dans le menu.
- Le score affiché sur la page SIM est une approximation d'affichage (annotation `in_flight`
  reproduite localement) — un vrai calcul de sélection passerait par
  `GatewayManager.eligible_sims()` + `GatewayScoreService.rank()`, jamais dupliqués ici.
- `Gateway.host` (UUID de l'appareil) n'est pas affiché sur la page Gateways sous ce nom — la
  colonne "UUID" du tableau montre `gateway.name`, qui inclut déjà l'identifiant fonctionnel
  utilisé partout ailleurs dans le code existant (aucun champ `Gateway.uuid` séparé n'existe).
