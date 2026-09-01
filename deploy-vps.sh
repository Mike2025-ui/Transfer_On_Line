#!/bin/bash
# VPS Deployment Script for Transfer On Line
# Usage: ./deploy-vps.sh <VPS_IP> <VPS_USER>

set -e

if [ $# -lt 2 ]; then
    echo "Usage: ./deploy-vps.sh <VPS_IP> <VPS_USER>"
    echo "Example: ./deploy-vps.sh 192.168.1.100 ubuntu"
    exit 1
fi

VPS_IP=$1
VPS_USER=$2
PROJECT_DIR="/home/$VPS_USER/transfer_on_line"

echo "=========================================="
echo "Transfer On Line - VPS Deployment"
echo "=========================================="
echo "VPS IP: $VPS_IP"
echo "VPS User: $VPS_USER"
echo "Project Directory: $PROJECT_DIR"
echo ""

# Step 1: Copy project to VPS
echo "📁 Copying project files to VPS..."
scp -r ../ $VPS_USER@$VPS_IP:$PROJECT_DIR
echo "✅ Project copied"

# Step 2: Connect to VPS and setup
echo ""
echo "⚙️  Setting up on VPS..."
ssh $VPS_USER@$VPS_IP << 'EOF'

# Ensure Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
fi

# Ensure docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Installing docker-compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

cd /home/$VPS_USER/transfer_on_line

# Create .env for production (user should update this)
if [ ! -f backend/.env.production ]; then
    echo "Creating .env.production template..."
    cp backend/.env backend/.env.production
    echo "⚠️  UPDATE backend/.env.production with your VPS-specific settings!"
fi

# Build and start containers
echo "Building Docker image..."
docker-compose build

echo "Starting services..."
docker-compose up -d

echo "✅ Deployment complete!"
echo "Visit http://$VPS_IP:8000 to access your application"

EOF

echo ""
echo "=========================================="
echo "✅ VPS Deployment complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. SSH into VPS: ssh $VPS_USER@$VPS_IP"
echo "2. Edit configuration: nano $PROJECT_DIR/backend/.env.production"
echo "3. Restart services: cd $PROJECT_DIR && docker-compose restart"
echo "4. Check logs: docker-compose logs -f backend"
echo ""
