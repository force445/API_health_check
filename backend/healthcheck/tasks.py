from celery import shared_task

from . import models
from .services import cleanup_old_health_check_results, run_all_active_health_checks, run_url_health_check


@shared_task
def check_all_urls_health():
    run_all_active_health_checks()


@shared_task
def check_single_url_health(url_id):
    url = models.URL.objects.select_related("project").get(
        id=url_id,
        is_use=True,
        project__is_use=True,
    )
    run_url_health_check(url)


@shared_task
def cleanup_health_check_results():
    return cleanup_old_health_check_results()
