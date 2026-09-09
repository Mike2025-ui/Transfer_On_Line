# 📋 RAPPORT TECHNIQUE DE HAUTE AUTORITÉ — PROJET TRANSFER ON LINE (TOL)

---

## 1. 🎯 Objectif du Projet
**Transfer On Line (TOL)** est une plateforme unifiée et automatisée permettant la souscription et le transfert de forfaits mobiles (Internet, Pass Voix, Pass SMS, Crédit de communication) pour les principaux opérateurs de télécommunication en Côte d'Ivoire (**Orange CI**, **MTN CI**, **Moov Africa CI**).

Le système interconnecte :
1. Une **application mobile client (Flutter)** permettant aux utilisateurs finaux de sélectionner un opérateur, de configurer leur offre et d'effectuer leur paiement en toute sécurité via une passerelle de paiement multi-opérateurs (**Djeko / Jèko**).
2. Un **serveur backend central (Django REST Framework)** responsable de la gestion des comptes, de la sécurité des transactions, de l'orchestration des flux de paiement, de l'idempotence et du pilotage de la flotte de passerelles USSD.
3. Une **flotte de passerelles mobiles (Android Gateways)** embarquant des cartes SIM physiques, chargées d'écouter les transactions validées et de composer automatiquement les syntaxes USSD opérateurs pour recharger le bénéficiaire.

---

## 2. 🛠️ Stack et Technologies Utilisées

| Composant | Technologie | Rôle & Particularités |
| :--- | :--- | :--- |
| **Backend API** | **Django 5.x / Django REST Framework** | API REST, architecture découplée, gestion d'état des transactions, webhooks et sécurité. |
| **Frontend Client** | **Flutter (Dart 3.x)** | Application mobile cross-platform (iOS/Android) avec design épuré, responsive et "no-scroll" compact. |
| **Passerelle Android** | **Flutter Android Gateway (Background Service)** | Application exécutée sur terminaux physiques avec écoute en tâche de fond, heartbeat et exécution de commandes USSD. |
| **Base de données** | **PostgreSQL 16 (Alpine)** | Persistance relationnelle ACID, historique des transactions, transactions atomiques (`@db_transaction.atomic`). |
| **Cache & Verrous** | **Redis 7 (Alpine)** | Gestion du cache, verrous distribués d'idempotence et file d'attente d'exécution. |
| **Passerelle de Paiement**| **Djeko / Jèko Payments** | Agrégateur de paiement multi-moyens (Wave, Djamo, Orange Money, Moov Money, MTN Money) par redirection Web Checkout. |
| **Authentification & OTP**| **IKODDI OTP As A Service** | Envoi et validation de codes OTP par SMS et WhatsApp sans stockage sensible de codes en clair côté Django. |
| **Conteneurisation** | **Docker & Docker Compose** | Environnement unifié backend + base PostgreSQL + Redis. |

---

## 3. 🏗️ Architecture et Structure des Fichiers

```
Transfer_On_Line/
├── backend/                             # Cœur applicatif Django REST Framework
│   ├── apps/
│   │   ├── accounts/                    # Utilisateurs, profils, OTP IKODDI
│   │   ├── core/                        # Modèles centraux (Transaction, Operator, Service, Gateway, USSD)
│   │   ├── devices/                     # Exécution des transactions, attribution des SIM, heartbeat Gateway
│   │   └── payments/                    # Fournisseurs de paiement (Jèko, CinetPay, FeexPay, GeniusPay)
│   │       ├── providers/
│   │       │   ├── jeko.py              # Intégration Checkout API Djeko / Jèko
│   │       │   └── registry.py          # Registre dynamique des passerelles
│   │       └── services/
│   ├── transfer_on_line/                # Configuration Django (settings, urls, wsgi)
│   ├── Dockerfile                       # Image Docker backend
│   └── requirements.txt                 # Dépendances Python
│
├── frontend/                            # Application mobile client Flutter
│   ├── lib/
│   │   ├── main.dart                    # Point d'entrée de l'application
│   │   ├── models/                      # Modèles Transaction, Notification, Operator, Service
│   │   ├── screens/
│   │   │   ├── splash_screen.dart       # Écran de démarrage (actuellement en mode Bypass Auth)
│   │   │   ├── home_screen.dart         # Accueil, solde, raccourcis opérateurs, historique récent
│   │   │   ├── step1_operator.dart      # Étape 1 : Choix de l'opérateur (Orange, MTN, Moov)
│   │   │   ├── step2_service.dart       # Étape 2 : Type de service (Internet, Voix, SMS) & opération
│   │   │   ├── step3_info.dart          # Étape 3 : Saisie du numéro bénéficiaire et du montant
│   │   │   ├── step4_payment.dart       # Étape 4 : Récapitulatif, appel Djeko, suivi de paiement
│   │   │   ├── history_screen.dart      # Historique complet des transactions
│   │   │   └── notifications_screen.dart# Centre de notifications
│   │   ├── services/
│   │   │   ├── backend_api_service.dart # Client HTTP vers l'API Django
│   │   │   └── auth_service.dart        # Gestion des tokens JWT et requêtes OTP
│   │   ├── theme/                       # Charte graphique (AppColors, typographie Nunito)
│   │   └── widgets/                     # Composants UI compacts (GreenHeader, TolCard, TolButton)
│   └── pubspec.yaml                     # Dépendances Flutter
│
├── mobile/                              # Application Flutter Android Gateway (Exécutant USSD)
│   ├── lib/
│   │   └── services/gateway_api.dart    # Polling des transactions en attente et remontée d'état
│   └── android/                         # Configuration Android native (Permissions SMS, Téléphone, Accessibilité)
│
├── docker-compose.yml                   # Orchestration Docker (backend, postgres, redis)
├── RAPPORT.md                           # Présente documentation haute autorité
└── README.md                            # Guide de démarrage général
```

