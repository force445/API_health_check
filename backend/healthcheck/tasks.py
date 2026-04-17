# healthcheck/tasks.py
import os
import requests
from celery import shared_task
from .models import URL
from django.utils import timezone

@shared_task
def check_all_urls_health():
    urls = URL.objects.filter(is_use=True, project__is_use=True)
    log = ""
    status_code = 510
    for url in urls:
        try:
            response = requests.get(url.url, timeout=10, verify=False)
            status_code = response.status_code
            log = response.text
        except requests.RequestException as e:
            log = str(e)
        url.is_healthy = status_code < 400
        url.log = log
        url.last_checked = timezone.now()
        url.save()

        if url.is_healthy == False and url.notify:
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

        