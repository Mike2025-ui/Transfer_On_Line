# ⚡ CHECKLIST - Ce que VOUS devez faire maintenant

L'intégration OTP Aion Messaging est **complète côté code**. Voici ce qu'il vous reste à faire:

---

## 1️⃣ Créer un compte Aion Messaging et obtenir les clés API

### Étape 1: Inscription

1. Allez sur https://aionmessaging.com
2. Cliquez sur "Sign Up" ou "Create Account"
3. Remplissez le formulaire avec:
   - Email professionnel
   - Mot de passe sécurisé
   - Nom de l'entreprise: "Transfer On Line"
   - Pays: Côte d'Ivoire

### Étape 2: Générer la clé API

1. Connectez-vous au Dashboard Aion
2. Allez à **Settings → API Keys** (ou **Dashboard → API Keys**)
3. Cliquez sur **"Generate New Key"**
4. Donnez un nom: `transfer_on_line_backend`
5. Copiez la clé: `sk_sandbox_...` ou `sk_live_...`
6. **Sauvegardez-la en sécurité** (vous ne pourrez pas la voir deux fois)

### Étape 3: Créer et approuver un Sender ID

1. Allez à **Dashboard → Sender IDs**
2. Cliquez sur **"Create New Sender ID"**
3. Entrez: `TransferOnLine` ou `TOLMONEY` (max 11 caractères, alphanumériques)
4. Type: SMS
5. Cliquez sur "Submit for Approval"
6. **Attendez l'approbation** (peut prendre 24-48h)
7. Une fois approuvé, le statut changera à "Active"

### Résultat attendu:

```
AION_API_KEY=sk_sandbox_WWyBpGpr2IwNEIPVG7fDIZlKIV6WVFjg  (ou sk_live_...)
AION_SENDER_ID=TransferOnLine  (approuvé et actif)
AION_BASE_URL=https://aionmessaging.com/api/v1/
```

---

## 2️⃣ Configurer les variables d'environnement

### Pour le développement local (Windows):

#### Option A: Via fichier .env (recommandé)

1. Ouvrez `backend/.env` dans VS Code
2. Trouvez la section "Aion Messaging" (vers la fin)
3. Remplacez les valeurs par celles obtenues:

```bash
# Aion Messaging - OTP Provider
AION_API_KEY=sk_sandbox_VOtre_Clé_API_Réelle
AION_SENDER_ID=TransferOnLine
AION_BASE_URL=https://aionmessaging.com/api/v1/
```

4. Sauvegardez (Ctrl+S)
5. Le Django se relancera automatiquement (si en dev)

#### Option B: Variables d'environnement Windows

1. Ouvrez Command Prompt (Admin)
2. Exécutez:

```cmd
setx AION_API_KEY "sk_sandbox_VOtre_Clé_API_Réelle"
setx AION_SENDER_ID "TransferOnLine"
setx AION_BASE_URL "https://aionmessaging.com/api/v1/"
```

3. Redémarrez le terminal/IDE pour que les changements prennent effet

### Pour la production:

1. Allez sur votre plateforme d'hébergement (Docker, Heroku, AWS, etc.)
2. Configurez les variables d'environnement:
   - `AION_API_KEY` = votre clé
   - `AION_SENDER_ID` = votre sender ID
   - `AION_BASE_URL` = https://aionmessaging.com/api/v1/

---

## 3️⃣ Tester l'intégration

### Test 1: Vérifier que les variables sont chargées

```bash
# Dans la console Django
python manage.py shell
>>> from django.conf import settings
>>> print(settings.AION_API_KEY)
sk_sandbox_...  # Doit afficher votre clé, pas vide!
>>> print(settings.AION_SENDER_ID)
TransferOnLine  # Doit afficher votre sender ID
```

### Test 2: Tester l'endpoint OTP Request via curl

```bash
curl -X POST http://localhost:8000/api/auth/otp/request/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number":"0745123456"}'
```

**Réponse attendue (succès):**

```json
{
  "status": "sent",
  "verification_id": 42
}
```

**Réponse si erreur:**

```json
{
  "error": "Aion Messaging is not configured"
}
```

→ Vérifiez que les variables d'environnement sont correctement définies

### Test 3: Tester via Postman ou Insomnia

1. Créez une nouvelle requête POST
2. URL: `http://localhost:8000/api/auth/otp/request/`
3. Headers:
   ```
   Content-Type: application/json
   ```
4. Body (JSON):
   ```json
   {
     "phone_number": "0745123456"
   }
   ```
5. Cliquez "Send"
6. Vérifiez la réponse

### Test 4: Tester sur le téléphone

1. Lancez l'app Flutter
2. Accédez à l'écran de vérification (première connexion)
3. Entrez un numéro: `07XXXXXXXX` (10 chiffres)
4. Cliquez "CONTINUER"
5. **Vérifiez que vous recevez un SMS** avec un code
6. Entrez le code (6 chiffres)
7. Cliquez "VALIDER"
8. Vous devriez être connecté

### Logs à vérifier après test:

```bash
# Backend - Django console devrait afficher:
[INFO] Aion Messaging OTP started for +2250745123456 (verification_id=42)

# Si erreur:
[WARNING] Aion Messaging verify/start failed for +2250745123456: ...
```

---

## 4️⃣ Valider la configuration complète

### Checklist de validation:

