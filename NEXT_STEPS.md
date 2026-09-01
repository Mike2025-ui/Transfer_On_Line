# 🚀 NEXT STEPS - Ce qu'il faut faire maintenant

## Immédiat (Maintenant)

### 1️⃣ Tester Docker localement

```bash
# En Windows PowerShell ou Terminal
cd C:\Users\TOSHIBA\Desktop\Transfer_On_Line

# Démarrer tous les services (backend + postgres + redis)
docker-compose up -d

# Attendre ~40 secondes pour l'initialisation
# Vérifier que tout démarre
docker-compose ps

# Vous devriez voir 3 containers avec status "Up":
# - transfer_on_line_backend
# - transfer_on_line_postgres
# - transfer_on_line_redis
```

### 2️⃣ Vérifier l'application

```
- Frontend: http://localhost:8000
- Admin: http://localhost:8000/admin
- Superuser: admin / changeme (par défaut)
```

### 3️⃣ Tester les paiements Jèko

```bash
docker-compose exec backend python -c "
from apps.payments.providers.jeko import JekoProvider
provider = JekoProvider()
stores = provider.get_stores()
print(f'✅ Jèko API working: {len(stores)} stores found')
"
```

### 4️⃣ Vérifier les logs

```bash
# Si quelque chose ne marche pas
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f redis
```

### 5️⃣ Arrêter quand fait

```bash
docker-compose down  # Arrête les services mais garde les données
```

---

## Court terme (Cette semaine)

### ✅ Étape 1: Mettre à jour la SECRET_KEY

```bash
# Générer une nouvelle clé sécurisée
cd backend
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Copier la valeur générée
# Éditer backend/.env et remplacer DJANGO_SECRET_KEY
```

### ✅ Étape 2: Vérifier que Jèko API est activé

- Aller sur https://cockpit.jeko.africa
- Vérifier que votre compte est "Enabled for API access"
- Si NON, contacter support Jèko
- Si OUI, vous avez déjà les credentials dans `.env`

### ✅ Étape 3: Migrer SQLite → PostgreSQL (optionnel local)

```bash
# Si vous voulez basculer votre DB locale de SQLite à PostgreSQL
docker-compose exec backend python migrate_sqlite_to_postgres.py
```

---

## Moyen terme (Avant production)

### ✅ Étape 4: Préparer le VPS

1. Louer un VPS (OVH, Linode, DigitalOcean, etc.)
2. Récupérer l'IP du VPS
3. Acheter un domaine (si pas déjà fait)
4. Pointer le DNS vers le VPS

### ✅ Étape 5: Déployer sur VPS

```bash
# Sur votre PC
./deploy-vps.sh <IP_VPS> <USER_VPS>

# Exemple:
# ./deploy-vps.sh 192.168.1.100 ubuntu
```

### ✅ Étape 6: Configurer VPS pour production

```bash
# SSH sur le VPS
ssh user@vps-ip

# Éditer le fichier .env pour production
cd ~/transfer_on_line
nano backend/.env

# Mettre à jour:
# - DJANGO_SECRET_KEY
# - DJANGO_ALLOWED_HOSTS (votre domaine)
# - JEKO_API_KEY, JEKO_API_KEY_ID, JEKO_STORE_ID
# - GENIUSPAY_API_KEY, GENIUSPAY_API_SECRET
# - EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
# - Tous les autres credentials
```

### ✅ Étape 7: Configurer HTTPS/SSL

```bash
# Sur le VPS
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Créer la config Nginx
sudo nano /etc/nginx/sites-available/transfer_on_line
# (Copier le contenu de la section Nginx dans DEPLOYMENT.md)

# Générer le certificat SSL
sudo certbot --nginx -d votre-domaine.com -d www.votre-domaine.com
```

### ✅ Étape 8: Redémarrer et vérifier

```bash
# Sur le VPS
cd ~/transfer_on_line
docker-compose restart

# Vérifier les services
docker-compose ps

# Vérifier les logs
docker-compose logs -f backend

# Tester l'accès
curl https://votre-domaine.com
```

---

## Long terme (Après déploiement initial)

### 📊 Monitoring & Alerting

```bash
# Optionnel: Configurer Sentry pour error tracking
# 1. Créer un compte sur https://sentry.io
# 2. Créer un projet Django
# 3. Copier le SENTRY_DSN dans backend/.env
# 4. Redémarrer: docker-compose restart backend
```

### 📦 Backups automatiques

