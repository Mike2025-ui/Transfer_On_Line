# Transfer On Line — Application Flutter

Application mobile de souscription et transfert de forfaits mobiles pour les opérateurs ivoiriens (Orange, MTN, Moov).

---

## 🚀 Installation & Lancement

### Prérequis
- Flutter SDK ≥ 3.0 → https://flutter.dev/docs/get-started/install
- Android Studio ou VS Code avec l'extension Flutter
- Un émulateur Android/iOS OU un téléphone physique en mode débogage USB

### Étapes

```bash
# 1. Naviguer dans le dossier
cd transfer_on_line

# 2. Installer les dépendances
flutter pub get

# 3. Vérifier que Flutter est bien configuré
flutter doctor

# 4. Lancer l'app (choisir un appareil connecté)
flutter run

# OU lancer directement sur un appareil spécifique
flutter run -d android   # Android
flutter run -d ios       # iPhone (macOS requis)
```

### Build APK (pour installer sur Android)
```bash
flutter build apk --release
# Le fichier APK sera dans : build/app/outputs/flutter-apk/app-release.apk
```

### Build iOS (macOS requis)
```bash
flutter build ios --release
```

---

## 📁 Structure du projet

```
lib/
├── main.dart                    # Point d'entrée
├── theme/
│   └── app_theme.dart           # Couleurs & thème global
├── models/
│   └── models.dart              # Modèles de données (Transaction, Notification...)
├── widgets/
│   └── widgets.dart             # Composants réutilisables
└── screens/
    ├── home_screen.dart         # Accueil + détail transaction
    ├── step1_operator.dart      # Étape 1 : Choix opérateur
    ├── step2_service.dart       # Étape 2 : Service + opération
    ├── step3_info.dart          # Étape 3 : Numéro + montant
    ├── step4_payment.dart       # Étape 4 : Récap + paiement + succès
    └── history_screen.dart      # Historique + Notifs + Profil
```

---

## ✨ Fonctionnalités

- **Accueil** : Tableau de bord avec stats, opérateurs rapides, actions rapides, transactions récentes
- **Flux opération 4 étapes** : Opérateur → Service → Informations → Paiement
- **Types de service** : Appels, Internet, SMS
- **Types d'opération** : Souscription pour moi/tiers, Transfert pour moi/tiers
- **Montants rapides** : 500, 1000, 2000, 5000, 10000 FCFA + montant personnalisé
- **Moyens de paiement** : Wave, Orange Money, MTN Money, Moov Money
- **Historique** : Filtres, stats, détail transaction
- **Notifications** : Badge compteur, marquer lu, détail
- **Profil** : Stats utilisateur, menus paramètres

---

## 🎨 Design

- Couleurs opérateurs : Orange (`#E55A00`), MTN (`#C7960A`), Moov (`#0048C8`)
- Couleur principale : Vert `#1A6E35`
- Police : **Nunito** (Google Fonts)
- Design system cohérent avec cartes blanches, coins arrondis, dégradés verts

---

## 🏢 Développé par AFRITECH-CI
