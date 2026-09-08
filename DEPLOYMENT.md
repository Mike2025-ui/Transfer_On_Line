# 🚀 Transfer On Line - Guide de Déploiement Production

## 📋 Prérequis

- Docker >= 20.10
- docker-compose >= 2.0
- Git
- Terminal/SSH pour VPS

## 🏠 Développement Local avec Docker

### 1. Préparation

```bash
# Clone ou accédez au projet
cd Transfer_On_Line

# Assurez-vous d'utiliser .env.local pour le développement
cp backend/.env.local backend/.env
```

### 2. Démarrage des services

```bash
# Démarrer tous les services (backend, PostgreSQL, Redis)
docker-compose up -d

# Vérifier l'état
docker-compose ps

# Voir les logs
docker-compose logs -f backend
```

### 3. Initialisation de la base de données

L'initialisation se fait automatiquement via `entrypoint.sh`, mais vous pouvez aussi :

```bash
# Accéder au conteneur backend
docker-compose exec backend bash

# Lancer les migrations manuellement
python manage.py migrate

# Créer un superuser
python manage.py createsuperuser

# Charger les données initiales
python manage.py shell < scripts/seed_data.py
```

### 4. Accès local

- **Application**: http://localhost:8000
- **Admin**: http://localhost:8000/admin
- **PostgreSQL**: localhost:5432
  - User: `transfer`
  - Password: `transfer`
  - Database: `transfer_on_line`
- **Redis**: localhost:6379

### 5. Tests

```bash
# Exécuter les tests (sans le test threading SQLite)
docker-compose exec backend python manage.py test apps.accounts apps.core apps.payments

# Vérifier la configuration de production
docker-compose exec backend python manage.py check --deploy
```

## 🌐 Déploiement sur VPS

### 1. Préparation VPS

SSH sur votre VPS et exécutez :

```bash
# Mise à jour système
sudo apt-get update && sudo apt-get upgrade -y

# Installation Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Installation docker-compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Installation d'autres dépendances
sudo apt-get install -y git net-tools curl
```

### 2. Clone du projet

```bash
cd /home/your_user
git clone <your-repo-url> transfer_on_line
cd transfer_on_line
```

### 3. Configuration production

Créez le fichier secret uniquement sur le VPS. Il est ignoré par Git et ne doit
jamais être ajouté au dépôt GitHub :

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Vérifiez au minimum ces valeurs :

```env
DJANGO_SECRET_KEY=<cle-secrete-generee-aleatoirement>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=transfert-online.site,www.transfert-online.site,180.149.198.189
DJANGO_SECURE_SSL_REDIRECT=true
DATABASE_URL=postgres://transfer:<mot-de-passe-postgres>@postgres:5432/transfer_on_line
REDIS_URL=redis://redis:6379/0
CORS_ALLOWED_ORIGINS=https://transfert-online.site,https://www.transfert-online.site
CSRF_TRUSTED_ORIGINS=https://transfert-online.site,https://www.transfert-online.site
GENIUSPAY_SUCCESS_URL=https://transfert-online.site/payment/success
GENIUSPAY_ERROR_URL=https://transfert-online.site/payment/cancel
JEKO_SUCCESS_URL=https://transfert-online.site/payment/success
JEKO_ERROR_URL=https://transfert-online.site/payment/cancel
```

Renseignez aussi les vraies clés Jèko, GeniusPay et les secrets webhook dans
ce fichier uniquement sur le VPS.

### 4. Lancement sur VPS

```bash
docker compose --env-file backend/.env build
docker compose --env-file backend/.env up -d
docker compose --env-file backend/.env exec backend python manage.py check --deploy
docker compose --env-file backend/.env ps
docker compose --env-file backend/.env logs -f backend
```

Le DNS doit contenir :

```text
transfert-online.site       A       180.149.198.189
www.transfert-online.site   A       180.149.198.189
```

### 5. HTTPS avec Nginx

