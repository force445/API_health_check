import os
from unittest.mock import Mock, patch

import requests
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Project, URL
from .tasks import check_all_urls_health


class HealthcheckModelTests(TestCase):
    def test_project_string_representation(self):
        project = Project(name="API", is_use=True)

        self.assertEqual(str(project), "API | True")

    def test_url_string_representation(self):
        project = Project.objects.create(name="Payments")
        url = URL.objects.create(project=project, name="Primary", url="https://example.com")

        self.assertEqual(str(url), "Payments Primary")


class DashboardViewTests(TestCase):
    def setUp(self):
        self.project_a = Project.objects.create(name="Project A", is_use=True)
        self.project_b = Project.objects.create(name="Project B", is_use=True)
        self.disabled_project = Project.objects.create(name="Disabled", is_use=False)

        self.url_a_healthy = URL.objects.create(
            project=self.project_a,
            name="Healthy URL",
            url="https://example.com/healthy",
            is_healthy=True,
        )
        self.url_a_unhealthy = URL.objects.create(
            project=self.project_a,
            name="Unhealthy URL",
            url="https://example.com/unhealthy",
            is_healthy=False,
        )
        self.url_b = URL.objects.create(
            project=self.project_b,
            name="Project B URL",
            url="https://example.org/status",
            is_healthy=True,
        )
        URL.objects.create(
            project=self.disabled_project,
            name="Disabled URL",
            url="https://disabled.example.com",
            is_healthy=True,
        )

    def test_dashboard_excludes_urls_from_disabled_projects(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context["urls"].order_by("id"),
            URL.objects.filter(project__is_use=True).order_by("id"),
            transform=lambda item: item,
        )
        self.assertNotContains(response, "Disabled URL")

    def test_dashboard_filters_by_project(self):
        response = self.client.get(reverse("dashboard"), {"project": self.project_a.id})

        self.assertEqual(list(response.context["urls"]), [self.url_a_healthy, self.url_a_unhealthy])

    def test_dashboard_filters_by_health_status(self):
        response = self.client.get(reverse("dashboard"), {"is_healthy": "false"})

        self.assertEqual(list(response.context["urls"]), [self.url_a_unhealthy])

    def test_dashboard_builds_project_health_percentages(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(
            response.context["project_health_data"],
            [
                {
                    "project_name": "Project A",
                    "healthy_percentage": 50.0,
                    "unhealthy_percentage": 50.0,
                },
                {
                    "project_name": "Project B",
                    "healthy_percentage": 100.0,
                    "unhealthy_percentage": 0.0,
                },
            ],
        )


class CheckAllUrlsHealthTaskTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Core", is_use=True)
        self.url = URL.objects.create(
            project=self.project,
            name="Service",
            url="https://service.example.com/health",
            notify=True,
        )

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.tasks.requests.post")
    @patch("healthcheck.tasks.requests.get")
    def test_marks_url_healthy_on_success(self, mock_get, mock_post):
        mock_get.return_value = Mock(status_code=200, text="ok")

        check_all_urls_health()

        self.url.refresh_from_db()
        self.assertTrue(self.url.is_healthy)
        self.assertEqual(self.url.log, "ok")
        self.assertIsNotNone(self.url.last_checked)
        mock_post.assert_not_called()

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.tasks.requests.post")
    @patch("healthcheck.tasks.requests.get")
    def test_sends_notification_when_url_is_unhealthy(self, mock_get, mock_post):
        mock_get.return_value = Mock(status_code=503, text="maintenance")

        check_all_urls_health()

        self.url.refresh_from_db()
        self.assertFalse(self.url.is_healthy)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(kwargs["json"]["text"].splitlines()[0], "[error]")
        self.assertIn("project : Core", kwargs["json"]["text"])
        self.assertIn("service : Service", kwargs["json"]["text"])
        self.assertIn("log : maintenance", kwargs["json"]["text"])

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.tasks.requests.post")
    @patch("healthcheck.tasks.requests.get")
    def test_request_exception_marks_url_unhealthy_and_notifies(self, mock_get, mock_post):
        mock_get.side_effect = requests.RequestException("timed out")

        check_all_urls_health()

        self.url.refresh_from_db()
        self.assertFalse(self.url.is_healthy)
        self.assertEqual(self.url.log, "timed out")
        self.assertIsNotNone(self.url.last_checked)
        mock_post.assert_called_once()
        self.assertIn("log : timed out", mock_post.call_args.kwargs["json"]["text"])

    @patch("healthcheck.tasks.requests.post")
    @patch("healthcheck.tasks.requests.get")
    def test_skips_notification_when_notify_is_disabled(self, mock_get, mock_post):
        self.url.notify = False
        self.url.save(update_fields=["notify"])
        mock_get.return_value = Mock(status_code=500, text="down")

        check_all_urls_health()

        self.url.refresh_from_db()
        self.assertFalse(self.url.is_healthy)
        mock_post.assert_not_called()

    @patch("healthcheck.tasks.requests.get")
    def test_skips_disabled_urls_and_projects(self, mock_get):
        disabled_url = URL.objects.create(
            project=self.project,
            name="Disabled URL",
            url="https://service.example.com/disabled",
            is_use=False,
        )
        disabled_project = Project.objects.create(name="Disabled Project", is_use=False)
        project_url = URL.objects.create(
            project=disabled_project,
            name="Disabled Project URL",
            url="https://service.example.com/project-disabled",
        )
        previous_disabled_url_checked = disabled_url.last_checked
        previous_project_url_checked = project_url.last_checked

        mock_get.return_value = Mock(status_code=200, text="ok")

        check_all_urls_health()

        self.url.refresh_from_db()
        disabled_url.refresh_from_db()
        project_url.refresh_from_db()
        self.assertTrue(self.url.is_healthy)
        self.assertIsNotNone(self.url.last_checked)
        self.assertEqual(disabled_url.last_checked, previous_disabled_url_checked)
        self.assertEqual(project_url.last_checked, previous_project_url_checked)
        mock_get.assert_called_once_with(self.url.url, timeout=10, verify=False)
