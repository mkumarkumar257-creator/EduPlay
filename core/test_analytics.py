from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Game,
    GameAttempt,
    GameAttemptAnswer,
    LearnerContentProgress,
    LearningLesson,
    LearningTopic,
    Question,
    PracticeActivity,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
    User,
)


class AnalyticsAccessTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="analytics-learner",
            email="learner.analytics@example.com",
            password="A-secure-test-pass-908!",
            first_name="Ari",
            last_name="Learner",
        )
        self.educator = User.objects.create_user(
            username="analytics-educator",
            email="educator.analytics@example.com",
            password="A-secure-test-pass-908!",
            role=User.Role.EDUCATOR,
        )

    def test_analytics_pages_require_the_matching_role(self):
        self.assertEqual(self.client.get(reverse("learner_analytics")).status_code, 302)
        self.assertEqual(self.client.get(reverse("educator_analytics")).status_code, 302)

        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("learner_analytics")).status_code, 200)
        self.assertEqual(self.client.get(reverse("educator_analytics")).status_code, 403)

        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("educator_analytics")).status_code, 200)
        self.assertEqual(self.client.get(reverse("learner_analytics")).status_code, 403)

    def test_role_navigation_links_to_the_correct_analytics_page(self):
        self.client.force_login(self.learner)
        learner_page = self.client.get(reverse("learner_analytics"))
        self.assertContains(learner_page, reverse("learner_analytics"))
        self.assertNotContains(learner_page, reverse("educator_analytics"))

        self.client.force_login(self.educator)
        educator_page = self.client.get(reverse("educator_analytics"))
        self.assertContains(educator_page, reverse("educator_analytics"))
        self.assertNotContains(educator_page, reverse("learner_analytics"))


class AnalyticsDataTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="learner-one",
            email="learner.one@example.com",
            password="A-secure-test-pass-908!",
            first_name="Ari",
            last_name="Learner",
            total_xp=75,
        )
        self.other_learner = User.objects.create_user(
            username="learner-two",
            email="learner.two@example.com",
            password="A-secure-test-pass-908!",
            total_xp=10,
        )
        self.educator = User.objects.create_user(
            username="educator-one",
            email="educator.one@example.com",
            password="A-secure-test-pass-908!",
            role=User.Role.EDUCATOR,
        )
        self.topic = LearningTopic.objects.create(
            name="Analytics Test Topic", slug="analytics-test-topic"
        )
        self.game = Game.objects.create(
            title="Analytics Test Quiz",
            slug="analytics-test-quiz",
            description="Quiz fixture for analytics tests.",
            category=Game.Category.QUIZ,
            is_active=True,
            is_implemented=True,
        )
        self.questions = []
        for order in (1, 2):
            question = Question.objects.create(
                game=self.game,
                prompt=f"Analytics question {order}?",
                option_a="Correct",
                option_b="Incorrect",
                option_c="Another option",
                option_d="Another option",
                correct_option=Question.Option.A,
                order=order,
            )
            question.topics.add(self.topic)
            self.questions.append(question)

    def record_quiz(self, user, days_ago, correct_count=1, xp_awarded=10):
        ended_at = timezone.now() - timedelta(days=days_ago)
        attempt = GameAttempt.objects.create(
            user=user,
            game=self.game,
            status=GameAttempt.Status.COMPLETED,
            question_order=[question.pk for question in self.questions],
            total_questions=len(self.questions),
            correct_answers=correct_count,
            xp_awarded=xp_awarded,
            started_at=ended_at - timedelta(minutes=2),
            ended_at=ended_at,
        )
        for index, question in enumerate(self.questions):
            correct = index < correct_count
            GameAttemptAnswer.objects.create(
                attempt=attempt,
                question=question,
                selected_option=Question.Option.A if correct else Question.Option.B,
                is_correct=correct,
                answered_at=ended_at - timedelta(seconds=20 - index),
            )
        return attempt

    def test_learner_analytics_uses_only_own_records_and_applies_period_filter(self):
        self.record_quiz(self.learner, days_ago=1, correct_count=1, xp_awarded=10)
        self.record_quiz(self.learner, days_ago=45, correct_count=2, xp_awarded=20)
        self.record_quiz(self.other_learner, days_ago=1, correct_count=2, xp_awarded=99)

        self.client.force_login(self.learner)
        response = self.client.get(reverse("learner_analytics"), {"period": "7d"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_xp"], 75)
        self.assertEqual(response.context["level"], 1)
        self.assertEqual(response.context["xp_in_period"], 10)
        self.assertEqual(response.context["games_completed"], 1)
        self.assertEqual(response.context["quiz_accuracy"], 50.0)
        self.assertEqual(response.context["charts"]["quiz"]["values"], [50.0])
        self.assertEqual(sum(response.context["charts"]["activity"]["values"]), 1)
        self.assertEqual(response.context["recent_activity"][0]["title"], self.game.title)
        self.assertNotContains(response, "learner-two")

    def test_activity_and_topic_filters_update_learner_metrics(self):
        self.record_quiz(self.learner, days_ago=1)
        simulation, _ = Simulation.objects.update_or_create(
            slug="computer-system-performance-lab",
            defaults={
                "title": "Computer System Performance Lab",
                "description": "Simulation fixture.",
                "topic": self.topic,
                "is_active": True,
                "is_implemented": True,
            },
        )
        run = SimulationAttempt.objects.create(
            user=self.learner,
            simulation=simulation,
            parameters={"cpu_workload": 50},
            results={"performance_score": 80},
            xp_awarded=30,
        )
        SimulationCompletion.objects.create(
            user=self.learner,
            simulation=simulation,
            first_attempt=run,
            xp_awarded=30,
        )

        self.client.force_login(self.learner)
        response = self.client.get(
            reverse("learner_analytics"),
            {"period": "30d", "activity_type": "simulation", "topic": self.topic.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["games_completed"], 0)
        self.assertEqual(response.context["simulations_completed"], 1)
        self.assertIsNone(response.context["quiz_accuracy"])
        self.assertEqual(response.context["xp_in_period"], 30)
        self.assertEqual(response.context["charts"]["distribution"]["values"][2], 1)

    def test_educator_metrics_exclude_educators_and_report_real_learner_activity(self):
        self.record_quiz(self.learner, days_ago=2, correct_count=2, xp_awarded=12)
        self.record_quiz(self.educator, days_ago=1, correct_count=2, xp_awarded=99)

        self.client.force_login(self.educator)
        response = self.client.get(reverse("educator_analytics"), {"period": "30d"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_learners"], 2)
        self.assertEqual(response.context["active_learners"], 1)
        self.assertEqual(response.context["total_activities"], 1)
        self.assertEqual(response.context["average_performance"], 100.0)
        self.assertEqual(response.context["period_xp"], 12)
        self.assertEqual(len(response.context["learners"]), 2)
        self.assertNotIn(self.educator.pk, [row["learner"].pk for row in response.context["learners"]])
        self.assertFalse(response.context["show_course_filter"])
        self.assertContains(response, "Course and enrollment records are not implemented")

    def test_no_activity_has_explicit_empty_states(self):
        self.client.force_login(self.learner)
        response = self.client.get(reverse("learner_analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No XP awards in this range")
        self.assertContains(response, "More learning evidence is needed")
        self.assertEqual(response.context["overall_progress"], 0)

    def test_lesson_and_practice_progress_flows_into_learner_and_educator_analytics(self):
        lesson = LearningLesson.objects.create(
            title="Analytics Lesson",
            slug="analytics-lesson",
            description="Published analytics lesson.",
            body="Read and apply the concept.",
            subject="Computer Science",
            topic=self.topic,
            created_by=self.educator,
            status=LearningLesson.Status.PUBLISHED,
            visibility=LearningLesson.Visibility.PUBLIC,
        )
        practice = PracticeActivity.objects.create(
            title="Analytics Practice",
            slug="analytics-practice",
            description="Published analytics practice.",
            instructions="Complete the short practice.",
            subject="Computer Science",
            topic=self.topic,
            created_by=self.educator,
            status=PracticeActivity.Status.PUBLISHED,
            visibility=PracticeActivity.Visibility.PUBLIC,
        )
        now = timezone.now()
        LearnerContentProgress.objects.create(
            learner=self.learner,
            content_type=ContentType.objects.get_for_model(lesson),
            object_id=lesson.pk,
            status=LearnerContentProgress.Status.COMPLETED,
            started_at=now - timedelta(minutes=10),
            completed_at=now - timedelta(minutes=2),
        )
        LearnerContentProgress.objects.create(
            learner=self.learner,
            content_type=ContentType.objects.get_for_model(practice),
            object_id=practice.pk,
            status=LearnerContentProgress.Status.COMPLETED,
            started_at=now - timedelta(minutes=5),
            completed_at=now,
        )
        LearnerContentProgress.objects.create(
            learner=self.other_learner,
            content_type=ContentType.objects.get_for_model(practice),
            object_id=practice.pk,
            status=LearnerContentProgress.Status.IN_PROGRESS,
            started_at=now,
        )

        self.client.force_login(self.learner)
        lesson_response = self.client.get(
            reverse("learner_analytics"),
            {"period": "all", "activity_type": "lesson", "topic": self.topic.pk},
        )
        self.assertEqual(lesson_response.status_code, 200)
        self.assertEqual(lesson_response.context["lessons_completed"], 1)
        self.assertEqual(lesson_response.context["practice_activities_completed"], 0)
        self.assertEqual(lesson_response.context["completed_targets"], 1)
        self.assertEqual(lesson_response.context["catalog_size"], 1)
        self.assertEqual(lesson_response.context["recent_activity"][0]["title"], lesson.title)

        practice_response = self.client.get(
            reverse("learner_analytics"),
            {"period": "all", "activity_type": "practice", "topic": self.topic.pk},
        )
        self.assertEqual(practice_response.context["practice_activities_completed"], 1)
        self.assertEqual(practice_response.context["lessons_completed"], 0)
        self.assertEqual(practice_response.context["catalog_size"], 1)
        self.assertEqual(practice_response.context["charts"]["distribution"]["values"][5], 1)

        self.client.force_login(self.educator)
        educator_response = self.client.get(
            reverse("educator_analytics"),
            {"period": "all", "activity_type": "all", "topic": self.topic.pk},
        )
        self.assertEqual(educator_response.status_code, 200)
        self.assertEqual(educator_response.context["total_activities"], 3)
        self.assertEqual(educator_response.context["active_learners"], 2)
        learner_row = next(
            row for row in educator_response.context["learners"] if row["learner"].pk == self.learner.pk
        )
        self.assertEqual(learner_row["completed_count"], 2)
        self.assertEqual(learner_row["learning_progress"], 100)
        distribution = dict(zip(
            educator_response.context["activity_distribution"]["labels"],
            educator_response.context["activity_distribution"]["values"],
        ))
        self.assertEqual(distribution["Lessons"], 1)
        self.assertEqual(distribution["Practice activities"], 1)
