from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Challenge,
    ContentView,
    Game,
    GameAttempt,
    GameAttemptAnswer,
    LearnerContentProgress,
    LearningLesson,
    LearningTopic,
    PracticeActivity,
    Question,
    TeamChallenge,
    User,
)


PASSWORD = "A-secure-content-pass-839!"


class ContentStudioTests(TestCase):
    def setUp(self):
        self.educator = User.objects.create_user(
            username="author-one",
            email="author-one@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
            first_name="Ari",
        )
        self.other_educator = User.objects.create_user(
            username="author-two",
            email="author-two@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
        )
        self.learner = User.objects.create_user(
            username="content-learner",
            email="content-learner@example.com",
            password=PASSWORD,
            first_name="Lee",
        )
        self.topic = LearningTopic.objects.create(name="Database Systems", slug="content-db-topic")

    def quiz_payload(self, *, title="Authored Quiz", visibility="public", question_count=1):
        data = {
            "title": title,
            "description": "A short quiz created in Content Studio.",
            "subject": "Database Systems",
            "topic": str(self.topic.pk),
            "difficulty": Game.Difficulty.INTERMEDIATE,
            "time_limit_seconds": "180",
            "xp_reward": "40",
            "visibility": visibility,
            "questions-TOTAL_FORMS": str(question_count),
            "questions-INITIAL_FORMS": "0",
            "questions-MIN_NUM_FORMS": "0",
            "questions-MAX_NUM_FORMS": "50",
        }
        for index in range(question_count):
            prefix = f"questions-{index}-"
            data.update({
                prefix + "order": str(question_count - index),
                prefix + "prompt": f"Which option is correct for item {index + 1}?",
                prefix + "option_a": f"Correct answer {index + 1}",
                prefix + "option_b": f"Distractor B {index + 1}",
                prefix + "option_c": f"Distractor C {index + 1}",
                prefix + "option_d": f"Distractor D {index + 1}",
                prefix + "correct_option": Question.Option.A,
                prefix + "explanation": "The first option is correct for this test question.",
                prefix + "difficulty": Question._meta.get_field("difficulty").default,
            })
        return data

    def create_quiz(self, *, title="Authored Quiz", visibility="public", question_count=1):
        self.client.force_login(self.educator)
        response = self.client.post(
            reverse("educator_content_new", kwargs={"content_type": "quiz"}),
            self.quiz_payload(title=title, visibility=visibility, question_count=question_count),
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        return Game.objects.get(title=title)

    def publish(self, content_type, content):
        return self.client.post(
            reverse(
                "educator_content_action",
                kwargs={"content_type": content_type, "pk": content.pk, "action": "publish"},
            )
        )

    def test_role_guards_and_owner_scoped_library(self):
        quiz = self.create_quiz(title="Only my draft")
        self.client.force_login(self.other_educator)
        self.assertEqual(
            self.client.get(reverse("educator_content_edit", kwargs={"content_type": "quiz", "pk": quiz.pk})).status_code,
            404,
        )
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("educator_content_library")).status_code, 403)
        self.assertEqual(self.client.get(reverse("educator_content_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("learner_content_library")).status_code, 200)
        self.assertNotContains(self.client.get(reverse("learner_content_library")), "Only my draft")

    def test_quiz_requires_questions_to_publish_and_is_unavailable_while_draft(self):
        self.client.force_login(self.educator)
        response = self.client.post(
            reverse("educator_content_new", kwargs={"content_type": "quiz"}),
            {
                "title": "Empty quiz",
                "description": "A draft quiz without questions.",
                "subject": "Databases",
                "topic": "",
                "difficulty": Game.Difficulty.BEGINNER,
                "time_limit_seconds": "180",
                "xp_reward": "20",
                "visibility": "public",
                "questions-TOTAL_FORMS": "1",
                "questions-INITIAL_FORMS": "0",
                "questions-MIN_NUM_FORMS": "0",
                "questions-MAX_NUM_FORMS": "50",
                "questions-0-order": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        empty_quiz = Game.objects.get(title="Empty quiz")
        self.assertEqual(self.publish("quiz", empty_quiz).status_code, 302)
        empty_quiz.refresh_from_db()
        self.assertEqual(empty_quiz.status, Game.Status.DRAFT)
        self.client.force_login(self.learner)
        self.assertEqual(
            self.client.get(reverse("content_quiz_instructions", kwargs={"slug": empty_quiz.slug})).status_code,
            404,
        )

    def test_quiz_creation_publishing_attempt_xp_and_real_content_statistics(self):
        quiz = self.create_quiz(title="Storage Concepts", question_count=2)
        self.assertEqual(quiz.status, Game.Status.DRAFT)
        questions = list(quiz.questions.order_by("order"))
        self.assertEqual([question.order for question in questions], [1, 2])
        self.assertEqual(questions[0].prompt, "Which option is correct for item 2?")
        self.assertTrue(questions[0].topics.filter(pk=self.topic.pk).exists())

        self.publish("quiz", quiz)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Game.Status.PUBLISHED)
        self.assertTrue(quiz.is_active)
        self.assertTrue(quiz.is_implemented)

        self.client.force_login(self.learner)
        library = self.client.get(reverse("learner_content_library"))
        self.assertContains(library, "Storage Concepts")
        instructions = self.client.get(reverse("content_quiz_instructions", kwargs={"slug": quiz.slug}))
        self.assertEqual(instructions.status_code, 200)
        self.assertNotContains(instructions, "Correct answer 1")
        attempt_response = self.client.post(reverse("content_quiz_start", kwargs={"slug": quiz.slug}))
        attempt = GameAttempt.objects.get(user=self.learner, game=quiz)
        self.assertEqual(attempt_response.status_code, 302)
        self.assertEqual(self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk})).status_code, 200)
        self.assertNotContains(self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk})), "The first option is correct")

        for question_id in attempt.question_order:
            question = Question.objects.get(pk=question_id)
            self.client.post(
                reverse("submit_quiz_answer", kwargs={"attempt_id": attempt.pk}),
                {"question_id": question.pk, "option": Question.Option.A},
            )
        self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, GameAttempt.Status.COMPLETED)
        self.assertEqual(attempt.xp_awarded, quiz.xp_reward)
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.total_xp, quiz.xp_reward)

        self.client.force_login(self.educator)
        library = self.client.get(reverse("educator_content_library"))
        self.assertContains(library, "Storage Concepts")
        self.assertContains(library, "100.0%")
        self.assertContains(library, "1</strong><span>Views")
        self.assertContains(library, "1</strong><span>Completions")

    def test_private_and_unpublished_quizzes_never_open_to_learners(self):
        quiz = self.create_quiz(title="Private Quiz", visibility="private")
        self.publish("quiz", quiz)
        self.client.force_login(self.learner)
        self.assertNotContains(self.client.get(reverse("learner_content_library")), "Private Quiz")
        self.assertEqual(
            self.client.get(reverse("content_quiz_instructions", kwargs={"slug": quiz.slug})).status_code,
            404,
        )
        self.client.force_login(self.educator)
        self.client.post(
            reverse("educator_content_action", kwargs={"content_type": "quiz", "pk": quiz.pk, "action": "unpublish"})
        )
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Game.Status.UNPUBLISHED)

    def test_quiz_preview_edit_order_republish_and_delete(self):
        quiz = self.create_quiz(title="Editable Quiz", question_count=2)
        preview_url = reverse(
            "educator_content_preview", kwargs={"content_type": "quiz", "pk": quiz.pk}
        )
        preview = self.client.get(preview_url)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Correct answer 1")

        self.publish("quiz", quiz)
        questions = list(quiz.questions.order_by("order"))
        data = {
            "title": quiz.title,
            "description": quiz.description,
            "subject": quiz.subject,
            "topic": str(self.topic.pk),
            "difficulty": quiz.difficulty,
            "time_limit_seconds": str(quiz.time_limit_seconds),
            "xp_reward": str(quiz.xp_reward),
            "visibility": quiz.visibility,
            "questions-TOTAL_FORMS": "2",
            "questions-INITIAL_FORMS": "2",
            "questions-MIN_NUM_FORMS": "0",
            "questions-MAX_NUM_FORMS": "50",
        }
        for index, question in enumerate(questions):
            prefix = f"questions-{index}-"
            data.update({
                prefix + "id": str(question.pk),
                prefix + "order": str(2 - index),
                prefix + "prompt": question.prompt,
                prefix + "option_a": question.option_a,
                prefix + "option_b": question.option_b,
                prefix + "option_c": question.option_c,
                prefix + "option_d": question.option_d,
                prefix + "correct_option": question.correct_option,
                prefix + "explanation": question.explanation,
                prefix + "difficulty": question.difficulty,
                prefix + "topics": str(self.topic.pk),
            })
        edit_url = reverse("educator_content_edit", kwargs={"content_type": "quiz", "pk": quiz.pk})
        response = self.client.post(edit_url, data)
        self.assertRedirects(response, edit_url)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Game.Status.DRAFT)
        self.assertFalse(quiz.is_active)
        reordered = list(quiz.questions.order_by("order"))
        self.assertEqual(reordered[0].prompt, questions[1].prompt)
        self.assertEqual(reordered[0].topics.filter(pk=self.topic.pk).count(), 1)

        self.publish("quiz", quiz)
        delete_url = reverse(
            "educator_content_action", kwargs={"content_type": "quiz", "pk": quiz.pk, "action": "delete"}
        )
        self.assertRedirects(self.client.post(delete_url), reverse("educator_content_library"))
        self.assertFalse(Game.objects.filter(pk=quiz.pk).exists())

    def test_published_lesson_tracks_views_and_idempotent_completion(self):
        self.client.force_login(self.educator)
        response = self.client.post(
            reverse("educator_content_new", kwargs={"content_type": "lesson"}),
            {
                "title": "Relational Keys",
                "description": "A lesson on primary and foreign keys.",
                "subject": "Databases",
                "topic": str(self.topic.pk),
                "difficulty": "beginner",
                "estimated_duration_minutes": "12",
                "visibility": "public",
                "body": "A primary key identifies a row.\nA foreign key references another table.",
                "learning_objectives": "Identify primary keys\nExplain foreign keys",
            },
        )
        self.assertEqual(response.status_code, 302)
        lesson = LearningLesson.objects.get(title="Relational Keys")
        self.assertEqual(lesson.status, LearningLesson.Status.DRAFT)
        self.publish("lesson", lesson)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LearningLesson.Status.PUBLISHED)

        self.client.force_login(self.learner)
        page_url = reverse("learner_content_detail", kwargs={"content_type": "lesson", "slug": lesson.slug})
        self.assertEqual(self.client.get(page_url).status_code, 200)
        self.assertContains(self.client.get(page_url), "Explain foreign keys")
        progress = LearnerContentProgress.objects.get(learner=self.learner, object_id=lesson.pk)
        self.assertEqual(progress.status, LearnerContentProgress.Status.IN_PROGRESS)
        complete_url = reverse("learner_content_complete", kwargs={"content_type": "lesson", "pk": lesson.pk})
        self.assertEqual(self.client.post(complete_url).status_code, 302)
        progress.refresh_from_db()
        completed_at = progress.completed_at
        self.assertEqual(progress.status, LearnerContentProgress.Status.COMPLETED)
        self.client.post(complete_url)
        progress.refresh_from_db()
        self.assertEqual(progress.completed_at, completed_at)
        self.assertEqual(ContentView.objects.filter(object_id=lesson.pk).count(), 2)
        progress_page = self.client.get(reverse("learner_content_progress"))
        self.assertEqual(progress_page.status_code, 200)
        self.assertContains(progress_page, 'aria-current="page"')
        dashboard = self.client.get(reverse("learner_dashboard"))
        self.assertEqual(dashboard.context["dashboard_analytics"]["lessons_completed"], 1)

    def test_practice_activity_and_challenge_can_be_saved_published_and_browsed(self):
        self.client.force_login(self.educator)
        response = self.client.post(
            reverse("educator_content_new", kwargs={"content_type": "practice"}),
            {
                "title": "Normalize a Table",
                "description": "Practice identifying repeating values.",
                "subject": "Databases",
                "topic": str(self.topic.pk),
                "difficulty": "intermediate",
                "estimated_duration_minutes": "15",
                "visibility": "public",
                "instructions": "Inspect the sample rows and identify repeating groups.",
                "learning_objectives": "Practice first normal form.",
                "completion_criteria": "Record the fields that should become a separate table.",
            },
        )
        self.assertEqual(response.status_code, 302)
        practice = PracticeActivity.objects.get(title="Normalize a Table")

        starts_at = timezone.localtime(timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        deadline = timezone.localtime(timezone.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("educator_content_new", kwargs={"content_type": "challenge"}),
            {
                "title": "Team Schema Review",
                "description": "Review a schema as a team.",
                "category": Challenge.Category.DATABASE,
                "subject": "Databases",
                "topic": str(self.topic.pk),
                "difficulty": Challenge.Difficulty.BEGINNER,
                "xp_reward": "30",
                "starts_at": starts_at,
                "deadline": deadline,
                "visibility": "public",
                "instructions": "Discuss the proposed schema and submit your team's review.",
                "completion_criteria": "Submit at least one justified normalization improvement.",
                "minimum_submission_characters": "50",
            },
        )
        self.assertEqual(response.status_code, 302)
        challenge = Challenge.objects.get(title="Team Schema Review")
        self.assertEqual(challenge.created_by, self.educator)
        self.assertEqual(challenge.status, Challenge.Status.DRAFT)
        self.publish("practice", practice)
        self.publish("challenge", challenge)
        self.client.force_login(self.learner)
        library = self.client.get(reverse("learner_content_library"))
        self.assertContains(library, "Normalize a Table")
        self.assertContains(library, "Team Schema Review")
        self.assertEqual(
            self.client.get(reverse("collaboration_challenge", kwargs={"slug": challenge.slug})).status_code,
            200,
        )

    def test_delete_is_post_only_and_protected_content_is_archived_instead(self):
        quiz = self.create_quiz(title="History Protected Quiz")
        self.publish("quiz", quiz)
        question = quiz.questions.get()
        attempt = GameAttempt.objects.create(
            user=self.learner,
            game=quiz,
            status=GameAttempt.Status.COMPLETED,
            question_order=[question.pk],
            total_questions=1,
            correct_answers=1,
            ended_at=timezone.now(),
        )
        GameAttemptAnswer.objects.create(
            attempt=attempt,
            question=question,
            selected_option=Question.Option.A,
            is_correct=True,
        )
        self.client.force_login(self.educator)
        action_url = reverse(
            "educator_content_action", kwargs={"content_type": "quiz", "pk": quiz.pk, "action": "delete"}
        )
        self.assertEqual(self.client.get(action_url).status_code, 405)
        self.assertEqual(self.client.post(action_url).status_code, 302)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Game.Status.PUBLISHED)
        self.client.post(
            reverse("educator_content_action", kwargs={"content_type": "quiz", "pk": quiz.pk, "action": "archive"})
        )
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, Game.Status.ARCHIVED)