Installez Nginx et Certbot :

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo mkdir -p /var/www/certbot
```

Pour la première installation, copiez la configuration HTTP bootstrap :

```bash
sudo cp deploy/nginx/transfert-online.site.bootstrap.conf /etc/nginx/sites-available/transfert-online.site
sudo ln -s /etc/nginx/sites-available/transfert-online.site /etc/nginx/sites-enabled/transfert-online.site
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d transfert-online.site -d www.transfert-online.site
```

Après émission du certificat, activez la configuration HTTPS finale :

```bash
sudo cp deploy/nginx/transfert-online.site.conf /etc/nginx/sites-available/transfert-online.site
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable certbot.timer
```

### 6. Surveillance et Logs

```bash
# Voir tous les logs
docker-compose logs

# Logs backend uniquement
docker-compose logs -f backend

# Logs PostgreSQL
docker-compose logs -f postgres

# Logs Redis
docker-compose logs -f redis

# Utiliser journalctl pour Docker
sudo journalctl -u docker -f
```

## 🔄 Mise à jour du code en production

```bash
# Sur le VPS
cd /home/your_user/transfer_on_line

# Récupérer les derniers changements
git pull origin main

# Reconstruire l'image
docker-compose build backend

# Redémarrer le service
docker-compose restart backend

# Vérifier les logs
docker-compose logs -f backend
```

## 📊 Gestion des données

### Backup PostgreSQL

```bash
# Créer un backup
docker-compose exec postgres pg_dump -U transfer transfer_on_line > backup_$(date +%Y%m%d_%H%M%S).sql

# Restaurer depuis un backup
docker-compose exec -T postgres psql -U transfer transfer_on_line < backup_file.sql
```

### Récupérer les données SQLite de développement

```bash
# Avant migration, sauvegarder
cp backend/db.sqlite3 backup_sqlite_$(date +%Y%m%d_%H%M%S).db

# Exporter les données depuis SQLite en JSON
python manage.py dumpdata > data.json

# Importer dans PostgreSQL
docker-compose exec backend python manage.py loaddata data.json
```

## ⚠️ Troubleshooting

### Erreur: "database table is locked"

- Normal avec SQLite et tests multithreads
- Utiliser PostgreSQL (voir ci-dessus) pour éviter ce problème
- En local: `docker-compose exec backend python manage.py migrate --fresh`

### Port déjà utilisé

```bash
# Changer les ports dans docker-compose.yml
# Ou libérer le port existant
sudo lsof -i :8000
sudo kill -9 <PID>
```

### Conteneurs ne démarrent pas

```bash
# Vérifier les logs d'erreur
docker-compose logs

# Forcer une reconstruction
docker-compose build --no-cache

# Redémarrer tout
docker-compose restart
```

### Migrations échouées

```bash
# Exécuter les migrations manuellement
docker-compose exec backend python manage.py migrate --verbosity=2

# Voir les migrations non appliquées
docker-compose exec backend python manage.py showmigrations
```

## 🔐 Points de sécurité importants

✅ Checklist avant production :

- [ ] `DJANGO_DEBUG=false` dans `.env`
- [ ] `DJANGO_SECRET_KEY` fort et unique
- [ ] `DJANGO_SECURE_SSL_REDIRECT=true`
- [ ] HTTPS/SSL configuré (certbot)
- [ ] Domaine pointant vers VPS
- [ ] Credentials de paiement (Jèko/GeniusPay) en place
- [ ] Credentials de SMS (IKODDI) en place
- [ ] Backups automatiques configurés
- [ ] Logs centralisés (Sentry recommandé)
- [ ] Firewall configuré (ports 80, 443 ouverts)

## 📞 Support

Pour toute question ou problème :

1. Vérifier les logs: `docker-compose logs`
2. Consulter la documentation: Voir [docs/](../docs/)
3. Vérifier `.env` est correct et à jour

---

**Version**: 1.0  
**Dernière mise à jour**: 2026-09-01
