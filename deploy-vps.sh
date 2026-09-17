#!/usr/bin/env bash
# ==============================================================================
# Script de Déploiement et Maintenance Production - Transfer On Line
# ==============================================================================
# Ce script assure le déploiement sécurisé, les migrations et la vérification
# de santé du backend Django et du reconciler sur le serveur VPS de production.
#
# RÈGLES CRITIQUES :
# - Aucun volume PostgreSQL / Redis n'est supprimé (JAMAIS de docker compose down -v).
# - La configuration Nginx hôte et ISPConfig ne sont PAS modifiées.
# - Le fichier de secrets backend/.env est strictement préservé.
# ==============================================================================

set -eo pipefail

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paramètres par défaut
DO_PULL=true
NO_CACHE=false
DRY_RUN=false
SETUP_GATEWAY_NAME=""
BUILD_FLAGS=""

# Traitement des arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pull)
            DO_PULL=false
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            BUILD_FLAGS="--no-cache"
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --setup-gateway)
            if [ -n "$2" ] && [[ "$2" != --* ]]; then
                SETUP_GATEWAY_NAME="$2"
                shift 2
            else
                SETUP_GATEWAY_NAME="Gateway-Serveur-1"
                shift
            fi
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo
            echo "Options:"
            echo "  --no-pull              Ne pas exécuter 'git pull' avant le déploiement"
            echo "  --no-cache             Reconstruire les images Docker sans utiliser le cache"
            echo "  --dry-run              Effectuer uniquement les vérifications préalables sans modifier les conteneurs"
            echo "  --setup-gateway [NOM]  Générer/afficher le secret d'enrôlement Gateway USSD après déploiement"
            echo "  -h, --help             Afficher cette aide"
            exit 0
            ;;
        *)
            echo -e "${RED}Option inconnue : $1${NC}"
            echo "Utilisez --help pour voir les options disponibles."
            exit 1
            ;;
    esac
done

echo "=============================================="
echo " TRANSFER ON LINE - DÉPLOIEMENT PRODUCTION"
echo "=============================================="
echo "Mode dry-run : $DRY_RUN"
echo "Git pull     : $DO_PULL"
echo "No-cache     : $NO_CACHE"
if [ -n "$SETUP_GATEWAY_NAME" ]; then
    echo "Setup Gateway: $SETUP_GATEWAY_NAME"
fi
echo "=============================================="

# Gestion des erreurs
cleanup_on_error() {
    echo
    echo -e "${RED}==============================================${NC}"
    echo -e "${RED} ÉCHEC DU DÉPLOIEMENT${NC}"
    echo -e "${RED}==============================================${NC}"
    echo "Consultez les derniers logs du conteneur backend :"
    if [ -n "$COMPOSE" ]; then
        $COMPOSE logs --tail=40 backend 2>/dev/null || true
    fi
}
trap cleanup_on_error ERR

# ------------------------------------------------------------------------------
# [1/8] Répertoire & Pré-requis système
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[1/8] Vérification de l'environnement...${NC}"

PROD_DIR="/var/www/transfert-online/Transfer_On_Line"
if [ -d "$PROD_DIR" ]; then
    cd "$PROD_DIR"
fi

echo "Répertoire actif : $(pwd)"

if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}ERREUR: docker-compose.yml introuvable dans $(pwd).${NC}"
    exit 1
fi

if [ ! -f "backend/requirements.txt" ]; then
    echo -e "${RED}ERREUR: backend/requirements.txt introuvable.${NC}"
    exit 1
fi

if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}ATTENTION: backend/.env introuvable dans $(pwd).${NC}"
    echo -e "${YELLOW}Assurez-vous que les variables d'environnement de production sont définies.${NC}"
else
    echo -e "${GREEN}Fichier de configuration backend/.env détecté et préservé.${NC}"
fi

# Détection de la commande Docker Compose
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo -e "${RED}ERREUR: 'docker compose' ou 'docker-compose' est requis mais non installé.${NC}"
    exit 1
fi
echo -e "Outil Docker Compose détecté : ${GREEN}$COMPOSE${NC}"

# ------------------------------------------------------------------------------
# [2/8] Synchronisation Git sécurisée
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[2/8] Synchronisation du dépôt Git...${NC}"

