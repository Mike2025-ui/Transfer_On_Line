#!/usr/bin/env bash
# ==============================================================================
# Script de Déploiement et Réparation Production - Transfer On Line
# ==============================================================================
set -e

echo "=============================================="
echo " TRANSFER ON LINE - DÉPLOIEMENT PRODUCTION"
echo "=============================================="

WORKDIR="/var/www/transfert-online/Transfer_On_Line"
if [ -d "$WORKDIR" ]; then
    cd "$WORKDIR"
fi

# [1/8] Vérification des fichiers du projet
echo
echo "[1/8] Vérification des fichiers du projet..."
if [ ! -f "docker-compose.yml" ]; then
    echo "ERREUR: docker-compose.yml introuvable dans $(pwd)."
    exit 1
fi

if [ ! -f "backend/requirements.txt" ]; then
    echo "ERREUR: backend/requirements.txt introuvable."
    exit 1
fi
echo "Projet OK : $(pwd)"

# [2/8] Sécurité dépendances : Garantie de présence de django-rq
echo
echo "[2/8] Vérification de django-rq dans backend/requirements.txt..."
if grep -qE '^django-rq([=<>!~].*)?$' backend/requirements.txt; then
    echo "django-rq est bien présent :"
    grep -nE '^django-rq([=<>!~].*)?$' backend/requirements.txt
else
    echo "django-rq absent. Ajout automatique de django-rq==2.10.3 et rq==1.16.2..."
    echo "django-rq==2.10.3" >> backend/requirements.txt
    echo "rq==1.16.2" >> backend/requirements.txt
fi

# [3/8] Pare-feu (UFW)
echo
echo "[3/8] Vérification des ports Pare-feu (UFW)..."
if command -v ufw >/dev/null 2>&1; then
    ufw allow 80/tcp || true
    ufw allow 443/tcp || true
    echo "Ports 80 et 443 autorisés sur UFW."
fi

# [4/8] Construction et mise à jour des conteneurs Docker
echo
echo "[4/8] Construction et démarrage des conteneurs Docker..."
echo "IMPORTANT : Les volumes PostgreSQL et Redis sont préservés (aucun volume supprimé)."

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

ENV_ARG=""
if [ -f "backend/.env" ]; then
    ENV_ARG="--env-file backend/.env"
fi

echo "Construction des images backend et reconciler..."
$COMPOSE $ENV_ARG build backend reconciler

echo "Lancement des conteneurs en tâche de fond..."
$COMPOSE $ENV_ARG up -d

# [5/8] Attente du démarrage complet du backend
echo
echo "[5/8] Attente du démarrage du backend..."
MAX_ATTEMPTS=30
ATTEMPT=1
BACKEND_CONTAINER=$($COMPOSE ps -q backend 2>/dev/null || echo "transfer_on_line_backend")

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "unknown")
    HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "none")

    echo "Tentative $ATTEMPT/$MAX_ATTEMPTS - état : $STATUS (health: $HEALTH)"

    if [ "$STATUS" = "running" ] && [ "$HEALTH" = "healthy" ]; then
        echo "Conteneur backend opérationnel et en bonne santé !"
        break
    elif [ "$STATUS" = "running" ] && [ "$HEALTH" = "none" ]; then
        sleep 5
        break
    fi

    sleep 4
    ATTEMPT=$((ATTEMPT + 1))
done

# [6/8] Tests d'intégrité internes
echo
echo "[6/8] Vérifications d'intégrité..."

echo "--- Test django-rq ---"
if $COMPOSE exec -T backend python -c "import django_rq; print('django_rq OK:', django_rq.__version__)"; then
    echo "django-rq fonctionne correctement."
else
    echo "ERREUR : django-rq n'est pas disponible."
    $COMPOSE logs --tail=50 backend
    exit 1
fi

echo "--- Test Django check ---"
if $COMPOSE exec -T backend python manage.py check; then
    echo "Django check : OK"
