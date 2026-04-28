import os
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import HealthCheckResult, Project, URL
from .tasks import check_all_urls_health, cleanup_health_check_results
from .services import cleanup_old_health_check_results


class HealthcheckModelTests(TestCase):
    def test_project_string_representation(self):
        project = Project(name="API", is_use=True)

        self.assertEqual(str(project), "API | True")

    def test_url_string_representation(self):
        project = Project.objects.create(name="Payments")
        url = URL.objects.create(project=project, name="Primary", url="https://example.com")

        self.assertEqual(str(url), "Payments Primary")

    def test_health_check_result_string_representation(self):
        project = Project.objects.create(name="Payments")
        url = URL.objects.create(project=project, name="Primary", url="https://example.com")
        checked_at = timezone.now()
        result = HealthCheckResult.objects.create(
            url=url,
            checked_at=checked_at,
            is_healthy=True,
            status_code=200,
            response_time_ms=123,
            log="ok",
        )

        self.assertEqual(str(result), f"Payments Primary @ {checked_at.isoformat()} | True")


class DashboardViewTests(TestCase):
    def setUp(self):
        self.staff_user = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.project_a = Project.objects.create(name="Project A", is_use=True)
        self.project_b = Project.objects.create(name="Project B", is_use=True)
        self.disabled_project = Project.objects.create(name="Disabled", is_use=False)

        self.url_a_healthy = URL.objects.create(
            project=self.project_a,
            name="Healthy URL",
            tag="production",
            url="https://example.com/healthy",
            is_healthy=True,
        )
        self.url_a_unhealthy = URL.objects.create(
            project=self.project_a,
            name="Unhealthy URL",
            tag="staging",
            url="https://example.com/unhealthy",
            is_healthy=False,
        )
        self.url_b = URL.objects.create(
            project=self.project_b,
            name="Project B URL",
            tag="production",
            url="https://example.org/status",
            is_healthy=True,
        )
        URL.objects.create(
            project=self.disabled_project,
            name="Disabled URL",
            url="https://disabled.example.com",
            is_healthy=True,
        )
        now = timezone.now()
        HealthCheckResult.objects.create(
            url=self.url_a_healthy,
            checked_at=now - timedelta(hours=2),
            is_healthy=True,
            status_code=200,
            response_time_ms=100,
            log="ok",
        )
        HealthCheckResult.objects.create(
            url=self.url_a_healthy,
            checked_at=now - timedelta(hours=1),
            is_healthy=False,
            status_code=500,
            response_time_ms=200,
            log="down",
        )
        HealthCheckResult.objects.create(
            url=self.url_a_healthy,
            checked_at=now - timedelta(days=2),
            is_healthy=True,
            status_code=200,
            response_time_ms=95,
            log="ok",
        )
        HealthCheckResult.objects.create(
            url=self.url_a_unhealthy,
            checked_at=now - timedelta(hours=3),
            is_healthy=False,
            status_code=503,
            response_time_ms=250,
            log="maintenance",
        )
        HealthCheckResult.objects.create(
            url=self.url_b,
            checked_at=now - timedelta(days=8),
            is_healthy=True,
            status_code=200,
            response_time_ms=110,
            log="ok",
        )

    def login(self):
        self.client.force_login(self.staff_user)

    def test_dashboard_requires_staff_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('admin:login')}?next={reverse('dashboard')}")

    def test_dashboard_excludes_urls_from_disabled_projects(self):
        self.login()
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["urls"],
            list(URL.objects.filter(project__is_use=True).order_by("project__name", "name")),
        )
        self.assertNotContains(response, "Disabled URL")

    def test_dashboard_shows_logout_button(self):
        self.login()
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'action="/admin/logout/"', html=False)
        self.assertContains(response, "Logout")

    def test_dashboard_filters_by_project(self):
        self.login()
        response = self.client.get(reverse("dashboard"), {"project": self.project_a.id})

        self.assertEqual(list(response.context["urls"]), [self.url_a_healthy, self.url_a_unhealthy])

    def test_dashboard_filters_by_health_status(self):
        self.login()
        response = self.client.get(reverse("dashboard"), {"is_healthy": "false"})

        self.assertEqual(list(response.context["urls"]), [self.url_a_unhealthy])

    def test_dashboard_filters_by_tag(self):
        self.login()
        response = self.client.get(reverse("dashboard"), {"tag": "staging"})

        self.assertEqual(list(response.context["urls"]), [self.url_a_unhealthy])
        self.assertEqual(response.context["selected_tag"], "staging")
        self.assertEqual(list(response.context["tags"]), ["production", "staging"])

    def test_dashboard_builds_project_health_percentages(self):
        self.login()
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

    def test_dashboard_adds_uptime_percentages_from_history(self):
        self.login()
        response = self.client.get(reverse("dashboard"))

        urls_by_name = {url.name: url for url in response.context["urls"]}
        self.assertEqual(urls_by_name["Healthy URL"].uptime_24h, 50.0)
        self.assertEqual(urls_by_name["Healthy URL"].uptime_7d, 66.7)
        self.assertEqual(urls_by_name["Unhealthy URL"].uptime_24h, 0.0)
        self.assertEqual(urls_by_name["Project B URL"].uptime_24h, None)
        self.assertEqual(urls_by_name["Project B URL"].uptime_7d, None)

    def test_dashboard_exposes_trend_chart_data(self):
        self.login()
        response = self.client.get(reverse("dashboard"), {"tag": "production"})

        trend_data = {
            item["service_name"]: item
            for item in response.context["trend_chart_data"]
        }
        self.assertEqual(set(trend_data), {"Healthy URL", "Project B URL"})
        self.assertEqual(trend_data["Healthy URL"]["project_name"], "Project A")
        self.assertEqual(trend_data["Healthy URL"]["statuses"], [1, 1, 0])
        self.assertEqual(trend_data["Healthy URL"]["response_times"], [95, 100, 200])

    def test_dashboard_exposes_recent_incidents(self):
        self.login()
        response = self.client.get(reverse("dashboard"))

        recent_incidents = list(response.context["recent_incidents"])
        self.assertEqual(len(recent_incidents), 2)
        self.assertEqual(recent_incidents[0].url, self.url_a_healthy)
        self.assertEqual(recent_incidents[1].url, self.url_a_unhealthy)
        self.assertEqual(response.context["current_unhealthy_count"], 1)
        self.assertEqual(response.context["recent_incident_count"], 2)

    @patch("healthcheck.services.run_all_active_health_checks")
    def test_check_now_queues_global_health_check(self, mock_run_all):
        self.login()
        response = self.client.post(reverse("check_now"), {"next": reverse("dashboard")})

        self.assertEqual(response.status_code, 302)
        mock_run_all.assert_called_once_with()

    def test_check_now_requires_staff_login(self):
        response = self.client.post(reverse("check_now"), {"next": reverse("dashboard")})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('admin:login')}?next={reverse('check_now')}")

    @patch("healthcheck.services.run_url_health_check")
    def test_check_now_queues_single_url_health_check(self, mock_run_url_health_check):
        self.login()
        response = self.client.post(
            reverse("check_url_now", args=[self.url_a_healthy.id]),
            {"next": reverse("dashboard")},
        )

        self.assertEqual(response.status_code, 302)
        mock_run_url_health_check.assert_called_once()
        called_url = mock_run_url_health_check.call_args.args[0]
        self.assertEqual(called_url.id, self.url_a_healthy.id)


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
    @patch("healthcheck.services.requests.post")
    @patch("healthcheck.services.requests.get")
    def test_marks_url_healthy_on_success(self, mock_get, mock_post):
        mock_get.return_value = Mock(status_code=200, text="ok")

        check_all_urls_health()

        self.url.refresh_from_db()
        result = HealthCheckResult.objects.get(url=self.url)
        self.assertTrue(self.url.is_healthy)
        self.assertEqual(self.url.log, "ok")
        self.assertIsNotNone(self.url.last_checked)
        self.assertTrue(result.is_healthy)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.log, "ok")
        self.assertIsNotNone(result.response_time_ms)
        mock_post.assert_not_called()

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.services.requests.post")
    @patch("healthcheck.services.requests.get")
    def test_sends_notification_when_url_is_unhealthy(self, mock_get, mock_post):
        mock_get.return_value = Mock(status_code=503, text="maintenance")

        check_all_urls_health()

        self.url.refresh_from_db()
        result = HealthCheckResult.objects.get(url=self.url)
        self.assertFalse(self.url.is_healthy)
        self.assertFalse(result.is_healthy)
        self.assertEqual(result.status_code, 503)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(kwargs["json"]["text"].splitlines()[0], "[error]")
        self.assertIn("project : Core", kwargs["json"]["text"])
        self.assertIn("service : Service", kwargs["json"]["text"])
        self.assertIn("log : maintenance", kwargs["json"]["text"])

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.services.requests.post")
    @patch("healthcheck.services.requests.get")
    def test_request_exception_marks_url_unhealthy_and_notifies(self, mock_get, mock_post):
        mock_get.side_effect = requests.RequestException("timed out")

        check_all_urls_health()

        self.url.refresh_from_db()
        result = HealthCheckResult.objects.get(url=self.url)
        self.assertFalse(self.url.is_healthy)
        self.assertEqual(self.url.log, "timed out")
        self.assertIsNotNone(self.url.last_checked)
        self.assertFalse(result.is_healthy)
        self.assertIsNone(result.status_code)
        self.assertIsNone(result.response_time_ms)
        mock_post.assert_called_once()
        self.assertIn("log : timed out", mock_post.call_args.kwargs["json"]["text"])
        self.assertEqual(mock_get.call_count, 2)

    @patch.dict(os.environ, {"CHAT_HOOK_URL": "https://chat.example.com/hook"}, clear=False)
    @patch("healthcheck.services.requests.post")
    @patch("healthcheck.services.requests.get")
    def test_transient_request_exception_retries_before_alerting(self, mock_get, mock_post):
        mock_get.side_effect = [
            requests.ReadTimeout("read timed out"),
            Mock(status_code=200, text="ok"),
        ]

        check_all_urls_health()

        self.url.refresh_from_db()
        result = HealthCheckResult.objects.get(url=self.url)
        self.assertTrue(self.url.is_healthy)
        self.assertTrue(result.is_healthy)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.log, "ok")
        self.assertEqual(mock_get.call_count, 2)
        mock_post.assert_not_called()

    @patch("healthcheck.services.requests.post")
    @patch("healthcheck.services.requests.get")
    def test_skips_notification_when_notify_is_disabled(self, mock_get, mock_post):
        self.url.notify = False
        self.url.save(update_fields=["notify"])
        mock_get.return_value = Mock(status_code=500, text="down")

        check_all_urls_health()

        self.url.refresh_from_db()
        self.assertFalse(self.url.is_healthy)
        self.assertEqual(HealthCheckResult.objects.filter(url=self.url).count(), 1)
        mock_post.assert_not_called()

    @patch("healthcheck.services.requests.get")
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
        self.assertEqual(HealthCheckResult.objects.count(), 1)
        mock_get.assert_called_once_with(self.url.url, timeout=10, verify=False)


class HealthCheckResultRetentionTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Retention", is_use=True)
        self.url = URL.objects.create(
            project=self.project,
            name="Service",
            url="https://service.example.com/health",
        )

    def test_cleanup_old_health_check_results_deletes_stale_rows(self):
        old_result = HealthCheckResult.objects.create(
            url=self.url,
            checked_at=timezone.now() - timedelta(days=40),
            is_healthy=True,
            status_code=200,
            response_time_ms=100,
            log="old",
        )
        recent_result = HealthCheckResult.objects.create(
            url=self.url,
            checked_at=timezone.now() - timedelta(days=5),
            is_healthy=True,
            status_code=200,
            response_time_ms=90,
            log="recent",
        )

        deleted_count = cleanup_old_health_check_results(retention_days=30)

        self.assertEqual(deleted_count, 1)
        self.assertFalse(HealthCheckResult.objects.filter(id=old_result.id).exists())
        self.assertTrue(HealthCheckResult.objects.filter(id=recent_result.id).exists())

    def test_cleanup_health_check_results_task_uses_service_default(self):
        with patch("healthcheck.tasks.cleanup_old_health_check_results", return_value=3) as mock_cleanup:
            result = cleanup_health_check_results()

        self.assertEqual(result, 3)
        mock_cleanup.assert_called_once_with()
