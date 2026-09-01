# 🐳 Transfer On Line - Docker Setup

Ce projet est complètement containerisé pour faciliter le déploiement local et en production.

## 📦 Structure Docker

```
Transfer_On_Line/
├── docker-compose.yml          # Orchestration des conteneurs
├── backend/
│   ├── Dockerfile             # Image Docker du backend
│   ├── entrypoint.sh          # Script d'initialisation
│   ├── .env                   # Configuration production (PostgreSQL)
│   ├── .env.local             # Configuration locale (SQLite) - développement
│   └── requirements.txt        # Dépendances Python
├── .dockerignore               # Fichiers à ignorer dans l'image
├── start.sh                   # Script de démarrage local
├── deploy-vps.sh              # Script de déploiement VPS
└── DEPLOYMENT.md              # Guide complet de déploiement
```

## 🚀 Démarrage rapide

### Développement local

```bash
# 1. Démarrer les conteneurs
docker-compose up -d

# 2. Vérifier que tout fonctionne
docker-compose ps

# 3. Accéder à l'application
# Frontend: http://localhost:8000
# Admin: http://localhost:8000/admin
```

### Production sur VPS

```bash
# 1. Préparer le VPS
./deploy-vps.sh <VPS_IP> <VPS_USER>

# 2. Configurer les paramètres
ssh user@vps_ip
nano ~/transfer_on_line/backend/.env

# 3. Redémarrer les services
cd ~/transfer_on_line
docker-compose restart
```

## 🔧 Services Docker

### Backend (Django)

- **Image**: Python 3.12 slim
- **Port**: 8000
- **Commande**: gunicorn + migrations + collectstatic

### PostgreSQL

- **Image**: postgres:16-alpine
- **Port**: 5432
- **Données persistantes**: Volume `postgres_data`
- **Paramètres**: UTF-8, locale US

### Redis

- **Image**: redis:7-alpine
- **Port**: 6379
- **Données persistantes**: Volume `redis_data`

## 📝 Fichiers de configuration

### `.env.local` (Développement)

- SQLite pour la base de données
- DEBUG=true
- Services de test

### `.env` (Production - Docker)

- PostgreSQL
- DEBUG=false
- HTTPS activé
- Configuration pour VPS

## 🔄 Cycle de vie des migrations

### Développement

```bash
# SQLite en local
docker-compose exec backend python manage.py migrate

# Créer un superuser
docker-compose exec backend python manage.py createsuperuser

# Charger les données
docker-compose exec backend python manage.py loaddata fixtures/data.json
```

### Migration SQLite → PostgreSQL

```bash
# Exporter les données de SQLite
docker-compose exec backend python migrate_sqlite_to_postgres.py

# Ou manuellement:
python manage.py dumpdata > data.json
docker-compose exec backend python manage.py loaddata data.json
```

## 📊 Gestion des données

### Backups

```bash
# PostgreSQL
docker-compose exec postgres pg_dump -U transfer transfer_on_line > backup.sql

# Redis
docker cp transfer_on_line_redis:/data/dump.rdb ./redis_backup.rdb
```

### Restauration

```bash
# PostgreSQL
docker-compose exec -T postgres psql -U transfer transfer_on_line < backup.sql

# Redis
docker cp ./redis_backup.rdb transfer_on_line_redis:/data/dump.rdb
docker-compose restart redis
```

## 🧹 Maintenance

### Logs

```bash
# Tous les services
docker-compose logs -f

# Uniquement backend
docker-compose logs -f backend

# Avec limites de temps
docker-compose logs --tail=100 -f backend
```

### Arrêt et redémarrage

```bash
# Arrêter sans supprimer les données
docker-compose stop

# Redémarrer
docker-compose start

# Redémarrer complètement (rebuild)
docker-compose restart
docker-compose build backend
docker-compose up -d
```

### Suppression complète

```bash
# Arrêter et supprimer les conteneurs
docker-compose down

# Supprimer aussi les volumes (données)
docker-compose down -v

# Supprimer les images
docker-compose down --rmi all
```

## ⚙️ Variables d'environnement importantes

### Sécurité

```env
DJANGO_SECRET_KEY=<clé-forte>
DJANGO_DEBUG=false
DJANGO_SECURE_SSL_REDIRECT=true
```

### Base de données

```env
DATABASE_URL=postgresql://transfer:transfer@postgres:5432/transfer_on_line
```

### Cache & Queue

```env
REDIS_URL=redis://redis:6379/0
```

### Paiements

```env
JEKO_API_KEY=<votre-clé>
GENIUSPAY_API_KEY=<votre-clé>
```

## 🚨 Troubleshooting

### Problème: Conteneurs ne démarrent pas

```bash
# Vérifier les logs
docker-compose logs

# Reconstruction complète
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

### Problème: Port déjà utilisé

```bash
# Trouver le processus
lsof -i :8000

# Modifier les ports dans docker-compose.yml
# Ou tuer le processus
kill -9 <PID>
```

### Problème: Erreurs de migration

```bash
# Réinitialiser la base de données
docker-compose exec backend python manage.py migrate zero --app core

# Recommencer les migrations
docker-compose exec backend python manage.py migrate
```

### Problème: Static files non générés

```bash
# Régénérer
docker-compose exec backend python manage.py collectstatic --noinput --clear
```

## 📚 Documentation complète

Voir [DEPLOYMENT.md](DEPLOYMENT.md) pour :

- Guide complet de déploiement VPS
- Configuration HTTPS/SSL
- Monitoring et logs
- Stratégie de backup
- Points de sécurité

## 🔐 Points importants

✅ Le projet en Docker est **production-ready** :

- Migrations automatiques au démarrage
- Health checks sur tous les services
- Volumes persistants pour données
- Networking interne sécurisé
- Pas de données sensibles dans l'image
- Support pour scalabilité (replicas)

## 📞 Support

Pour toute question:

1. Consulter DEPLOYMENT.md
2. Vérifier `docker-compose logs`
3. Consulter la documentation Django
4. Vérifier la configuration `.env`

---

**Version**: 1.0  
**Dernière mise à jour**: 2026-09-01  
**Statut**: ✅ Production Ready