---

## 4. ✅ Fonctionnalités Développées à ce Jour

1. **Bypass Auth Local (Frontend)** :
   - Mise en place d'un contournement temporaire dans `frontend/lib/screens/splash_screen.dart` permettant d'accéder directement à l'interface sans exiger la vérification OTP IKODDI lors des phases de prototypage et de validation graphique.
2. **Design Compact et Sans Scroll ("No-Scroll Layout")** :
   - Refonte intégrale des étapes 2, 3 et 4 du tunnel de souscription pour supprimer les barres de défilement inutiles et garantir un affichage net sur un seul écran.
   - Adaptation des paddings, des tailles d'icônes et des conteneurs pour une ergonomie optimale.
3. **Mocks d'Opérateurs et de Services Intégrés** :
   - Injection sécurisée de données par défaut dans `home_screen.dart` et `step2_service.dart` pour permettre une navigation complète même en mode hors-ligne ou backend indisponible :
     - 3 Opérateurs : **Orange** (ID 1), **MTN** (ID 2), **Moov** (ID 3).
     - Services disponibles : **Pass Internet**, **Pass Voix**, **Pass SMS**, **Crédit**.
4. **Validation de l'Idempotence et Sécurité Backend** :
   - Génération côté client d'un en-tête `Idempotency-Key` unique par session d'achat pour prévenir tout double débit accidentel.
   - Architecture Transactionnelle atomique sous PostgreSQL.
5. **Gestionnaire de Passerelles Multi-Fournisseurs** :
   - Implémentation du `PaymentService` supportant plusieurs passerelles avec circuit-breaker et mécanismes de secours.
   - Module `JekoProvider` communiquant avec l'API Jèko Checkout.

---

## 5. ⏳ Fonctionnalités Restantes

1. **Activation complète du flux Web Djeko Multi-Opérateurs** :
   - Suppression du forçage de l'opérateur dans la charge utile de création de session pour laisser l'utilisateur choisir son portefeuille de paiement (Wave, Djamo, Orange Money, Moov Money, MTN Money).
2. **Rétablissement du Flux d'Authentification Réel** :
   - Réactivation de l'écran `PhoneVerificationScreen` et `OtpVerificationScreen` connectés aux endpoints IKODDI en production.
3. **Interconnexion de l'API en Ligne** :
   - Validation de la synchronisation en direct entre l'application Flutter et l'environnement de production sur `https://transfert-online.site`.
4. **Validation Automatique des Sessions de Paiement (Webhooks)** :
   - Réception et vérification des signatures HMAC du webhook Djeko (`/api/payments/jeko/webhook/`) pour basculer automatiquement la transaction de `pending` à `accepted`.
5. **Circuit de Relais USSD Gateway** :
   - Tests de transmission de bout en bout : Paiement validé -> Dispatching sur la SIM Gateway active -> Exécution USSD native -> Détection de SMS de succès.

---

## 6. 📝 Modifications Importantes Effectuées

1. **Tunnel Compact & Design Adaptatif** :
   - Remplacement des `SingleChildScrollView` superflus par des agencements `Column` / `Expanded` calibrés pour éviter les débordements de pixels.