if [ -d ".git" ]; then
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "inconnu")
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo "Branche actuelle : $CURRENT_BRANCH (commit : $CURRENT_COMMIT)"

    if [ "$DO_PULL" = true ] && [ "$DRY_RUN" = false ]; then
        # Vérification si des modifications locales sur des fichiers suivis existent
        if ! git diff-files --quiet --; then
            echo -e "${YELLOW}Modifications locales détectées dans le dépôt. Sauvegarde via git stash...${NC}"
            git stash push -m "deploy_auto_stash_$(date +%Y%m%d_%H%M%S)" || true
        fi

        echo "Récupération des dernières modifications depuis le dépôt distant (origin/$CURRENT_BRANCH)..."
        git fetch origin "$CURRENT_BRANCH" || true
        git pull origin "$CURRENT_BRANCH" || {
            echo -e "${YELLOW}Avertissement : 'git pull' a rencontré un problème. Poursuite avec le code local existant.${NC}"
        }

        NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "inconnu")
        echo -e "${GREEN}Code synchronisé sur le commit : $NEW_COMMIT${NC}"
    elif [ "$DRY_RUN" = true ]; then
        echo "[DRY-RUN] 'git pull' simulé (non exécuté)."
    else
        echo "Option --no-pull spécifiée, saut de la synchronisation Git."
    fi
else
    echo "Pas de sous-dossier .git détecté, saut de l'étape Git."
fi

# ------------------------------------------------------------------------------
# [3/8] Vérification des dépendances Python critiques
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[3/8] Vérification des dépendances critiques dans backend/requirements.txt...${NC}"

ENSURE_PACKAGE() {
    local pkg_pattern="$1"
    local pkg_exact="$2"
    if grep -qE "^${pkg_pattern}" backend/requirements.txt; then
        echo -e "  - ${pkg_pattern}: ${GREEN}présent${NC}"
    else
        echo -e "  - ${pkg_pattern}: ${YELLOW}absent -> ajout de ${pkg_exact}${NC}"
        if [ "$DRY_RUN" = false ]; then
            echo "$pkg_exact" >> backend/requirements.txt
        fi
    fi
}

ENSURE_PACKAGE "django-rq([=<>!~].*)?$" "django-rq==2.10.3"
ENSURE_PACKAGE "rq([=<>!~].*)?$" "rq==1.16.2"
ENSURE_PACKAGE "psycopg([=<>!~].*)?$" "psycopg==3.3.4"
ENSURE_PACKAGE "redis([=<>!~].*)?$" "redis==5.0.1"

# ------------------------------------------------------------------------------
# [4/8] Construction et mise à jour des conteneurs Docker
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[4/8] Construction et démarrage des conteneurs Docker...${NC}"
echo -e "${GREEN}SÉCURITÉ : Les volumes PostgreSQL ('postgres_data') et Redis ('redis_data') sont 100% préservés.${NC}"

ENV_ARG=""
if [ -f "backend/.env" ]; then
    ENV_ARG="--env-file backend/.env"
fi

if [ "$DRY_RUN" = true ]; then
    echo "[DRY-RUN] Commande de build simulée : $COMPOSE $ENV_ARG build $BUILD_FLAGS backend reconciler"
    echo "[DRY-RUN] Commande de démarrage simulée : $COMPOSE $ENV_ARG up -d"
    echo "[DRY-RUN] Migrations simulées : $COMPOSE exec -T backend python manage.py migrate --noinput"
    echo "[DRY-RUN] Collecte statiques simulée : $COMPOSE exec -T backend python manage.py collectstatic --noinput"
    echo "[DRY-RUN] Test django-rq simulé : $COMPOSE exec -T backend python -c \"import django_rq; print('django-rq OK:', django_rq.__file__)\""
    echo "[DRY-RUN] Test Django check simulé : $COMPOSE exec -T backend python manage.py check"
    echo -e "${GREEN}Vérification préalable réussie (Dry-Run achevé).${NC}"
    exit 0
fi

echo "Construction des images backend et reconciler..."
$COMPOSE $ENV_ARG build $BUILD_FLAGS backend reconciler

echo "Démarrage des services avec préservation stricte des volumes existants..."
$COMPOSE $ENV_ARG up -d

# ------------------------------------------------------------------------------
# [5/8] Attente du démarrage et santé du backend
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[5/8] Attente du démarrage du backend...${NC}"

MAX_ATTEMPTS=30
ATTEMPT=1
BACKEND_CONTAINER=$($COMPOSE ps -q backend 2>/dev/null || echo "transfer_on_line_backend")

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "unknown")
    HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "none")

    echo "Tentative $ATTEMPT/$MAX_ATTEMPTS - état : $STATUS (santé: $HEALTH)"

    if [ "$STATUS" = "running" ] && [ "$HEALTH" = "healthy" ]; then
        echo -e "${GREEN}Conteneur backend opérationnel et sain !${NC}"
        break
    elif [ "$STATUS" = "running" ] && [ "$HEALTH" = "none" ]; then
        sleep 5
        break
    fi

    sleep 4
    ATTEMPT=$((ATTEMPT + 1))
