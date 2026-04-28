from datetime import timedelta

import os
import time

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import models


def calculate_uptime(results):
    total_checks = len(results)
    if total_checks == 0:
        return None

    healthy_checks = sum(1 for result in results if result.is_healthy)
    return round((healthy_checks / total_checks) * 100, 1)


def get_active_urls_queryset():
    return (
        models.URL.objects.filter(project__is_use=True)
        .select_related("project")
        .prefetch_related("health_check_results")
        .order_by("project__name", "name")
    )


def filter_urls_queryset(urls_queryset, project_id, is_healthy, tag):
    if project_id:
        urls_queryset = urls_queryset.filter(project_id=project_id)

    if is_healthy in {"true", "false"}:
        urls_queryset = urls_queryset.filter(is_healthy=is_healthy == "true")

    if tag:
        urls_queryset = urls_queryset.filter(tag=tag)

    return urls_queryset


def group_urls_by_project(urls):
    grouped_urls = {}
    for url in urls:
        grouped_urls.setdefault(url.project_id, []).append(url)
    return grouped_urls


def build_project_health_data(projects, urls_by_project):
    project_health_data = []
    for project in projects:
        project_urls = urls_by_project.get(project.id, [])
        total_urls = len(project_urls)

        if total_urls:
            healthy_count = sum(1 for url in project_urls if url.is_healthy)
            healthy_percentage = (healthy_count / total_urls) * 100
            unhealthy_percentage = 100 - healthy_percentage
        else:
            healthy_percentage = 0
            unhealthy_percentage = 0

        project_health_data.append(
            {
                "project_name": project.name,
                "healthy_percentage": healthy_percentage,
                "unhealthy_percentage": unhealthy_percentage,
            }
        )

    return project_health_data


def annotate_urls_for_dashboard(urls, last_24_hours, last_7_days):
    for url in urls:
        history = list(url.health_check_results.all())
        recent_24h = [result for result in history if result.checked_at >= last_24_hours]
        recent_7d = [result for result in history if result.checked_at >= last_7_days]

        url.uptime_24h = calculate_uptime(recent_24h)
        url.uptime_7d = calculate_uptime(recent_7d)
        url.uptime_24h_display = "No data" if url.uptime_24h is None else f"{url.uptime_24h}%"
        url.uptime_7d_display = "No data" if url.uptime_7d is None else f"{url.uptime_7d}%"
        url.last_incident = next((result for result in history if not result.is_healthy), None)


def get_recent_incidents_queryset(project_id):
    recent_incidents_queryset = models.HealthCheckResult.objects.filter(
        url__project__is_use=True,
        is_healthy=False,
    )

    if project_id:
        recent_incidents_queryset = recent_incidents_queryset.filter(url__project_id=project_id)

    return recent_incidents_queryset


def get_available_tags():
    return (
        models.URL.objects.filter(project__is_use=True)
        .exclude(tag="")
        .order_by("tag")
        .values_list("tag", flat=True)
        .distinct()
    )


def build_trend_chart_data(urls):
    trend_chart_data = []

    for url in urls:
        recent_results = list(url.health_check_results.all()[:20])
        recent_results.reverse()

        trend_chart_data.append(
            {
                "url_id": url.id,
                "service_name": url.name,
                "project_name": url.project.name,
                "labels": [result.checked_at.isoformat() for result in recent_results],
                "statuses": [1 if result.is_healthy else 0 for result in recent_results],
                "response_times": [
                    result.response_time_ms if result.response_time_ms is not None else None
                    for result in recent_results
                ],
            }
        )

    return trend_chart_data


def build_dashboard_context(project_id, is_healthy, tag=None):
    now = timezone.now()
    last_24_hours = now - timedelta(hours=24)
    last_7_days = now - timedelta(days=7)

    active_urls_queryset = get_active_urls_queryset()
    urls_queryset = filter_urls_queryset(active_urls_queryset, project_id, is_healthy, tag)
    urls = list(urls_queryset)
    active_urls = list(active_urls_queryset)

    projects = models.Project.objects.filter(is_use=True).order_by("name")
    urls_by_project = group_urls_by_project(active_urls)

    project_health_data = build_project_health_data(projects, urls_by_project)
    annotate_urls_for_dashboard(urls, last_24_hours, last_7_days)

    recent_incidents_query = get_recent_incidents_queryset(project_id)
    recent_incidents = recent_incidents_query.select_related("url", "url__project")[:10]

    return {
        "urls": urls,
        "projects": projects,
        "tags": get_available_tags(),
        "selected_project": project_id,
        "selected_health": is_healthy,
        "selected_tag": tag,
        "project_health_data": project_health_data,
        "trend_chart_data": build_trend_chart_data(urls),
        "recent_incidents": recent_incidents,
        "tracked_services_count": len(urls),
        "current_unhealthy_count": sum(1 for url in urls if not url.is_healthy),
        "recent_incident_count": recent_incidents_query.count(),
    }


def queue_health_check(url_id=None):
    if url_id is None:
        run_all_active_health_checks()
        return None

    url = get_object_or_404(models.URL, id=url_id, is_use=True, project__is_use=True)
    run_url_health_check(url)
    return url


def run_url_health_check(url):
    log = ""
    status_code = None
    response_time_ms = None
    request_timeout = getattr(settings, "HEALTHCHECK_REQUEST_TIMEOUT_SECONDS", 10)
    request_attempts = max(1, getattr(settings, "HEALTHCHECK_REQUEST_ATTEMPTS", 2))

    for attempt in range(1, request_attempts + 1):
        try:
            started_at = time.monotonic()
            response = requests.get(url.url, timeout=request_timeout, verify=False)
            response_time_ms = round((time.monotonic() - started_at) * 1000)
            status_code = response.status_code
            log = response.text
            break
        except requests.RequestException as exc:
            log = str(exc)
            if attempt < request_attempts:
                continue

    checked_at = timezone.now()
    is_healthy = status_code is not None and status_code < 400

    url.is_healthy = is_healthy
    url.log = log
    url.last_checked = checked_at
    url.save(update_fields=["is_healthy", "log", "last_checked"])

    models.HealthCheckResult.objects.create(
        url=url,
        checked_at=checked_at,
        is_healthy=is_healthy,
        status_code=status_code,
        response_time_ms=response_time_ms,
        log=log,
    )

    if not is_healthy and url.notify:
        requests.post(
            os.environ.get("CHAT_HOOK_URL"),
            headers={"Content-Type": "application/json"},
            json={
                "text": f"""[error]
project : {url.project.name}
service : {url.name}
url : {url.url}
log : {url.log[:500]}"""
            },
        )


def run_all_active_health_checks():
    urls = models.URL.objects.filter(is_use=True, project__is_use=True).select_related("project")
    for url in urls:
        run_url_health_check(url)


def cleanup_old_health_check_results(retention_days=None):
    retention_days = retention_days if retention_days is not None else getattr(
        settings,
        "HEALTHCHECK_RESULT_RETENTION_DAYS",
        30,
    )
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = models.HealthCheckResult.objects.filter(checked_at__lt=cutoff).delete()
    return deleted_count
