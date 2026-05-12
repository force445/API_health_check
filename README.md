# Services Health Check

Simple Django-based service monitoring dashboard for HTTP endpoints. It stores
service status in PostgreSQL, runs scheduled checks with Celery, and can send a
chat webhook notification when a service becomes unhealthy.

## What This Project Does

- Group monitored services by project
- Check each URL and store the result history
- Show dashboard status, uptime, incidents, and trend graphs
- Allow manual "check now" runs from the UI
- Run automatic checks on a schedule with Celery Beat
- Send a webhook alert for failed checks when `notify=true`

## Stack

- Django
- PostgreSQL
- Redis
- Celery worker
- Celery Beat
- Docker Compose

## Project Structure

```text
.
├── docker-compose.yml
├── .env.template
├── backend/
│   ├── manage.py
│   ├── backend/settings.py
│   └── healthcheck/
│       ├── models.py
│       ├── services.py
│       ├── views.py
│       └── templates/healthcheck/dashboard.html
└── config/nginx.conf
```

## Requirements

- Docker
- `docker-compose`

## Quick Start

1. Copy the environment file:

```bash
cp .env.template .env
```

2. Edit `.env` and set at least:

- `DJANGO_SECRET`
- `POSTGRES_PASSWORD`
- `CHAT_HOOK_URL`

3. Start the stack:

```bash
docker-compose up -d --build
```

4. Run database migrations:

```bash
docker-compose exec backend python manage.py migrate
```

5. Create an admin user:

```bash
docker-compose exec backend python manage.py createsuperuser
```

6. Open the app:

- Dashboard: `http://localhost:8000/`
- Django admin: `http://localhost:8000/admin/`

The dashboard requires a staff/admin login. If you are not logged in, it sends
you to the Django admin login page.

## Environment Variables

The repo includes `.env.template`. Main values:

```env
PROJECT_NAME='health-check'
STATE=dev

DJANGO_SECRET=''
POSTGRES_DB='health-check'
POSTGRES_USER='health-check'
POSTGRES_PASSWORD=''
POSTGRES_HOST=${PROJECT_NAME}-db
POSTGRES_PORT=5432

CSRF_TRUSTED_ORIGINS='http://localhost:8000'

REDIS_URI="redis://${PROJECT_NAME}-redis:6379/0"
CELERY_SCHEDULE_TIME=600
HEALTHCHECK_REQUEST_TIMEOUT_SECONDS=10
HEALTHCHECK_REQUEST_ATTEMPTS=2

CHAT_HOOK_URL="https://chat.googleapis.com/..."
```

Important notes:

- `CELERY_SCHEDULE_TIME=600` means automatic checks run every 10 minutes.
- `HEALTHCHECK_REQUEST_TIMEOUT_SECONDS` controls each request timeout.
- `HEALTHCHECK_REQUEST_ATTEMPTS` controls retry attempts before marking a check
  as failed.
- `CHAT_HOOK_URL` is used only when a monitored URL fails and that URL has
  `notify=true`.

## How To Use

### 1. Create a Project

In Django admin, add a `Project`.

Fields:

- `name`: logical group name such as `Production`, `Staging`, or `Client A`
- `is_use`: enables or disables the whole project

### 2. Add URLs To Monitor

In Django admin, add one or more `URL` entries.

Fields:

- `project`: parent project
- `name`: display name for the service
- `tag`: optional grouping label such as `production`, `staging`, `api`, `web`
- `url`: full HTTP/HTTPS URL to check
- `is_use`: enables or disables this service
- `notify`: send webhook alert on failure

Runtime fields maintained by the app:

- `last_checked`
- `is_healthy`
- `log`

### 3. Open the Dashboard

Go to:

```text
http://localhost:8000/
```

The dashboard shows:

- Total tracked services
- Current unhealthy services
- Recent incidents
- Per-project health summary
- Uptime for the last 24 hours and 7 days
- Trend graphs from recent check history

### 4. Run Checks

Automatic checks:

- Celery Beat triggers checks on the interval from `CELERY_SCHEDULE_TIME`

Manual checks:

- Use the `Check Now` action in the dashboard to run all active services
- Use the per-service action to run one service immediately

Manual checks are processed synchronously by the app and immediately create
`HealthCheckResult` rows.

### 5. Filter the Dashboard

The dashboard supports filtering by:

- Project
- Current health status
- Tag

Tags are useful for separating environments such as `production`, `staging`,
`internal`, or `external`.

## How Health Checks Work

For each active URL:

1. The app sends an HTTP GET request.
2. If the response status is below `400`, the service is marked healthy.
3. If the request fails, times out, or returns `4xx/5xx`, it is marked
   unhealthy.
4. A `HealthCheckResult` row is stored with:
   - check time
   - health status
   - status code
   - response time
   - response/error log
5. If the service is unhealthy and `notify=true`, the app posts a message to
   `CHAT_HOOK_URL`.

## Main Data Models

### `Project`

Logical group of services.

### `URL`

A monitored endpoint tied to a project.

### `HealthCheckResult`

Historical result for each check. This is the source for:

- uptime percentages
- incident history
- trend charts

Old records are cleaned up automatically based on
`HEALTHCHECK_RESULT_RETENTION_DAYS` in the Django settings. Default retention is
30 days.

## Useful Commands

Start services:

```bash
docker-compose up -d --build
```

Stop services:

```bash
docker-compose down
```

View logs:

```bash
docker-compose logs -f backend
docker-compose logs -f celery
docker-compose logs -f celery-beat
```

Run migrations:

```bash
docker-compose exec backend python manage.py migrate
```

Create admin user:

```bash
docker-compose exec backend python manage.py createsuperuser
```

Run tests:

```bash
docker-compose exec backend python manage.py test
```

## Operational Notes

- The default runtime path in this repo is PostgreSQL, not SQLite.
- The backend waits for PostgreSQL before starting Django in development.
- The app currently uses `requests.get(..., verify=False)` for URL checks, so
  SSL certificate verification is disabled during checks.
- `TIME_ZONE` is set to `UTC` in Django settings.

## Troubleshooting

If the dashboard is not loading:

- confirm `docker-compose ps`
- confirm migrations were run
- confirm the backend container is up

If checks are not running automatically:

- confirm `celery` and `celery-beat` containers are running
- confirm Redis is up
- confirm `CELERY_SCHEDULE_TIME` is set correctly

If notifications are not sent:

- confirm `CHAT_HOOK_URL` is valid
- confirm the URL entry has `notify` enabled

If a service is always failing:

- inspect the `log` field in the URL or `HealthCheckResult`
- try the URL manually from the host or container
