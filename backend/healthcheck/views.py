from django.shortcuts import render
from . import models
from django.db.models import Count, Q
# Create your views here.

def dashboard_view(request):
# Get filter parameters from the request
    project_id = request.GET.get('project')
    is_healthy = request.GET.get('is_healthy')

    # Filter URLs by project and is_healthy status
    urls = models.URL.objects.filter(project__is_use=True)

    if project_id:
        urls = urls.filter(project__id=project_id)
    
    if is_healthy:
        is_healthy_bool = True if is_healthy == 'true' else False
        urls = urls.filter(is_healthy=is_healthy_bool)
    
    # Fetch projects for filter dropdown
    projects = models.Project.objects.filter(is_use=True)

    # Count healthy and unhealthy URLs per project for the chart
    project_health_data = []
    for project in projects:
        total_urls = project.url_set.count()
        if total_urls > 0:
            healthy_count = project.url_set.filter(is_healthy=True).count()
            unhealthy_count = total_urls - healthy_count
            healthy_percentage = (healthy_count / total_urls) * 100
            unhealthy_percentage = (unhealthy_count / total_urls) * 100
        else:
            healthy_percentage = 0
            unhealthy_percentage = 0
        
        project_health_data.append({
            'project_name': project.name,
            'healthy_percentage': healthy_percentage,
            'unhealthy_percentage': unhealthy_percentage
        })

    context = {
        'urls': urls,
        'projects': projects,
        'selected_project': project_id,
        'selected_health': is_healthy,
        'project_health_data': project_health_data,
    }

    return render(request, 'healthcheck/dashboard.html', context)