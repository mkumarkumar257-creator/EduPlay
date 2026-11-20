from django.test import TestCase
from django.urls import reverse

from .models import User


PASSWORD = "A-secure-demo-pass-831!"


class PublicPageTests(TestCase):
    def test_home_about_login_and_registration_pages_load(self):
        for route in ("home", "about", "login", "register"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 200)


class RegistrationTests(TestCase):
    def post_registration(self, **overrides):
        data = {
            "full_name": "Ari Learner",
            "username": "ari",
            "email": "ari@example.com",
            "role": User.Role.LEARNER,
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return self.client.post(reverse("register"), data)

    def test_learner_registration_stores_hashed_password_and_signs_in(self):
        response = self.post_registration()
        self.assertRedirects(response, reverse("learner_dashboard"))
        user = User.objects.get(username="ari")
        self.assertEqual(user.role, User.Role.LEARNER)
        self.assertEqual(user.get_full_name(), "Ari Learner")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.client.get(reverse("learner_dashboard")).status_code, 200)

    def test_educator_can_register_and_reaches_educator_dashboard(self):
        response = self.post_registration(
            username="teacher",
            email="teacher@example.com",
            role=User.Role.EDUCATOR,
        )
        self.assertRedirects(response, reverse("educator_dashboard"))
        user = User.objects.get(username="teacher")
        self.assertEqual(user.role, User.Role.EDUCATOR)
        self.assertEqual(self.client.get(reverse("educator_dashboard")).status_code, 200)

    def test_registration_rejects_mismatched_passwords(self):
        response = self.post_registration(password2="Different-pass-572!")
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="ari").exists())

    def test_registration_uses_django_password_validators(self):
        response = self.post_registration(password1="password", password2="password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)

    def test_registration_rejects_invalid_email(self):
        response = self.post_registration(email="not-an-email")
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)

    def test_registration_rejects_duplicate_username_and_email(self):
        User.objects.create_user(username="ari", email="ari@example.com", password=PASSWORD)
        response = self.post_registration(username="ARI", email="other@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)


class LoginAndRoleTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner", email="learner@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="educator", email="educator@example.com", password=PASSWORD, role=User.Role.EDUCATOR
        )

    def test_username_login_redirects_learner_to_learner_dashboard(self):
        response = self.client.post(
            reverse("login"), {"username": "learner", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("learner_dashboard"))

    def test_email_login_redirects_educator_to_educator_dashboard(self):
        response = self.client.post(
            reverse("login"), {"username": "EDUCATOR@example.com", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("educator_dashboard"))

    def test_invalid_login_shows_generic_error(self):
        response = self.client.post(
            reverse("login"), {"username": "learner", "password": "incorrect"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertIsNone(response.context["form"].get_user())

    def test_remember_me_controls_session_expiry(self):
        self.client.post(reverse("login"), {"username": "learner", "password": PASSWORD})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.post(
            reverse("logout"),
        )
        self.client.post(
            reverse("login"),
            {"username": "learner", "password": PASSWORD, "remember_me": "on"},
        )
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_role_dashboards_require_login_and_reject_the_other_role(self):
        for route in ("dashboard", "learner_dashboard", "educator_dashboard", "profile"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("learner_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("educator_dashboard")).status_code, 403)
        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("educator_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("learner_dashboard")).status_code, 403)

    def test_dashboards_render_role_navigation_and_six_module_cards(self):
        self.client.force_login(self.learner)
        learner_page = self.client.get(reverse("learner_dashboard"))
        self.assertContains(learner_page, "Game Zone")
        self.assertContains(learner_page, "Simulation Lab")
        self.assertContains(learner_page, "Adaptive Learning")
        self.assertContains(learner_page, "Collaboration Hub")
        self.assertContains(learner_page, "Learning Path")
        self.assertContains(learner_page, "NO PERFORMANCE INFERENCES YET")
        self.assertNotContains(learner_page, "My Courses")
        self.assertContains(learner_page, "offcanvas-lg offcanvas-start")
        self.assertContains(learner_page, 'data-bs-target="#appSidebar"')
        self.assertContains(learner_page, 'aria-current="page"')
        self.assertEqual(learner_page.content.decode().count('<article class="module-card'), 6)
        self.assertContains(learner_page, "Open Game Zone")
        self.assertContains(learner_page, "Open Simulation Lab")
        self.assertContains(learner_page, "Open Learning Path")
        self.assertContains(learner_page, "Open Collaboration Hub")
        self.assertContains(learner_page, "Achievement tracking is not available yet")
        self.assertContains(learner_page, "No recent activity")
        self.assertContains(learner_page, "My Progress")
        self.assertContains(learner_page, "6 available")
        self.assertNotContains(learner_page, "lesson tracking are not implemented")

        self.client.force_login(self.educator)
        educator_page = self.client.get(reverse("educator_dashboard"))
        self.assertContains(educator_page, "Create Learning Content")
        self.assertNotContains(educator_page, "Game Zone")
        self.assertContains(educator_page, "LEARNER ACTIVITIES")


    def test_dashboard_root_redirects_to_signed_in_users_role(self):
        self.client.force_login(self.educator)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("educator_dashboard"))

    def test_logout_is_post_only_and_ends_session(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.get(reverse("learner_dashboard")).status_code, 302)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ari", email="ari@example.com", password=PASSWORD, role=User.Role.LEARNER
        )
        self.client.force_login(self.user)

    def test_profile_page_renders_read_only_identity_and_role(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Username")
        self.assertContains(response, "Role")
        self.assertContains(response, 'aria-current="page"')

    def test_profile_updates_name_and_email_but_ignores_role_changes(self):
        response = self.client.post(
            reverse("profile"),
            {
                "full_name": "Ari Updated",
                "email": "ari.updated@example.com",
                "role": User.Role.EDUCATOR,
            },
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), "Ari Updated")
        self.assertEqual(self.user.email, "ari.updated@example.com")
        self.assertEqual(self.user.role, User.Role.LEARNER)

    def test_profile_rejects_invalid_email(self):
        response = self.client.post(
            reverse("profile"), {"full_name": "Ari Learner", "email": "invalid"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)


class WorkspacePlaceholderTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner", email="learner@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="educator", email="educator@example.com", password=PASSWORD, role=User.Role.EDUCATOR
        )

    def test_learner_navigation_destinations_are_live_coming_soon_pages(self):
        features = (
            "achievements", "leaderboard", "settings",
        )
        self.client.force_login(self.learner)
        for feature in features:
            with self.subTest(feature=feature):
                response = self.client.get(reverse("workspace_placeholder", kwargs={"feature": feature}))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "COMING SOON")
                self.assertContains(response, 'aria-current="page"')
        self.assertRedirects(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "my-learning"})),
            reverse("learner_content_library"),
        )

    def test_legacy_simulations_placeholder_redirects_to_the_implemented_lab(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("workspace_placeholder", kwargs={"feature": "simulations"}))
        self.assertRedirects(response, reverse("simulation_lab"))

    def test_legacy_learning_paths_placeholder_redirects_to_adaptive_learning(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("workspace_placeholder", kwargs={"feature": "learning-paths"}))
        self.assertRedirects(response, reverse("adaptive_learning"))

    def test_legacy_game_zone_placeholder_redirects_to_the_implemented_game_zone(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("workspace_placeholder", kwargs={"feature": "game-zone"}))
        self.assertRedirects(response, reverse("game_zone"))

    def test_educator_navigation_destinations_are_live_coming_soon_pages(self):
        features = ("my-courses", "learners", "settings")
        self.client.force_login(self.educator)
        for feature in features:
            with self.subTest(feature=feature):
                response = self.client.get(reverse("workspace_placeholder", kwargs={"feature": feature}))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "COMING SOON")
        self.assertRedirects(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "content-library"})),
            reverse("educator_content_library"),
        )
        self.assertRedirects(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "create-content"})),
            reverse("educator_content_create"),
        )
        self.assertRedirects(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "analytics"})),
            reverse("educator_analytics"),
        )
        self.assertEqual(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "simulations"})).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "learning-paths"})).status_code,
            403,
        )

    def test_placeholder_routes_are_role_checked_and_unknown_slugs_return_404(self):
        self.client.force_login(self.learner)
        self.assertEqual(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "my-courses"})).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("workspace_placeholder", kwargs={"feature": "not-a-feature"})).status_code,
            404,
        )
