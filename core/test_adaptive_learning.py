from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .adaptive_learning import build_adaptive_snapshot, recommendation_band_for_accuracy
from .models import (
    Game,
    GameAttempt,
    GameAttemptAnswer,
    LearningPath,
    LearningPathItem,
    Question,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
    User,
)


PASSWORD = "A-secure-demo-pass-831!"


class AdaptiveLearningTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="adaptivelearner", email="adaptivelearner@example.com", password=PASSWORD
        )
        self.other_learner = User.objects.create_user(
            username="anotherlearner", email="anotherlearner@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="adaptiveeducator",
            email="adaptiveeducator@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
        )
        self.quiz = Game.objects.get(slug="quiz-challenge")
        self.questions = list(self.quiz.questions.order_by("order"))
        self.path = LearningPath.objects.get(slug="mca-core-foundations")
        self.client.force_login(self.learner)

    def add_attempt(self, user, questions=None, correct_question_ids=None, status=GameAttempt.Status.COMPLETED):
        questions = list(questions if questions is not None else self.questions)
        correct_question_ids = set(correct_question_ids or ())
        now = timezone.now()
        attempt = GameAttempt.objects.create(
            user=user,
            game=self.quiz,
            status=status,
            question_order=[question.pk for question in questions],
            total_questions=len(questions),
            correct_answers=sum(question.pk in correct_question_ids for question in questions),
            started_at=now,
            ended_at=now if status == GameAttempt.Status.COMPLETED else None,
        )
        answers = []
        for question in questions:
            selected = question.correct_option
            if question.pk not in correct_question_ids:
                selected = next(option for option in Question.Option.values if option != question.correct_option)
            answers.append(
                GameAttemptAnswer(
                    attempt=attempt,
                    question=question,
                    selected_option=selected,
                    is_correct=question.pk in correct_question_ids,
                    answered_at=now,
                )
            )
        GameAttemptAnswer.objects.bulk_create(answers)
        return attempt

    def topic_row(self, snapshot, slug):
        return next(row for row in snapshot["topics"] if row["topic"].slug == slug)

    def test_adaptive_page_has_an_honest_onboarding_state_and_role_protection(self):
        response = self.client.get(reverse("adaptive_learning"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your personalized profile is getting started")
        self.assertContains(response, "Start the baseline quiz")
        self.assertContains(response, "Not Started")
        self.assertContains(response, "MCA Core Foundations")
        self.assertContains(response, "Not Started")
        self.assertIsNone(response.context["adaptive"]["accuracy"])
        self.assertIsNone(response.context["adaptive"]["recommendation"])
        self.assertEqual(response.context["adaptive"]["path_state"]["progress_percent"], 0)

        self.client.logout()
        self.assertEqual(self.client.get(reverse("adaptive_learning")).status_code, 302)
        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("adaptive_learning")).status_code, 403)

    def test_recommendation_accuracy_bands_cover_configured_boundaries(self):
        expected = {
            0: "Beginner",
            39: "Beginner",
            40: "Guided",
            69: "Guided",
            70: "Intermediate",
            89: "Intermediate",
            90: "Advanced",
            100: "Advanced",
        }
        for accuracy, difficulty in expected.items():
            with self.subTest(accuracy=accuracy):
                self.assertEqual(recommendation_band_for_accuracy(accuracy)["difficulty"], difficulty)
        self.assertIsNone(recommendation_band_for_accuracy(None))

    def test_accuracy_rules_create_real_recommendations_or_explain_missing_advanced_content(self):
        cases = ((3, "Beginner", "Quiz Challenge", "ready"),
                 (6, "Guided", "Quiz Challenge", "ready"),
                 (8, "Intermediate", "Computer System Performance Lab", "ready"),
                 (9, None, None, "advanced_unavailable"))
        for index, (correct_count, difficulty, activity, state) in enumerate(cases, start=1):
            with self.subTest(correct_count=correct_count):
                user = User.objects.create_user(
                    username=f"bandlearner{index}",
                    email=f"bandlearner{index}@example.com",
                    password=PASSWORD,
                )
                self.add_attempt(user, correct_question_ids={question.pk for question in self.questions[:correct_count]})
                snapshot = build_adaptive_snapshot(user)
                self.assertEqual(snapshot["recommendation_state"], state)
                if activity:
                    self.assertEqual(snapshot["recommendation"]["recommended_difficulty"], difficulty)
                    self.assertTrue(snapshot["recommendation"]["activity_name"].startswith(activity))
                    self.assertTrue(snapshot["recommendation"]["action_url"].startswith("/"))
                    self.assertTrue(snapshot["recommendation"]["reason"])
                    self.assertTrue(snapshot["recommendation"]["expected_outcome"])
                else:
                    self.assertIsNone(snapshot["recommendation"])

    def test_topic_mastery_requires_multiple_distinct_questions_and_finds_inferred_strength(self):
        db_questions = [question for question in self.questions if "databases" in {topic.slug for topic in question.topics.all()}]
        self.assertEqual(len(db_questions), 2)
        for _ in range(2):
            self.add_attempt(self.learner, db_questions, correct_question_ids={question.pk for question in db_questions})

        snapshot = build_adaptive_snapshot(self.learner)
        database_topic = self.topic_row(snapshot, "databases")
        self.assertEqual(database_topic["answer_count"], 4)
        self.assertEqual(database_topic["question_count"], 2)
        self.assertEqual(database_topic["observed_accuracy"], 100)
        self.assertEqual(database_topic["mastery_score"], 100)
        self.assertEqual(database_topic["mastery_level"], "Mastered")
        self.assertTrue(database_topic["is_strength"])

    def test_repeated_mistakes_can_infer_a_weak_topic_but_one_question_cannot(self):
        db_questions = [question for question in self.questions if "databases" in {topic.slug for topic in question.topics.all()}]
        for _ in range(2):
            self.add_attempt(self.learner, db_questions)
        weak_snapshot = build_adaptive_snapshot(self.learner)
        database_topic = self.topic_row(weak_snapshot, "databases")
        self.assertTrue(database_topic["is_weakness"])
        self.assertEqual(database_topic["repeated_mistakes"], 2)

        one_question_learner = User.objects.create_user(
            username="onequestion", email="onequestion@example.com", password=PASSWORD
        )
        algorithm_question = [question for question in self.questions if "algorithms" in {topic.slug for topic in question.topics.all()}]
        self.assertEqual(len(algorithm_question), 1)
        for _ in range(4):
            self.add_attempt(one_question_learner, algorithm_question)
        one_question_row = self.topic_row(build_adaptive_snapshot(one_question_learner), "algorithms")
        self.assertEqual(one_question_row["answer_count"], 4)
        self.assertEqual(one_question_row["question_count"], 1)
        self.assertEqual(one_question_row["mastery_level"], "Insufficient data")
        self.assertFalse(one_question_row["is_weakness"])

    def test_simulation_output_is_reported_as_system_data_not_learner_mastery(self):
        simulation = Simulation.objects.get(slug="computer-system-performance-lab")
        for score in (42, 62):
            SimulationAttempt.objects.create(
                user=self.learner,
                simulation=simulation,
                parameters={"cpu_workload": 50},
                results={"performance_score": score},
            )
        system_topic = self.topic_row(build_adaptive_snapshot(self.learner), "computer-systems")
        self.assertEqual(system_topic["simulation_run_count"], 2)
        self.assertEqual(system_topic["average_simulation_score"], 52)
        self.assertEqual(system_topic["mastery_level"], "Not Started")
        self.assertIsNone(system_topic["mastery_score"])

    def test_path_progress_uses_existing_completion_records_and_is_user_scoped(self):
        self.add_attempt(self.learner, correct_question_ids={question.pk for question in self.questions})
        first_snapshot = build_adaptive_snapshot(self.learner)
        self.assertEqual(first_snapshot["path_state"]["progress_percent"], 50)
        states = [entry["state"] for entry in first_snapshot["path_state"]["items"]]
        self.assertEqual(states, ["completed", "current"])

        simulation = Simulation.objects.get(slug="computer-system-performance-lab")
        SimulationCompletion.objects.create(user=self.learner, simulation=simulation)
        complete_snapshot = build_adaptive_snapshot(self.learner)
        self.assertEqual(complete_snapshot["path_state"]["progress_percent"], 100)
        self.assertEqual([entry["state"] for entry in complete_snapshot["path_state"]["items"]], ["completed", "completed"])

        other_snapshot = build_adaptive_snapshot(self.other_learner)
        self.assertEqual(other_snapshot["path_state"]["progress_percent"], 0)
        self.assertEqual(other_snapshot["answer_count"], 0)

    def test_configured_prerequisites_lock_only_dependent_items(self):
        original_items = list(self.path.items.all())
        second_item = original_items[1]
        item = LearningPathItem.objects.create(
            path=self.path,
            sequence=3,
            title="Dependent follow-up",
            topic=second_item.topic,
            activity_type=LearningPathItem.ActivityType.QUIZ,
            game=self.quiz,
            difficulty=LearningPathItem.Difficulty.INTERMEDIATE,
            expected_outcome="Continue after the prerequisite activity.",
            prerequisite=second_item,
        )
        snapshot = build_adaptive_snapshot(self.learner)
        entry = next(state for state in snapshot["path_state"]["items"] if state["item"].pk == item.pk)
        self.assertTrue(entry["locked"])
        self.assertEqual(entry["state"], "locked")

    def test_dashboard_uses_actual_profile_state_and_legacy_route_redirects(self):
        response = self.client.get(reverse("learner_dashboard"))
        self.assertContains(response, "Adaptive learning")
        self.assertContains(response, "STARTING ACTIVITY")
        self.assertContains(response, "View learning path and topic mastery")
        legacy = self.client.get(reverse("workspace_placeholder", kwargs={"feature": "learning-paths"}))
        self.assertRedirects(legacy, reverse("adaptive_learning"))

        self.add_attempt(self.learner, correct_question_ids={question.pk for question in self.questions})
        response = self.client.get(reverse("adaptive_learning"))
        self.assertEqual(response.context["adaptive"]["accuracy"], 100)
        self.assertContains(response, "OBSERVED QUIZ ACCURACY")

    def test_recent_activity_and_accuracy_do_not_leak_between_learners(self):
        self.add_attempt(self.learner, correct_question_ids={question.pk for question in self.questions})
        self.client.force_login(self.other_learner)
        response = self.client.get(reverse("adaptive_learning"))
        adaptive = response.context["adaptive"]
        self.assertEqual(adaptive["answer_count"], 0)
        self.assertIsNone(adaptive["accuracy"])
        self.assertEqual(adaptive["recent_activity"], [])

