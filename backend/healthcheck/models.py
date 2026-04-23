from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=100)
    is_use = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.name} | {self.is_use}"


class URL(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    url = models.URLField(unique=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    is_healthy = models.BooleanField(default=False)
    log = models.TextField(default='-')

    is_use = models.BooleanField(default=True)
    notify = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.project.name} {self.name}"


class HealthCheckResult(models.Model):
    url = models.ForeignKey(URL, on_delete=models.CASCADE, related_name="health_check_results")
    checked_at = models.DateTimeField()
    is_healthy = models.BooleanField()
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    log = models.TextField(default="-")

    class Meta:
        ordering = ["-checked_at", "-id"]

    def __str__(self):
        return f"{self.url} @ {self.checked_at.isoformat()} | {self.is_healthy}"