2. **Correction du Forçage d'Opérateur dans Djeko (Étape 3 du présent plan)** :
   - Correction de `backend/apps/payments/providers/jeko.py` : l'opérateur de la ligne rechargée (`operator_code`) était incorrectement utilisé pour restreindre le champ `paymentMethod` de Jèko. Désormais, le payload omet ce paramètre par défaut, ce qui ordonne à Djeko d'afficher son menu complet de sélection à l'utilisateur.
   - Normalisation du paramètre `djeko` vers `jeko` dans le backend et le registre de paiement.
3. **Sécurisation de Branche Git** :
   - Sauvegarde de l'état de design sur la branche `bypass-auth`.
   - Création et publication de la branche officielle `feature-payment-djeko`.

---

## 7. ⚠️ Problèmes Rencontrés et Leurs Solutions

### Problème 1 : Bug d'Overflow sur Samsung Galaxy S8 (360 x 740 dp)
- **Symptôme** : Débordement de pixels jaunes/noirs (RenderFlex overflowed by X pixels) sur les téléphones à écran étroit ou allongé lors de l'affichage du clavier ou des récapitulatifs.
- **Solution** :
  - Intégration d'un test automatisé dédié `frontend/test/screens/no_scroll_layout_test.dart` simulant exactement la surface de 360x740 dp (`setSurfaceSize(const Size(360, 740))`).
  - Réduction proportionnelle des marges intérieures (`padding: const EdgeInsets.fromLTRB(12, 10, 12, 10)`), miniaturisation des icônes à 34-38 dp et utilisation de `FittedBox` sur les libellés pour empêcher les retours à la ligne intempestifs.

### Problème 2 : Erreurs CORS en Développement Local
- **Symptôme** : Les requêtes HTTP du frontend Flutter Web ou émulateur étaient bloquées par le navigateur avec l'erreur `Cross-Origin Request Blocked`.
- **Solution** :
  - Configuration dynamique de `CORS_ALLOWED_ORIGINS` et `CSRF_TRUSTED_ORIGINS` dans `backend/transfer_on_line/settings.py` acceptant par défaut `localhost:3000`, `localhost:8080`, `127.0.0.1:3000` et les domaines spécifiés via variable d'environnement sans compromettre la sécurité en production.

### Problème 3 : Forçage involontaire de MTN Money lors du paiement
- **Symptôme** : Lors du clic sur "PAYER ET SOUSCRIRE", Djeko ouvrait directement une page de paiement MTN Money au lieu de proposer le choix du moyen de paiement (Wave, Djamo, Orange, Moov, MTN).
- **Solution** :
  - Découplage dans le backend entre l'opérateur télécom cible (bénéficiaire du forfait) et le moyen de paiement utilisé par le client.
  - Suppression de l'assignation automatique de `paymentMethod` dans `paymentDetails.data` du connecteur Jèko, libérant ainsi l'affichage complet du catalogue de paiement de la passerelle.

---

## 8. 📦 Dépendances Installées

