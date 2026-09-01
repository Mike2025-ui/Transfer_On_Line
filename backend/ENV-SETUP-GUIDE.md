# Transfer On Line - Environment Configuration Guide

## Overview

This project uses environment-specific configuration files to support both local development and production deployment.

### File Structure

- **`.env.local`** - Local development environment (uses SQLite, HTTP, DEBUG=true)
- **`.env.production`** - Production environment (uses PostgreSQL, HTTPS, DEBUG=false)
- **`.env`** - Currently used configuration (should match `.env.local` for development)

---

## Local Development Setup

### 1. Copy `.env.local` to `.env` for local work:

```bash
cp backend/.env.local backend/.env
```

### 2. Start the Django development server:

```bash
cd backend
python manage.py migrate
python manage.py runserver
```

### 3. Frontend development (if using Flutter web or React):

```bash
# Terminal 1: Django backend
cd backend && python manage.py runserver 0.0.0.0:8000

# Terminal 2: Frontend (example: React on port 3000)
cd frontend && npm start
```

---

## Production Deployment

### 1. Prepare production environment variables:

```bash
# On your production server, set these environment variables
# or use a `.env` file with these values:

export DJANGO_SECRET_KEY="<YOUR_SECURE_SECRET_KEY>"
export DATABASE_URL="postgresql://user:pass@prod-db:5432/db"
export REDIS_URL="redis://prod-redis:6379/0"
export EMAIL_HOST_USER="your-email@gmail.com"
export EMAIL_HOST_PASSWORD="your-app-password"
```

### 2. Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Run migrations:

```bash
python manage.py migrate
```

### 4. Collect static files:

```bash
python manage.py collectstatic --noinput
```

### 5. Start the production server with gunicorn:

```bash
gunicorn transfer_on_line.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --worker-class sync \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

---

## Key Differences: Local vs Production

| Setting           | Local                | Production                                       |
| ----------------- | -------------------- | ------------------------------------------------ |
| **DEBUG**         | `true`               | `false`                                          |
| **ALLOWED_HOSTS** | localhost, 127.0.0.1 | transfert-online.site, www.transfert-online.site |
| **Database**      | SQLite               | PostgreSQL                                       |
| **SSL Redirect**  | `false`              | `true`                                           |
| **Logging**       | plain (readable)     | json (structured)                                |
| **Log Level**     | DEBUG                | INFO                                             |
| **Email Backend** | console              | SMTP (Gmail, SendGrid, AWS SES)                  |
| **Sentry**        | disabled             | optional (set SENTRY_DSN)                        |

---

## Production Checklist

Before deploying to https://transfert-online.site:

- [ ] Set a unique `DJANGO_SECRET_KEY` (run: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- [ ] Configure production PostgreSQL database (`DATABASE_URL`)
- [ ] Configure production Redis (`REDIS_URL`)
- [ ] Set up email provider (Gmail, SendGrid, AWS SES)
- [ ] Verify all payment API keys are **LIVE** accounts (not sandbox)
- [ ] Test HTTPS/SSL certificate is valid
- [ ] Enable HSTS headers (already set: `DJANGO_SECURE_HSTS_SECONDS=31536000`)
- [ ] Configure CORS and CSRF for your domain
- [ ] Optional: Set up Sentry for error tracking
- [ ] Run `python manage.py check` to validate configuration
- [ ] Run `python manage.py migrate` on production database
- [ ] Run `python manage.py collectstatic --noinput` to gather static files
- [ ] Restart the application server

---

## Payment Provider Configuration

### Jèko (Primary Provider)

- **Base URL**: `https://api.jeko.africa`
- **API Credentials**: From cockpit.jeko.africa
- **Store ID**: `1468389641` (merchant-specific, get from Jèko dashboard)
- **Failover**: Automatic to GeniusPay if Jèko is unavailable or returns an error

### GeniusPay (Fallback Provider)

- **Base URL**: `https://geniuspay.ci/api/v1/merchant`
- **API Credentials**: Live account keys configured in `.env`
- **Webhook Secret**: Verify webhook signatures against this value

### Provider Health Check

The system uses a circuit breaker pattern. If a provider fails repeatedly, the payment service automatically switches to the next provider in `PAYMENT_PROVIDER_ORDER`.

---

## Observability & Logging

### Local Development

- Logs print to terminal in plain text format
- Log level: DEBUG (very verbose)
- Slow requests (>1000ms) are flagged

### Production

- Logs output in JSON format (structured for analysis)
- Log level: INFO (important events only)
- Slow requests (>2000ms) are flagged
- Optional: Send logs to Sentry for centralized error tracking

### Sentry Setup (Optional)

If you want centralized error tracking in production:

1. Create a project at https://sentry.io
2. Copy your Sentry DSN
3. Set `SENTRY_DSN=your-dsn-here` in production environment
4. All errors will be sent to Sentry automatically

---

## Security Best Practices

1. **Never commit `.env` files** - they are gitignored by default
2. **Rotate DJANGO_SECRET_KEY** periodically in production
3. **Use strong database passwords** - at least 32 characters, random
4. **Enable SSL/HTTPS** - set `DJANGO_SECURE_SSL_REDIRECT=true` once certificate is ready
5. **Use environment variables** - never hardcode secrets in code
6. **Monitor payment webhooks** - verify signatures to prevent fraud
7. **Keep dependencies updated** - run `pip install --upgrade django` regularly

---

## Troubleshooting

### "DisallowedHost" Error

- Check `DJANGO_ALLOWED_HOSTS` includes your domain
- Verify the Host header matches an allowed host

### Payment Provider Failures

- Verify API credentials are correct and not expired
- Check that merchant account is enabled for API access
- Ensure circuit breaker hasn't opened (see logs for "circuit open")

### CORS Errors in Frontend

- Update `CORS_ALLOWED_ORIGINS` to include your frontend URL
- Ensure frontend is making requests to backend URL in `ALLOWED_HOSTS`

### Database Connection Errors

- Verify `DATABASE_URL` is correct and database is running
- Check network connectivity to database host
- Ensure user credentials have proper permissions

---

## Support

For issues or questions:

1. Check the logs: `python manage.py runserver`
2. Review Django configuration: `python manage.py check`
3. Test payment providers directly: see `backend/scripts/api_demo.py`
