from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import models
from .tasks import check_all_urls_health, check_single_url_health


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


def filter_urls_queryset(urls_queryset, project_id, is_healthy):
    if project_id:
        urls_queryset = urls_queryset.filter(project_id=project_id)

    if is_healthy in {"true", "false"}:
        urls_queryset = urls_queryset.filter(is_healthy=is_healthy == "true")

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


def build_dashboard_context(project_id, is_healthy):
    now = timezone.now()
    last_24_hours = now - timedelta(hours=24)
    last_7_days = now - timedelta(days=7)

    active_urls_queryset = get_active_urls_queryset()
    urls_queryset = filter_urls_queryset(active_urls_queryset, project_id, is_healthy)
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
        "selected_project": project_id,
        "selected_health": is_healthy,
        "project_health_data": project_health_data,
        "recent_incidents": recent_incidents,
        "tracked_services_count": len(urls),
        "current_unhealthy_count": sum(1 for url in urls if not url.is_healthy),
        "recent_incident_count": recent_incidents_query.count(),
    }


def queue_health_check(url_id=None):
    if url_id is None:
        check_all_urls_health.delay()
        return None

    url = get_object_or_404(models.URL, id=url_id, is_use=True, project__is_use=True)
    check_single_url_health.delay(url.id)
    return url