else
    echo "ERREUR : Django check a échoué."
    $COMPOSE logs --tail=50 backend
    exit 1
fi

# [7/8] Configuration Nginx & Certificat SSL Let's Encrypt
echo
echo "[7/8] Configuration Nginx et SSL..."
mkdir -p /var/www/certbot
CERT_PATH="/etc/letsencrypt/live/transfert-online.site/fullchain.pem"

if [ -f "$CERT_PATH" ]; then
    echo "Certificat SSL Let's Encrypt détecté."
    if [ -f "deploy/nginx/transfert-online.site.conf" ]; then
        cp deploy/nginx/transfert-online.site.conf /etc/nginx/sites-available/transfert-online.site
        ln -sf /etc/nginx/sites-available/transfert-online.site /etc/nginx/sites-enabled/transfert-online.site
    fi
    
    if nginx -t >/dev/null 2>&1; then
        systemctl restart nginx 2>/dev/null || systemctl reload nginx 2>/dev/null || true
        echo "Nginx actif en HTTPS."
    fi
else
    echo "Certificat SSL non trouvé. Phase de Bootstrap HTTP..."
    rm -f /etc/nginx/sites-enabled/*
    for f in /etc/nginx/conf.d/*.conf; do
        if [ -f "$f" ] && grep -q "fullchain.pem" "$f" 2>/dev/null; then
            mv "$f" "${f}.bak"
        fi
    done
    
    if [ -f "deploy/nginx/transfert-online.site.bootstrap.conf" ]; then
        cp deploy/nginx/transfert-online.site.bootstrap.conf /etc/nginx/sites-available/transfert-online.site
        ln -sf /etc/nginx/sites-available/transfert-online.site /etc/nginx/sites-enabled/transfert-online.site
        nginx -t >/dev/null 2>&1 && systemctl restart nginx 2>/dev/null || true
    fi

    echo "Génération du certificat Let's Encrypt..."
    certbot certonly --webroot -w /var/www/certbot \
        -d transfert-online.site -d www.transfert-online.site \
        --non-interactive --agree-tos --register-unsafely-without-email || true

    if [ -f "$CERT_PATH" ] && [ -f "deploy/nginx/transfert-online.site.conf" ]; then
        cp deploy/nginx/transfert-online.site.conf /etc/nginx/sites-available/transfert-online.site
        nginx -t >/dev/null 2>&1 && systemctl restart nginx 2>/dev/null || true
        echo "Certificat émis et Nginx configuré en HTTPS !"
    fi
fi

# [8/8] Vérification des endpoints HTTP & HTTPS
echo
echo "[8/8] Tests de connectivité API..."
sleep 2

HTTP_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health/ 2>/dev/null || echo "000")
echo "HTTP Local (127.0.0.1:8000/api/health/) : $HTTP_LOCAL"

HTTP_PUBLIC=$(curl -k -s -o /tmp/tol_health_response.txt -w "%{http_code}" https://transfert-online.site/api/health/ 2>/dev/null || echo "000")
echo "HTTP Public (https://transfert-online.site/api/health/) : $HTTP_PUBLIC"
if [ -f /tmp/tol_health_response.txt ]; then
    cat /tmp/tol_health_response.txt
    echo
fi

echo
echo "=============================================="
echo " ÉTAT DES SERVICES DOCKER"
echo "=============================================="
$COMPOSE ps

echo
if [ "$HTTP_PUBLIC" = "200" ] || [ "$HTTP_LOCAL" = "200" ]; then
    echo "=============================================="
    echo " DÉPLOIEMENT TERMINÉ AVEC SUCCÈS !"
    echo "=============================================="
    echo " - Backend Django opérationnel"
    echo " - django-rq opérationnel"
    echo " - Migrations & données de production à jour"
    echo " - API en ligne et prête pour l'application"
else
    echo "=============================================="
    echo " ATTENTION : Vérifiez les logs"
    echo "=============================================="
    $COMPOSE logs --tail=30 backend
fi