- [ ] **Aion Messaging Account:**
  - [ ] Compte créé et connecté
  - [ ] API Key générée (sk*sandbox*... ou sk*live*...)
  - [ ] Sender ID approuvé (statut "Active")

- [ ] **Backend Django:**
  - [ ] `.env` file mis à jour avec les 3 variables
  - [ ] Ou variables d'environnement système configurées
  - [ ] `python manage.py shell` affiche les bonnes valeurs

- [ ] **API Endpoints:**
  - [ ] `/api/auth/otp/request/` retourne `{"status": "sent", "verification_id": ...}`
  - [ ] SMS reçu dans les 5 secondes
  - [ ] `/api/auth/otp/verify/` fonctionne avec code correct

- [ ] **Frontend:**
  - [ ] App starts without OTP service errors
  - [ ] Phone input accepts 10-digit numbers
  - [ ] SMS received after clicking "CONTINUER"
  - [ ] Code input accepts 6 digits
  - [ ] Code verification works and logs in user
  - [ ] Timer works: "Renvoyer (60s)" → "Renvoyer le code"

- [ ] **Error Handling:**
  - [ ] Invalid phone shows error message
  - [ ] Invalid code shows "Code invalide ou expiré"
  - [ ] Too many attempts shows error
  - [ ] Offline/network errors handled gracefully

---

## 5️⃣ Optimisations optionnelles (selon vos besoins)

### A. Personnaliser le message SMS

Actuellement, Aion utilise un template default. Pour personnaliser:

1. Allez au Dashboard Aion → Templates (s'il existe)
2. Créez un template SMS: `Your OTP code is: {code}. Valid for 10 minutes.`
3. Mettez à jour l'API request pour utiliser ce template

### B. Ajouter des logs additionnels

Modifiez `backend/apps/accounts/services.py`:

```python
logger.info(f'OTP sent to {phone_number} via Aion, verification_id={verification_id}')
```

### C. Tester avec plusieurs numéros

1. Demandez des codes pour différents numéros
2. Vérifiez les SMS sur plusieurs téléphones
3. Testez le resend après 60 secondes

### D. Configuration de production

Pour switcher de sandbox à production:

1. Dans le Dashboard Aion: activez "Live Mode"
2. Générée une clé API live: `sk_live_...`
3. Remplacez la clé dans `.env` ou variables de production
4. Continuez à utiliser le même Sender ID

---

## ❓ FAQ

**Q: Je n'ai pas reçu de SMS après avoir cliqué "CONTINUER"**
A:

1. Vérifiez que votre Sender ID est "Active" dans Aion
2. Vérifiez que votre numéro n'est pas dans la liste noire
3. Vérifiez les logs Django: `[WARNING] Aion Messaging verify/start failed...`
4. Attendez 5-10 secondes (peut être lent la première fois)

**Q: "Aion Messaging is not configured" error**
A:

1. Les variables d'environnement ne sont pas définies
2. Redémarrez votre IDE/terminal après `setx`
3. Vérifiez: `python manage.py shell` → `from django.conf import settings; print(settings.AION_API_KEY)`

**Q: Le code expire avant que j'aie le temps de le taper**
A:

1. Code expire après 10 minutes (non configurable chez Aion)
2. Vous pouvez demander un nouveau code via "Renvoyer le code" après 60s

**Q: Comment activer le mode "live" pour la production?**
A:

1. Dans Aion Dashboard → Settings → Mode de paiement
2. Switchez de "Sandbox" à "Live"
3. Générez une clé API live: `sk_live_...`
4. Remplacez `AION_API_KEY` par la nouvelle clé

**Q: Puis-je tester avec un numéro fictif?**
A:

1. En mode Sandbox: oui, n'importe quel numéro fonctionne
2. En mode Live: vous devez utiliser des vrais numéros (SMS payant)
3. Code test default en Sandbox: contactez Aion pour code test spécifique

---

## 📞 Support et Débogage

### Si quelque chose ne fonctionne pas:

1. **Vérifiez les logs Django:**

   ```bash
   cd backend
   python manage.py runserver
   # Recherchez les erreurs "[WARNING]" ou "[ERROR]" dans la sortie
   ```

2. **Testez directement via curl:**

   ```bash
   curl -X POST http://localhost:8000/api/auth/otp/request/ \
     -H "Content-Type: application/json" \
     -d '{"phone_number":"0745123456"}' \
     -v
   ```

3. **Consultez Aion Dashboard:**
   - Dashboard → Messages → Vérifiez si SMS envoyé
   - Dashboard → Webhooks → Vérifiez les erreurs de livraison

4. **Contacts d'aide:**
   - Aion Support: support@aionmessaging.com
   - Documentataion: https://aionmessaging.com/api/v1/

---

## ✅ Félicitations!

Une fois ces étapes complétées:

- ✅ OTP fonctionnelle end-to-end
- ✅ SMS envoyés et reçus
- ✅ Vérification et login fonctionnels
- ✅ Ready for production deployment

**Prochaines étapes:**

1. Déployer le backend en production
2. Générer clé API live Aion
3. Mettre à jour frontend release app
4. Lancer vers app stores (Google Play, App Store)

---

📅 **Date:** 2026-08-27  
✍️ **Créé par:** Intégration Aion Messaging  
📍 **Statut:** À faire maintenant!