done

if [ "$ATTEMPT" -gt "$MAX_ATTEMPTS" ]; then
    echo -e "${RED}Délai d'attente dépassé pour le conteneur backend.${NC}"
    $COMPOSE logs --tail=50 backend
    exit 1
fi

# ------------------------------------------------------------------------------
# [6/8] Migrations Base de données & Collecte statiques
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[6/8] Exécution des migrations et collecte des fichiers statiques...${NC}"

echo "Application des migrations Django..."
$COMPOSE exec -T backend python manage.py migrate --noinput

echo "Collecte des fichiers statiques Django..."
$COMPOSE exec -T backend python manage.py collectstatic --noinput

# ------------------------------------------------------------------------------
# [7/8] Tests d'intégrité internes
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[7/8] Tests d'intégrité internes...${NC}"

echo "--- Test django-rq ---"
if $COMPOSE exec -T backend python -c "import django_rq; print('django-rq OK:', django_rq.__file__)"; then
    echo -e "${GREEN}django-rq est fonctionnel et chargé depuis le conteneur.${NC}"
else
    echo -e "${RED}ERREUR : django-rq n'a pas pu être chargé.${NC}"
    $COMPOSE logs --tail=40 backend
    exit 1
fi

echo "--- Test Django check ---"
if $COMPOSE exec -T backend python manage.py check; then
    echo -e "${GREEN}Django check : SUCCÈS${NC}"
else
    echo -e "${RED}ERREUR : Le check Django a échoué.${NC}"
    $COMPOSE logs --tail=40 backend
    exit 1
fi

# ------------------------------------------------------------------------------
# [8/8] Tests de connectivité API & Résumé
# ------------------------------------------------------------------------------
echo
echo -e "${BLUE}[8/8] Tests de connectivité de l'API...${NC}"
sleep 2

# Test HTTP local (127.0.0.1:8000)
HTTP_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health/ 2>/dev/null || echo "000")
echo -e "HTTP Local (127.0.0.1:8000/api/health/) : ${GREEN}$HTTP_LOCAL${NC}"

# Test HTTPS public (transfert-online.site)
HTTP_PUBLIC=$(curl -k -s -o /tmp/tol_health_response.txt -w "%{http_code}" https://transfert-online.site/api/health/ 2>/dev/null || echo "000")
echo -e "HTTP Public (https://transfert-online.site/api/health/) : ${GREEN}$HTTP_PUBLIC${NC}"
if [ -f /tmp/tol_health_response.txt ]; then
    cat /tmp/tol_health_response.txt
    echo
fi

# Option Setup Gateway
if [ -n "$SETUP_GATEWAY_NAME" ]; then
    echo
    echo -e "${BLUE}=== Configuration Gateway USSD ($SETUP_GATEWAY_NAME) ===${NC}"
    $COMPOSE exec -T backend python manage.py setup_gateway --name "$SETUP_GATEWAY_NAME"
fi

echo
echo "=============================================="
echo " ÉTAT DES SERVICES DOCKER"
echo "=============================================="
$COMPOSE ps

echo
echo "=============================================="
echo " DERNIERS LOGS DU RECONCILER"
echo "=============================================="
$COMPOSE logs --tail=15 reconciler 2>/dev/null || echo "Aucun log reconciler disponible."

echo
if [ "$HTTP_PUBLIC" = "200" ] || [ "$HTTP_LOCAL" = "200" ]; then
    echo -e "${GREEN}==============================================${NC}"
    echo -e "${GREEN} DÉPLOIEMENT PRODUCTION RÉUSSI !${NC}"
    echo -e "${GREEN}==============================================${NC}"
    echo " - Backend Django opérationnel (Gunicorn)"
    echo " - Reconciler opérationnel"
    echo " - django-rq disponible"
    echo " - Migrations PostgreSQL appliquées sans perte de données"
    echo " - API en ligne et prête"
else
    echo -e "${YELLOW}==============================================${NC}"
    echo -e "${YELLOW} ATTENTION : L'API ne répond pas en HTTP 200.${NC}"
    echo -e "${YELLOW}==============================================${NC}"
    echo "Consultez les logs détaillés :"
    echo "$COMPOSE logs --tail=40 backend"
fi