### Backend (Python / Pip)
- `django` (Framework web principal)
- `djangorestframework` (API REST et sérialiseurs)
- `django-cors-headers` (Gestion sécurisée des en-têtes CORS)
- `psycopg2-binary` (Connecteur PostgreSQL de haute performance)
- `redis` (Client de cache et locks distribués)
- `requests` (Communication HTTP avec les APIs de paiement et IKODDI)
- `pyjwt` (Gestion et vérification des jetons d'accès JWT)
- `gunicorn` (Serveur d'application WSGI de production)

### Frontend (Flutter / Pub)
- `flutter` (SDK UI)
- `google_fonts` (Typographie officielle Nunito)
- `http` (Client réseau REST)
- `url_launcher` (Ouverture sécurisée de la WebView / navigateur externe pour Djeko)
- `flutter_secure_storage` (Chiffrement local des tokens JWT)
- `local_auth` (Support de l'authentification biométrique)
- `shared_preferences` (Persistance locale de configuration)

---

## 9. 🚀 Commandes Importantes pour Lancer le Projet

### Backend
```bash
# Lancement avec Docker Compose (Base PostgreSQL, Redis, Django)
docker-compose up -d --build

# Exécution des migrations de base de données
docker-compose exec backend python manage.py migrate

# Création d'un administrateur
docker-compose exec backend python manage.py createsuperuser

# Lancement des tests unitaires
docker-compose exec backend python manage.py test
```

### Frontend (Application Client)
```bash
cd frontend

# Installation des paquets
flutter pub get

# Lancement en mode développement local
flutter run -d chrome  # Web
flutter run -d android # Mobile Android

# Lancement pointant vers l'API en ligne
flutter run --dart-define=TOL_API_BASE_URL=https://transfert-online.site/api

# Tests unitaires et tests de mise en page No-Scroll
flutter test
```

### Mobile (Passerelle USSD Android)
```bash
cd mobile
flutter pub get
flutter run -d android
```

---

## 10. 🔑 Variables d'Environnement Nécessaires (Gabarit sécurisé)

> [!NOTE]
> Aucun secret réel, clé privée ou mot de passe n'est exposé ci-dessous. Renseignez ces variables dans votre fichier `.env` sur le serveur.

```ini
# Configuration Django
DJANGO_SECRET_KEY=votre-cle-secrete-django
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=transfert-online.site,api.transfert-online.site,180.149.198.189
DJANGO_SECURE_SSL_REDIRECT=true

# Bases de données & Cache
DATABASE_URL=postgres://transfer:motdepasse@postgres:5432/transfer_on_line
REDIS_URL=redis://redis:6379/0

# Sécurité Web & Domaines
CORS_ALLOWED_ORIGINS=https://transfert-online.site
CSRF_TRUSTED_ORIGINS=https://transfert-online.site

# Passerelle Djeko / Jèko
JEKO_API_KEY=votre-cle-api-jeko
JEKO_API_KEY_ID=votre-cle-api-id-jeko
JEKO_STORE_ID=votre-store-id-jeko
JEKO_BASE_URL=https://api.jeko.africa
JEKO_SUCCESS_URL=https://transfert-online.site/payment/success
JEKO_ERROR_URL=https://transfert-online.site/payment/cancel
JEKO_WEBHOOK_SECRET=votre-secret-webhook-jeko
JEKO_TIMEOUT_SECONDS=20

# Authentification OTP IKODDI
IKODDI_API_KEY=votre-cle-api-ikoddi
IKODDI_BASE_URL=https://api.ikoddi.com/api/v1
IKODDI_GROUP_ID=votre-group-id-ikoddi
IKODDI_OTP_APP_ID=votre-app-id-ikoddi
IKODDI_TIMEOUT_SECONDS=20
```

---

## 11. 🧭 État Actuel, Procédure de Compilation Distante (VPS) et Prochaines Étapes

### A. État Actuel
- **Design compact & No-Scroll** : validé et sécurisé sur la branche `bypass-auth`.
- **Branche de travail** : `feature-payment-djeko` créée et suivie sur GitHub.
- **Passerelle Djeko / Jèko Multi-Opérateurs** :
  - Découplage de la charge utile de paiement : `paymentMethod` n'est plus forcé avec l'opérateur de recharge, libérant ainsi l'écran de sélection multi-moyens (Wave, Djamo, Orange Money, Moov Money, MTN Money).
  - Normalisation de l'identifiant `djeko` vers `jeko` dans l'API Django et le registre des passerelles.

### B. Procédure de Compilation Distante sur le VPS (180.149.198.189)
Afin de préserver les ressources de la machine locale et d'utiliser la bande passante et l'environnement Flutter du serveur distant, la compilation de l'APK de release s'exécute directement sur le VPS :

1. **Connexion au serveur distant** :
   ```bash
   ssh root@180.149.198.189
   # Ou avec votre utilisateur dédié si non-root :
   # ssh <utilisateur>@180.149.198.189
   ```

2. **Mise à jour du dépôt Git sur le serveur** :
   ```bash
   cd /chemin/vers/Transfer_On_Line
   git fetch origin
   git checkout feature-payment-djeko
   git pull origin feature-payment-djeko
   ```

3. **Compilation de l'application cliente Frontend** :
   ```bash
   cd frontend
   flutter pub get
   flutter build apk --release --dart-define=TOL_API_BASE_URL=https://transfert-online.site
   ```

4. **Emplacement de l'APK final généré sur le serveur** :
   Le fichier binaire produit se situe précisément à l'emplacement suivant :
   `frontend/build/app/outputs/flutter-apk/app-release.apk`

5. **Rapatriement de l'APK vers votre PC local** (depuis le terminal de votre PC portable) :
   ```bash
   scp root@180.149.198.189:/chemin/vers/Transfer_On_Line/frontend/build/app/outputs/flutter-apk/app-release.apk ./TransferOnLine-release.apk
   ```

### C. Prochaines Étapes Immédiates
1. Déployer et exécuter la compilation sur le VPS via les commandes ci-dessus.
2. Installer l'APK sur smartphone de test Android.
3. Vérifier le clic sur "PAYER ET SOUSCRIRE" : la WebView Djeko doit afficher l'écran complet de sélection avec Wave, Djamo, Orange Money, Moov Money et MTN Money.
4. Effectuer une transaction réelle de 100 FCFA pour valider la chaîne complète jusqu'au webhook.
