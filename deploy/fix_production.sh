#!/usr/bin/env bash
# ==============================================================================
# Script de Réparation et Démarrage Production - Transfer On Line
# ==============================================================================
set -e

echo "=== 1. Vérification de l'environnement ==="
WORKDIR="/var/www/transfert-online/Transfer_On_Line"
if [ -d "$WORKDIR" ]; then
    cd "$WORKDIR"
fi

# Création du dossier ACME pour certbot
mkdir -p /var/www/certbot

echo "=== 2. Ouverture des ports Pare-feu (UFW) ==="
if command -v ufw >/dev/null 2>&1; then
    ufw allow 80/tcp || true
    ufw allow 443/tcp || true
    echo "Ports 80 et 443 autorisés sur UFW."
fi

echo "=== 3. Vérification du backend Docker ==="
if [ -f "backend/.env" ]; then
    echo "Démarrage des conteneurs backend (PostgreSQL, Redis, Django)..."
    docker compose --env-file backend/.env up -d || docker-compose --env-file backend/.env up -d
else
    echo "ATTENTION: backend/.env introuvable, tentative avec docker compose standard..."
    docker compose up -d || docker-compose up -d
fi

echo "=== 4. Gestion du certificat SSL et Nginx ==="
CERT_PATH="/etc/letsencrypt/live/transfert-online.site/fullchain.pem"

if [ -f "$CERT_PATH" ]; then
    echo "Certificat SSL Let's Encrypt détecté."
    # Installer la configuration HTTPS finale
    cp deploy/nginx/transfert-online.site.conf /etc/nginx/sites-available/transfert-online.site
    ln -sf /etc/nginx/sites-available/transfert-online.site /etc/nginx/sites-enabled/transfert-online.site
    
    if nginx -t; then
        systemctl restart nginx
        echo "Nginx redémarré avec succès en HTTPS !"
    else
        echo "Erreur avec le certificat existant, tentative de renouvellement..."
        certbot renew --quiet || true
        systemctl restart nginx
    fi
else
    echo "Certificat SSL non trouvé. Phase de Bootstrap HTTP..."
    # 1. Utiliser la configuration HTTP temporaire
    cp deploy/nginx/transfert-online.site.bootstrap.conf /etc/nginx/sites-available/transfert-online.site
    ln -sf /etc/nginx/sites-available/transfert-online.site /etc/nginx/sites-enabled/transfert-online.site
    
    nginx -t
    systemctl restart nginx
    echo "Nginx démarré en HTTP."

    # 2. Générer le certificat SSL
    echo "Génération du certificat Let's Encrypt via Certbot..."
    certbot certonly --webroot -w /var/www/certbot \
        -d transfert-online.site -d www.transfert-online.site \
        --non-interactive --agree-tos --register-unsafely-without-email || \
    certbot certonly --webroot -w /var/www/certbot \
        -d transfert-online.site -d www.transfert-online.site

    # 3. Basculer sur la configuration HTTPS finale
    if [ -f "$CERT_PATH" ]; then
        echo "Certificat obtenu ! Activation de la configuration HTTPS finale..."
        cp deploy/nginx/transfert-online.site.conf /etc/nginx/sites-available/transfert-online.site
        nginx -t
        systemctl restart nginx
        echo "Nginx est maintenant configuré en HTTPS !"
    else
        echo "Avertissement: Le certificat n'a pas pu être émis automatiquement. Nginx reste actif en HTTP."
    fi
fi

echo ""
echo "=== 5. Test de connectivité interne ==="
sleep 2
echo "Test Nginx status:"
systemctl is-active nginx && echo "-> Nginx: ACTIF" || echo "-> Nginx: INACTIF"

echo ""
echo "Test appel API local (backend:8000) :"
curl -s -o /dev/null -w "Code HTTP local: %{http_code}\n" http://127.0.0.1:8000/api/operators/ || echo "Backend non joignable sur 8000"

echo ""
echo "Test appel API public (transfert-online.site) :"
curl -k -s -o /dev/null -w "Code HTTP public: %{http_code}\n" https://transfert-online.site/api/operators/ || echo "Public non joignable"

echo ""
echo "=============================================================================="
echo " Terminé ! Appuyez maintenant sur [RÉESSAYER] sur votre téléphone !"
echo "=============================================================================="

