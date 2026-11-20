from django.test import TestCase
from django.urls import reverse

from .models import Simulation, SimulationAttempt, SimulationCompletion, User
from .simulation_engine import calculate_computer_performance


PASSWORD = "A-secure-demo-pass-831!"


class ComputerPerformanceLabTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="simlearner", email="simlearner@example.com", password=PASSWORD
        )
        self.other_learner = User.objects.create_user(
            username="otherlearner", email="otherlearner@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="simeducator",
            email="simeducator@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
        )
        self.simulation = Simulation.objects.get(slug="computer-system-performance-lab")
        self.client.force_login(self.learner)

    def run_experiment(self, **overrides):
        values = {
            "cpu_workload": 55,
            "process_count": 4,
            "ram_gb": 8,
            "background_workload": 20,
        }
        values.update(overrides)
        response = self.client.post(
            reverse("run_simulation", kwargs={"slug": self.simulation.slug}), values
        )
        return response

    def test_simulation_lab_is_learner_only_and_only_implemented_simulation_is_playable(self):
        page = self.client.get(reverse("simulation_lab"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Simulation Lab")
        self.assertContains(page, "Computer System Performance Lab")
        self.assertContains(page, "Start Experiment")
        self.assertContains(page, "Network Traffic Explorer")
        self.assertContains(page, "Coming soon")
        self.assertEqual(page.content.decode().count('class="btn simulation-disabled-button"'), 3)

        self.client.logout()
        self.assertEqual(self.client.get(reverse("simulation_lab")).status_code, 302)
        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("simulation_lab")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("simulation_detail", kwargs={"slug": self.simulation.slug})).status_code,
            403,
        )

    def test_lab_card_opens_controls_and_legacy_navigation_redirects(self):
        detail = self.client.get(reverse("simulation_detail", kwargs={"slug": self.simulation.slug}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "CPU workload")
        self.assertContains(detail, "Number of processes")
        self.assertContains(detail, "How the estimates are calculated")
        self.assertContains(detail, 'min="10"')
        self.assertContains(detail, 'max="32"')
        self.assertFalse(SimulationAttempt.objects.filter(user=self.learner).exists())

        legacy = self.client.get(reverse("workspace_placeholder", kwargs={"feature": "simulations"}))
        self.assertRedirects(legacy, reverse("simulation_lab"))

    def test_server_validates_input_saves_estimates_and_awards_xp_once(self):
        invalid = self.run_experiment(cpu_workload=101)
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "Ensure this value is less than or equal to 100")
        self.assertFalse(SimulationAttempt.objects.filter(user=self.learner).exists())
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.total_xp, 0)

        response = self.run_experiment(cpu_workload=90, process_count=14, ram_gb=4, background_workload=60)
        self.assertEqual(response.status_code, 302)
        attempt = SimulationAttempt.objects.get(user=self.learner)
        self.assertRedirects(
            response,
            f"{reverse('simulation_detail', kwargs={'slug': self.simulation.slug})}?run={attempt.pk}",
        )
        self.assertEqual(attempt.parameters["cpu_workload"], 90)
        self.assertEqual(attempt.results["cpu_utilization_percent"], 100)
        self.assertGreater(attempt.results["memory_utilization_percent"], 70)
        self.assertIn(attempt.results["system_condition"], {"Healthy", "Moderate load", "Under pressure", "Critical load"})
        self.assertGreater(attempt.results["estimated_response_ms"], 120)
        self.assertEqual(attempt.xp_awarded, self.simulation.xp_reward)
        self.assertTrue(SimulationCompletion.objects.filter(user=self.learner, simulation=self.simulation).exists())
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.total_xp, self.simulation.xp_reward)

        result_page = self.client.get(response["Location"])
        self.assertContains(result_page, "Experiment result")
        self.assertContains(result_page, "CPU saturation")
        self.assertContains(result_page, "Live output")

        repeated = self.run_experiment(cpu_workload=45, process_count=2, ram_gb=16, background_workload=10)
        second_attempt = SimulationAttempt.objects.exclude(pk=attempt.pk).get(user=self.learner)
        self.assertEqual(repeated.status_code, 302)
        self.assertEqual(second_attempt.xp_awarded, 0)
        self.assertEqual(SimulationCompletion.objects.filter(user=self.learner, simulation=self.simulation).count(), 1)
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.total_xp, self.simulation.xp_reward)

        lab_page = self.client.get(reverse("simulation_lab"))
        self.assertContains(lab_page, "Completed")
        self.assertContains(lab_page, "2 experiments saved")

    def test_experiment_comparison_and_history_are_scoped_to_the_signed_in_learner(self):
        first_response = self.run_experiment(cpu_workload=35, process_count=2, ram_gb=16, background_workload=5)
        first = SimulationAttempt.objects.get(user=self.learner)
        second_response = self.run_experiment(cpu_workload=85, process_count=12, ram_gb=4, background_workload=75)
        second = SimulationAttempt.objects.exclude(pk=first.pk).get(user=self.learner)
        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)

        compare_url = f"{reverse('simulation_detail', kwargs={'slug': self.simulation.slug})}?run={second.pk}&compare={first.pk}"
        comparison = self.client.get(compare_url)
        self.assertContains(comparison, "What changed?")
        self.assertContains(comparison, "CPU utilization")
        self.assertContains(comparison, "Difference")
        self.assertContains(comparison, "Experiment history")

        self.client.force_login(self.other_learner)
        self.assertEqual(self.client.get(compare_url).status_code, 404)
        private_run = f"{reverse('simulation_detail', kwargs={'slug': self.simulation.slug})}?run={second.pk}"
        self.assertEqual(self.client.get(private_run).status_code, 404)

    def test_run_route_is_post_only_and_simulation_engine_checks_bounds(self):
        route = reverse("run_simulation", kwargs={"slug": self.simulation.slug})
        self.assertEqual(self.client.get(route).status_code, 405)
        self.client.force_login(self.educator)
        self.assertEqual(self.client.post(route).status_code, 403)

        with self.assertRaises(ValueError):
            calculate_computer_performance(
                {"cpu_workload": 9, "process_count": 4, "ram_gb": 8, "background_workload": 0}
            )

    def test_engine_outputs_respond_to_resource_changes(self):
        light = calculate_computer_performance(
            {"cpu_workload": 25, "process_count": 2, "ram_gb": 16, "background_workload": 5}
        )
        heavy = calculate_computer_performance(
            {"cpu_workload": 95, "process_count": 18, "ram_gb": 2, "background_workload": 85}
        )
        self.assertGreater(heavy["cpu_utilization_percent"], light["cpu_utilization_percent"])
        self.assertGreater(heavy["memory_utilization_percent"], light["memory_utilization_percent"])
        self.assertGreater(heavy["system_load"], light["system_load"])
        self.assertLess(heavy["performance_score"], light["performance_score"])
        self.assertGreater(heavy["estimated_response_ms"], light["estimated_response_ms"])
