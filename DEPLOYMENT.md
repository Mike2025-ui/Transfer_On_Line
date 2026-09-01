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

### 3. Configuration Production

```bash
# Copier le template de production
cp backend/.env backend/.env.production

# Éditer la configuration
nano backend/.env.production
```

**Paramètres à modifier :**

```env
# 🔐 Sécurité
ENVIRONMENT=production
DJANGO_SECRET_KEY=<votre-clé-secrète-forte>
DJANGO_DEBUG=false

# 🌍 Domaine
DJANGO_ALLOWED_HOSTS=votre-domaine.com,www.votre-domaine.com
DJANGO_SECURE_SSL_REDIRECT=true

# 🗄️ Base de données (si différente du default docker)
DATABASE_URL=postgresql://transfer:PASSWORD@postgres:5432/transfer_on_line

# 📧 Email (optionnel mais recommandé)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# 💳 Paiements (Jèko & GeniusPay)
JEKO_API_KEY=your_jeko_api_key
JEKO_API_KEY_ID=your_jeko_key_id
JEKO_STORE_ID=your_jeko_store_id
GENIUSPAY_API_KEY=your_geniuspay_key
GENIUSPAY_API_SECRET=your_geniuspay_secret

# 📱 OTP (IKODDI)
IKODDI_API_KEY=your_ikoddi_key
IKODDI_GROUP_ID=your_ikoddi_group
IKODDI_OTP_APP_ID=your_ikoddi_app_id

# 🔗 URLs de callback
GENIUSPAY_SUCCESS_URL=https://votre-domaine.com/payment/success
GENIUSPAY_ERROR_URL=https://votre-domaine.com/payment/cancel
```

### 4. Lancement sur VPS

```bash
# Utiliser le .env.production
cp backend/.env.production backend/.env

# Construire les images
docker-compose build

# Démarrer les services
docker-compose up -d

# Vérifier les logs
docker-compose logs -f backend

# Vérifier l'état
docker-compose ps
```

### 5. HTTPS avec Nginx (Recommandé)

Installez Nginx pour proxy HTTPS :

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Créer config Nginx
sudo nano /etc/nginx/sites-available/transfer_on_line
```

Contenu du fichier de config :

```nginx
upstream backend {
    server localhost:8000;
}

server {
    listen 80;
    server_name votre-domaine.com www.votre-domaine.com;
    client_max_body_size 100M;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /home/your_user/transfer_on_line/backend/staticfiles/;
    }

    location /media/ {
        alias /home/your_user/transfer_on_line/backend/media/;
    }
}
```

Puis :

```bash
# Activer la config
sudo ln -s /etc/nginx/sites-available/transfer_on_line /etc/nginx/sites-enabled/

# Tester la config
sudo nginx -t

# Redémarrer Nginx
sudo systemctl restart nginx

# Installer SSL (Let's Encrypt)
sudo certbot --nginx -d votre-domaine.com -d www.votre-domaine.com

# Vérifier renouvellement SSL auto
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
