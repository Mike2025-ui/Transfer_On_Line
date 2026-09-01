#!/bin/bash
# Script to start Transfer On Line with Docker

echo "=========================================="
echo "Transfer On Line - Docker Startup"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "🔍 Checking Docker and docker-compose versions..."
docker --version
docker-compose --version
echo ""

echo "🚀 Starting Transfer On Line containers..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

echo ""
echo "📊 Container status:"
docker-compose ps

echo ""
echo "=========================================="
echo "✅ Transfer On Line is running!"
echo "=========================================="
echo ""
echo "📍 Services available at:"
echo "  • Backend API: http://localhost:8000"
echo "  • Admin Panel: http://localhost:8000/admin"
echo "  • PostgreSQL: localhost:5432"
echo "  • Redis: localhost:6379"
echo ""
echo "📝 Logs:"
echo "  • Backend: docker-compose logs -f backend"
echo "  • Database: docker-compose logs -f postgres"
echo "  • Redis: docker-compose logs -f redis"
echo ""
echo "🛑 To stop: docker-compose down"
echo "🧹 To clean up: docker-compose down -v"
echo ""
