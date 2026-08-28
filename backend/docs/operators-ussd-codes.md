# Opérateurs et codes USSD

Ce document décrit le modèle `UssdCode` (`apps/core/models.py`) et la façon dont
les codes USSD, autrefois codés en dur dans `apps.core.serializers.build_ussd_code()`,
sont maintenant entièrement pilotés depuis la base de données.

## Modèle

`UssdCode` associe un `Operator` (obligatoire) et, optionnellement, un `Service`
à un `template` de composition USSD.

- `service=None` signifie "code générique, applicable à toutes les prestations
  de cet opérateur" — c'est le repli utilisé quand aucune ligne spécifique au
  service n'est active.
- `is_active` permet de désactiver un code sans le supprimer (conserve
  l'historique, permet de le réactiver).
- Une contrainte d'unicité garantit qu'il ne peut jamais exister plus d'une
  ligne **active** pour un même couple `(operator, service)` — les lignes
  désactivées peuvent coexister librement (historique).

## Ordre de résolution

Pour une transaction donnée (`tx.operator`, `tx.service`), `build_ussd_code(tx)` :

1. Cherche une ligne active `(operator, service)` exacte.
2. À défaut, cherche une ligne active `(operator, service=None)` (le repli
   opérateur).
3. Si rien n'est trouvé, lève `UssdCodeNotConfigured` — **aucun repli codé en
   dur ne subsiste** : composer un code deviné sur une transaction financière
   réelle serait plus dangereux qu'un échec explicite.

`resolve_ussd_code(operator, service)` fait la même recherche mais ne lève
jamais (retourne `None`) — utilisé pour les vérifications préalables (avant
tout appel à un fournisseur de paiement, voir `ExecuteTransactionView`).

## Variables de template

Un `template` peut contenir les variables suivantes, entre accolades :

| Variable | Source | Toujours disponible ? |
|---|---|---|
| `{numero}` | `tx.phone_number` | Oui |
| `{montant}` | `int(tx.amount)` | Oui |
| `{forfait}` | `tx.service.name` | Oui |
| `{pin}` | — | **Non, voir limitation ci-dessous** |

`UssdCode.render(context)` substitue ces variables. Une variable inconnue dans
le template (ex. `{bogus}`) lève `ValueError` — erreur de configuration, à
corriger dans le dashboard. Une variable connue mais absente du contexte
fourni lève `UssdCodeRenderError`.

### Limitation connue : `{pin}`

Le moteur de templates accepte syntaxiquement `{pin}` (c'était un requirement
explicite), mais **aucune source de données n'existe aujourd'hui** nulle part
dans le schéma pour peupler cette variable — ni sur `Transaction`, ni ailleurs.
Un template qui l'utilise lèvera `UssdCodeRenderError` à chaque génération
réelle de code, puisque le contexte ne contiendra jamais `pin`.

Ce n'est pas un oubli silencieux : c'est documenté ici précisément pour que ce
soit visible. Si un besoin réel de PIN (ex. recharge par carte à gratter)
apparaît, une phase future devra ajouter une collecte de cette donnée en amont
(ce qui nécessiterait très probablement une modification du Client Flutter,
hors périmètre de ce module).

## Ajouter un mapping opérateur/service depuis le dashboard

Voir `/dashboard/operateurs/` : créer/modifier un opérateur, puis depuis sa
fiche, gérer ses codes USSD (`/dashboard/operateurs/<id>/codes/`). Chaque
création/modification/activation/désactivation est tracée dans le journal
d'audit (`AuditLog`, visible sur `/dashboard/operateurs/historique/`).

Depuis l'Étape 3, une vue transverse `/dashboard/codes-ussd/` liste les codes
de **tous** les opérateurs sur une seule page (recherche, filtres opérateur/
service/actif) — un point d'entrée direct depuis le menu principal, en plus du
détour par une fiche opérateur. Elle réutilise exactement les mêmes vues de
création/édition/suppression/activation : aucune deuxième implémentation du
CRUD. Voir `backend/docs/dashboard-modernization.md` pour le reste du Back
Office (Transactions, Paiements, Gateways, SIM, Scheduler, Services/Forfaits,
Logs/Événements, Santé du système).

## Migrations

- `0011_ussdcode.py` — schéma (modèle `UssdCode`, champ `Operator.is_active`).
- `0012_seed_ussd_codes.py` — peuple `UssdCode` pour chaque `(Operator, Service)`
  existant au moment de la migration, en reproduisant exactement la sortie de
  l'ancienne fonction codée en dur (`*123*{numero}*{montant}#` pour les
  services de type "transfert", `*456*{montant}#` sinon), plus un repli
  opérateur par défaut. C'est ce qui garantit qu'appliquer ces migrations sur
  une base de production existante ne change strictement rien au comportement
  observable — voir les tests `UssdCodeMigrationSeedTests` dans
  `apps/core/tests.py` pour la preuve automatisée.

**Important** : un opérateur ou un service créé *après* ces migrations (via
l'API publique, `get_or_create` sur des noms envoyés par un client, ou depuis
le dashboard) n'a **aucun** code USSD configuré par défaut. `ExecuteTransactionView`
refuse toute transaction pour un couple `(operator, service)` non configuré
(réponse `400`, avant tout appel au fournisseur de paiement) — configurer le
code USSD est une étape obligatoire avant qu'un nouvel opérateur/service ne
puisse traiter de vraies transactions.
