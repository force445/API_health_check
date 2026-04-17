from django.db import models

# Create your models here.
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