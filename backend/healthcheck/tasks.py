# healthcheck/tasks.py
import os
import time

import requests
from celery import shared_task
from django.utils import timezone

from .models import HealthCheckResult, URL

def _check_url_health(url):
    log = ""
    status_code = None
    response_time_ms = None
    try:
        started_at = time.monotonic()
        response = requests.get(url.url, timeout=10, verify=False)
        response_time_ms = round((time.monotonic() - started_at) * 1000)
        status_code = response.status_code
        log = response.text
    except requests.RequestException as e:
        log = str(e)

    checked_at = timezone.now()
    is_healthy = status_code is not None and status_code < 400

    url.is_healthy = is_healthy
    url.log = log
    url.last_checked = checked_at
    url.save(update_fields=["is_healthy", "log", "last_checked"])

    HealthCheckResult.objects.create(
        url=url,
        checked_at=checked_at,
        is_healthy=is_healthy,
        status_code=status_code,
        response_time_ms=response_time_ms,
        log=log,
    )

    if not is_healthy and url.notify:
        requests.post(
            os.environ.get('CHAT_HOOK_URL'),
            headers={'Content-Type': 'application/json'},
            json={
                "text": f"""[error]
project : {url.project.name}
service : {url.name}
url : {url.url}
log : {url.log[:500]}"""
            }
        )


@shared_task
def check_all_urls_health():
    urls = URL.objects.filter(is_use=True, project__is_use=True)
    for url in urls:
        _check_url_health(url)


@shared_task
def check_single_url_health(url_id):
    url = URL.objects.select_related("project").get(id=url_id, is_use=True, project__is_use=True)
    _check_url_health(url)

        
