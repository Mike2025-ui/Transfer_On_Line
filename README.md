# Transfer On Line

Application de souscription et transfert de forfaits avec Flutter, Django REST Framework, PostgreSQL, Redis, CinetPay et une Gateway Android chargée d'exécuter les codes USSD après confirmation de paiement.

## Architecture

- `frontend/` : application Flutter client.
- `backend/` : API Django REST Framework et dashboard admin.
- `mobile/` : application Flutter Android Gateway pour heartbeat, lecture des transactions validées et exécution USSD.
- `postgres` : base de données de production.
- `redis` : file et infrastructure cache/worker.

## Paiement

CinetPay est l'unique fournisseur de paiement. Le client crée une transaction via `POST /api/transactions/execute/`, l'API initialise le checkout CinetPay et retourne `checkout_url`. La Gateway Android ne reçoit une transaction dans `GET /api/transactions/pending/` qu'après notification CinetPay validée par l'endpoint `POST /api/payments/cinetpay/notify/`.

## Lancement backend

1. Copier `backend/.env.example` vers `backend/.env`.
2. Renseigner les clés CinetPay et les domaines de production.
3. Lancer `docker compose up --build`.
4. Appliquer les migrations avec `docker compose run --rm backend python manage.py migrate`.

## Flutter

Passer l'URL backend au build :

```bash
flutter build apk --release --dart-define=TOL_API_BASE_URL=https://api.example.com/api
```

La même variable est utilisée par `frontend/` et `mobile/`.
