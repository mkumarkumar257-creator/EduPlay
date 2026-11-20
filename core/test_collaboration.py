from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Challenge, Team, TeamActivity, TeamChallenge, TeamMembership, User


PASSWORD = "A-secure-demo-pass-831!"


class CollaborationTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="collablearner", email="collablearner@example.com", password=PASSWORD
        )
        self.second_learner = User.objects.create_user(
            username="collabpartner", email="collabpartner@example.com", password=PASSWORD
        )
        self.third_learner = User.objects.create_user(
            username="collabguest", email="collabguest@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="collabeducator",
            email="collabeducator@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
        )
        self.challenge = Challenge.objects.get(slug="api-design-code-sprint")
        self.client.force_login(self.learner)

    def create_team(self, user=None, name="Byte Brigade"):
        if user is not None:
            self.client.force_login(user)
        response = self.client.post(
            reverse("collaboration_create_team"),
            {"name": name, "description": "A team learning by building together.", "avatar": "⚡"},
        )
        team = Team.objects.get(name=name)
        return response, team

    def join_team(self, user, team):
        self.client.force_login(user)
        return self.client.post(reverse("collaboration_join_team"), {"join_code": team.join_code.lower()})

    def start_challenge(self, team=None):
        if team is None:
            team = Team.objects.get(leader=self.learner, is_active=True)
        response = self.client.post(
            reverse("collaboration_start_challenge", kwargs={"slug": self.challenge.slug})
        )
        participation = TeamChallenge.objects.get(team=team, challenge=self.challenge)
        return response, participation

    def submit_challenge(self, participation, submission_text=None):
        return self.client.post(
            reverse(
                "collaboration_submit_challenge",
                kwargs={"slug": self.challenge.slug, "participation_id": participation.pk},
            ),
            {"submission_text": submission_text or (
                "Our team designed a safe endpoint with validated input, a clear response for invalid "
                "requests, and parameterized database operations to protect stored course data."
            )},
        )

    def test_hub_has_honest_empty_states_and_restricts_roles(self):
        response = self.client.get(reverse("collaboration_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create a team")
        self.assertContains(response, "Join a team")
        self.assertContains(response, "SEEDED SAMPLE")
        self.assertContains(response, "Team rankings are getting started")
        self.assertEqual(response.context["available_challenges"].__len__(), 5)

        self.client.logout()
        self.assertEqual(self.client.get(reverse("collaboration_hub")).status_code, 302)
        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("collaboration_hub")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("collaboration_challenge", kwargs={"slug": self.challenge.slug})).status_code,
            403,
        )

    def test_team_creation_generates_code_and_makes_creator_leader(self):
        response, team = self.create_team()
        self.assertRedirects(response, reverse("collaboration_team", kwargs={"team_id": team.pk}))
        self.assertEqual(len(team.join_code), 8)
        self.assertEqual(team.join_code, team.join_code.upper())
        self.assertEqual(team.leader, self.learner)
        self.assertTrue(TeamMembership.objects.filter(team=team, user=self.learner, left_at__isnull=True).exists())
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.TEAM_CREATED).count(), 1)

    def test_join_code_validation_duplicate_membership_and_one_team_rule(self):
        _, team = self.create_team()
        invalid = self.client.post(reverse("collaboration_join_team"), {"join_code": "NOTACODE"})
        self.assertRedirects(invalid, reverse("collaboration_hub"))
        self.assertEqual(TeamMembership.objects.filter(team=team).count(), 1)

        self.join_team(self.second_learner, team)
        first_join_count = team.activity.filter(event_type=TeamActivity.Event.MEMBER_JOINED).count()
        self.join_team(self.second_learner, team)
        self.assertEqual(
            TeamMembership.objects.filter(team=team, user=self.second_learner, left_at__isnull=True).count(), 1
        )
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.MEMBER_JOINED).count(), first_join_count)

        _, other_team = self.create_team(self.third_learner, name="Data Sprinters")
        self.client.force_login(self.second_learner)
        attempted = self.client.post(reverse("collaboration_join_team"), {"join_code": other_team.join_code})
        self.assertRedirects(attempted, reverse("collaboration_hub"))
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=self.second_learner, left_at__isnull=True).exists()
        )

    @override_settings(EDUPLAY_MAX_TEAM_SIZE=2)
    def test_team_size_limit_is_enforced(self):
        _, team = self.create_team()
        self.join_team(self.second_learner, team)
        response = self.join_team(self.third_learner, team)
        self.assertRedirects(response, reverse("collaboration_hub"))
        self.assertEqual(team.memberships.filter(left_at__isnull=True).count(), 2)
        self.assertFalse(
            TeamMembership.objects.filter(team=team, user=self.third_learner, left_at__isnull=True).exists()
        )

    def test_leader_transfer_member_management_and_leaving_rules(self):
        _, team = self.create_team()
        self.join_team(self.second_learner, team)
        self.join_team(self.third_learner, team)

        self.client.force_login(self.learner)
        forbidden_leave = self.client.post(reverse("collaboration_leave_team", kwargs={"team_id": team.pk}))
        self.assertRedirects(forbidden_leave, reverse("collaboration_hub"))
        self.assertTrue(TeamMembership.objects.filter(team=team, user=self.learner, left_at__isnull=True).exists())

        self.client.force_login(self.second_learner)
        forbidden_update = self.client.post(
            reverse("collaboration_update_team", kwargs={"team_id": team.pk}),
            {"name": "Hijacked", "description": "No", "avatar": "⭐"},
        )
        self.assertRedirects(forbidden_update, reverse("collaboration_team", kwargs={"team_id": team.pk}))
        team.refresh_from_db()
        self.assertEqual(team.name, "Byte Brigade")
        forbidden_remove = self.client.post(
            reverse(
                "collaboration_remove_member",
                kwargs={"team_id": team.pk, "member_id": self.third_learner.pk},
            )
        )
        self.assertRedirects(forbidden_remove, reverse("collaboration_team", kwargs={"team_id": team.pk}))
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=self.third_learner, left_at__isnull=True).exists()
        )

        self.client.force_login(self.learner)
        transfer = self.client.post(
            reverse(
                "collaboration_transfer_leadership",
                kwargs={"team_id": team.pk, "member_id": self.second_learner.pk},
            )
        )
        self.assertRedirects(transfer, reverse("collaboration_team", kwargs={"team_id": team.pk}))
        team.refresh_from_db()
        self.assertEqual(team.leader, self.second_learner)

        leave = self.client.post(reverse("collaboration_leave_team", kwargs={"team_id": team.pk}))
        self.assertRedirects(leave, reverse("collaboration_hub"))
        self.assertIsNotNone(TeamMembership.objects.get(team=team, user=self.learner).left_at)
        self.assertTrue(team.is_active)

        self.client.force_login(self.second_learner)
        remove = self.client.post(
            reverse(
                "collaboration_remove_member",
                kwargs={"team_id": team.pk, "member_id": self.third_learner.pk},
            )
        )
        self.assertRedirects(remove, reverse("collaboration_team", kwargs={"team_id": team.pk}))
        self.assertIsNotNone(TeamMembership.objects.get(team=team, user=self.third_learner).left_at)
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.LEADER_TRANSFERRED).count(), 1)

    def test_last_leader_leaves_by_archiving_team_without_erasing_it(self):
        _, team = self.create_team()
        response = self.client.post(reverse("collaboration_leave_team", kwargs={"team_id": team.pk}))
        self.assertRedirects(response, reverse("collaboration_hub"))
        team.refresh_from_db()
        self.assertFalse(team.is_active)
        self.assertTrue(Team.objects.filter(pk=team.pk).exists())
        self.assertIsNotNone(TeamMembership.objects.get(team=team, user=self.learner).left_at)
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.TEAM_ARCHIVED).count(), 1)

    def test_team_details_are_private_to_active_members(self):
        _, team = self.create_team()
        self.client.force_login(self.third_learner)
        self.assertEqual(
            self.client.get(reverse("collaboration_team", kwargs={"team_id": team.pk})).status_code,
            404,
        )

    def test_challenge_submission_must_belong_to_the_signed_in_learners_team(self):
        _, first_team = self.create_team(name="Byte Brigade")
        _, participation = self.start_challenge(first_team)
        _, other_team = self.create_team(self.third_learner, name="Data Sprinters")
        self.client.force_login(self.third_learner)
        response = self.submit_challenge(participation)
        self.assertEqual(response.status_code, 404)
        first_team.refresh_from_db()
        other_team.refresh_from_db()
        self.assertEqual(first_team.total_xp, 0)
        self.assertEqual(other_team.total_xp, 0)

    def test_challenge_participation_completion_and_rewards_are_once_only(self):
        _, team = self.create_team()
        self.join_team(self.second_learner, team)
        self.client.force_login(self.learner)
        response, participation = self.start_challenge(team)
        self.assertRedirects(response, reverse("collaboration_challenge", kwargs={"slug": self.challenge.slug}))
        self.assertEqual(participation.status, TeamChallenge.Status.IN_PROGRESS)
        self.assertEqual(participation.progress_percent, 0)

        self.client.post(reverse("collaboration_start_challenge", kwargs={"slug": self.challenge.slug}))
        self.assertEqual(TeamChallenge.objects.filter(team=team, challenge=self.challenge).count(), 1)
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.CHALLENGE_STARTED).count(), 1)

        draft_text = "Our team compared two schema choices."
        draft = self.client.post(
            reverse(
                "collaboration_submit_challenge",
                kwargs={"slug": self.challenge.slug, "participation_id": participation.pk},
            ),
            {"submission_text": draft_text, "action": "save"},
        )
        self.assertRedirects(draft, reverse("collaboration_challenge", kwargs={"slug": self.challenge.slug}))
        participation.refresh_from_db()
        self.assertEqual(participation.progress_percent, 50)
        self.assertEqual(participation.submission_text, draft_text)

        too_short = self.submit_challenge(participation, draft_text)
        self.assertEqual(too_short.status_code, 400)
        self.assertEqual(team.total_xp, 0)
        self.assertEqual(self.learner.total_xp, 0)

        response = self.submit_challenge(participation)
        self.assertRedirects(response, reverse("collaboration_challenge", kwargs={"slug": self.challenge.slug}))
        participation.refresh_from_db()
        team.refresh_from_db()
        self.learner.refresh_from_db()
        self.second_learner.refresh_from_db()
        self.assertEqual(participation.status, TeamChallenge.Status.COMPLETED)
        self.assertEqual(participation.progress_percent, 100)
        self.assertEqual(participation.xp_awarded, self.challenge.xp_reward)
        self.assertEqual(team.total_xp, self.challenge.xp_reward)
        self.assertEqual(self.learner.total_xp, self.challenge.xp_reward)
        self.assertEqual(self.second_learner.total_xp, self.challenge.xp_reward)
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.CHALLENGE_COMPLETED).count(), 1)

        self.submit_challenge(participation)
        team.refresh_from_db()
        self.learner.refresh_from_db()
        self.second_learner.refresh_from_db()
        self.assertEqual(team.total_xp, self.challenge.xp_reward)
        self.assertEqual(self.learner.total_xp, self.challenge.xp_reward)
        self.assertEqual(self.second_learner.total_xp, self.challenge.xp_reward)
        self.assertEqual(team.activity.filter(event_type=TeamActivity.Event.CHALLENGE_COMPLETED).count(), 1)

    def test_challenge_deadline_blocks_start_and_submission(self):
        _, team = self.create_team()
        closed = Challenge.objects.create(
            title="Closed challenge",
            slug="closed-challenge",
            description="This challenge is no longer open.",
            category=Challenge.Category.DATABASE,
            difficulty=Challenge.Difficulty.BEGINNER,
            starts_at=timezone.now() - timedelta(days=3),
            deadline=timezone.now() - timedelta(days=1),
            status=Challenge.Status.PUBLISHED,
            instructions="Review the challenge.",
            completion_criteria="Submit a meaningful response.",
        )
        response = self.client.post(
            reverse("collaboration_start_challenge", kwargs={"slug": closed.slug})
        )
        self.assertRedirects(response, reverse("collaboration_challenge", kwargs={"slug": closed.slug}))
        self.assertFalse(TeamChallenge.objects.filter(team=team, challenge=closed).exists())

    def test_leaderboard_uses_earned_team_xp_and_has_insufficient_team_state(self):
        _, first_team = self.create_team(name="Byte Brigade")
        one_team_page = self.client.get(reverse("collaboration_hub"))
        self.assertEqual(one_team_page.context["leaderboard"], [])

        self.join_team(self.second_learner, first_team)
        self.client.force_login(self.learner)
        _, participation = self.start_challenge(first_team)
        self.submit_challenge(participation)
        _, second_team = self.create_team(self.third_learner, name="Data Sprinters")

        self.client.force_login(self.learner)
        page = self.client.get(reverse("collaboration_hub"))
        leaderboard = page.context["leaderboard"]
        self.assertGreaterEqual(len(leaderboard), 2)
        self.assertEqual(leaderboard[0].pk, first_team.pk)
        self.assertEqual(leaderboard[0].total_xp, self.challenge.xp_reward)
        self.assertEqual(leaderboard[1].pk, second_team.pk)

    def test_activity_history_records_team_join_challenge_and_reward(self):
        _, team = self.create_team()
        self.join_team(self.second_learner, team)
        self.client.force_login(self.learner)
        _, participation = self.start_challenge(team)
        self.submit_challenge(participation)
        detail = self.client.get(reverse("collaboration_team", kwargs={"team_id": team.pk}))
        self.assertContains(detail, "created the team")
        self.assertContains(detail, "collabpartner joined the team")
        self.assertContains(detail, "completed API Design Code Sprint")
        self.assertContains(detail, "earned 80 team XP")
