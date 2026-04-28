from django.contrib import admin
from . import models


class ProjectAdmin(admin.ModelAdmin):
    list_display = [f.name for f in models.Project._meta.fields]
    search_fields = ['name']
    list_filter = ['is_use']
admin.site.register(models.Project, ProjectAdmin)


class URLAdmin(admin.ModelAdmin):
    list_display = [f.name for f in models.URL._meta.fields if f.name not in ['log']]
    search_fields = ['project__name', 'name', 'url', 'tag']
    list_filter = ['is_healthy', 'tag', 'project__name']
    autocomplete_fields = ['project']
admin.site.register(models.URL, URLAdmin)


class HealthCheckResultAdmin(admin.ModelAdmin):
    list_display = ["url", "checked_at", "is_healthy", "status_code", "response_time_ms"]
    search_fields = ["url__name", "url__url", "url__project__name"]
    list_filter = ["is_healthy", "url__project__name"]
    autocomplete_fields = ["url"]
    ordering = ["-checked_at"]


admin.site.register(models.HealthCheckResult, HealthCheckResultAdmin)