```bash
# Créer un cron job pour daily backups
crontab -e

# Ajouter:
0 2 * * * cd ~/transfer_on_line && docker-compose exec -T postgres pg_dump -U transfer transfer_on_line > ~/backups/backup_$(date +\%Y\%m\%d).sql
```

### 🔄 Updates du code

```bash
# Quand il y a un nouveau commit
cd ~/transfer_on_line
git pull origin main
docker-compose build backend
docker-compose restart backend
```

---

## 📋 Checklist rapide

### Local (Maintenant)

- [ ] `docker-compose up -d` fonctionne
- [ ] Application accessible sur http://localhost:8000
- [ ] Admin panel fonctionne
- [ ] Jèko API répond

### VPS (Cette semaine)

- [ ] VPS loué et IP connue
- [ ] Domaine acheté et pointant vers VPS
- [ ] Déploiement réussi
- [ ] HTTPS activé et fonctionnel

### Production (Avant go-live)

- [ ] Tous les credentials testés et valides
- [ ] Backups configurés
- [ ] Monitoring (Sentry) optionnel mais recommandé
- [ ] Firewall configuré (ports 80, 443)
- [ ] DNS propagé (vérifier: ping votre-domaine.com)

---

## 🔗 Fichiers importants à connaître

| Fichier                   | Usage                                       |
| ------------------------- | ------------------------------------------- |
| `docker-compose.yml`      | Orchestration des services                  |
| `backend/.env`            | Configuration (à adapter par environnement) |
| `backend/.env.local`      | Config pour développement                   |
| `backend/.env.production` | Template pour production                    |
| `backend/Dockerfile`      | Image Docker                                |
| `backend/entrypoint.sh`   | Script d'initialisation                     |
| `DEPLOYMENT.md`           | Guide complet 200+ lignes                   |
| `DOCKER_README.md`        | Documentation Docker                        |
| `PRODUCTION_READY.md`     | Status final                                |

---

## 🆘 Si quelque chose ne marche pas

### Erreur: Docker n'est pas installé

```
Solution: Installer Docker Desktop pour Windows
https://www.docker.com/products/docker-desktop
```

### Erreur: Port 8000 déjà utilisé

```bash
# Trouver le processus
netstat -ano | findstr :8000

# Changer le port dans docker-compose.yml
# Ligne "8000:8000" → "8001:8000"
```

### Erreur: "database table is locked"

```bash
# Arrêter et recommencer
docker-compose down -v
docker-compose up -d
```

### Erreur: Jèko API "business_not_enabled_for_api_access"

```
Solution: Contacter support Jèko
Email: support@jeko.africa
Votre account doit être "enabled for API access"
```

---

## 💡 Tips & Tricks

### Voir en temps réel les logs

```bash
docker-compose logs -f backend
```

### Accéder à la DB PostgreSQL directement

```bash
docker-compose exec postgres psql -U transfer -d transfer_on_line
```

### Réinitialiser complètement (perdre les données)

```bash
docker-compose down -v
docker-compose up -d
# Tout sera réinitialisé et reseedé
```

### Exporter la base de données

```bash
docker-compose exec postgres pg_dump -U transfer transfer_on_line > backup.sql
```

---

## 📞 Support immédiat

**Si vous êtes bloqué sur :**

1. Local avec Docker: Consulter `DOCKER_README.md`
2. Configuration: Consulter `DEPLOYMENT.md`
3. Erreurs Jèko: https://docs.jeko.africa
4. Erreurs IKODDI: https://docs.ikoddi.com
5. Erreurs GeniusPay: https://docs.geniuspay.ci

---

## 🎯 Ordre d'exécution recommandé

```
Jour 1:
  1. Tester Docker localement
  2. Générer nouvelle SECRET_KEY
  3. Vérifier que Jèko API est activé

Jour 2-3:
  4. Louer VPS
  5. Acheter domaine
  6. Déployer sur VPS test

Jour 4-7:
  7. Configurer HTTPS
  8. Tester paiements réels
  9. Configurer monitoring
  10. Lancer en production

En continu:
  11. Surveiller les logs
  12. Faire des backups
  13. Déployer les updates
```

---

**Prochaine action**: Ouvrir un terminal et exécuter:

```bash
cd C:\Users\TOSHIBA\Desktop\Transfer_On_Line
docker-compose up -d
docker-compose ps
```

Puis accéder à http://localhost:8000 pour vérifier que tout marche ! 🚀

---

**Version**: 1.0  
**Date**: 2026-09-01  
**Statut**: Ready to Deploy
