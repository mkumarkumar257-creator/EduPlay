from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Game, GameAttempt, GameAttemptAnswer, Question, User


PASSWORD = "A-secure-demo-pass-831!"


class QuizChallengeTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user(
            username="quizlearner", email="quizlearner@example.com", password=PASSWORD
        )
        self.educator = User.objects.create_user(
            username="quizeducator",
            email="quizeducator@example.com",
            password=PASSWORD,
            role=User.Role.EDUCATOR,
        )
        self.game = Game.objects.get(slug="quiz-challenge")
        self.questions = list(self.game.questions.filter(is_active=True).order_by("order"))
        self.client.force_login(self.learner)

    def start_attempt(self):
        response = self.client.post(reverse("start_quiz"))
        attempt = GameAttempt.objects.filter(user=self.learner, game=self.game).latest("started_at")
        self.assertRedirects(response, reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        return attempt

    def submit_answer(self, attempt, question, option):
        return self.client.post(
            reverse("submit_quiz_answer", kwargs={"attempt_id": attempt.pk}),
            {"question_id": str(question.pk), "option": option},
        )

    def complete_with_score(self, correct_count):
        attempt = self.start_attempt()
        for index, question in enumerate(self.questions):
            option = question.correct_option if index < correct_count else next(
                value for value in Question.Option.values if value != question.correct_option
            )
            response = self.submit_answer(attempt, question, option)
            self.assertEqual(response.status_code, 302)

        results = self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        self.assertEqual(results.status_code, 200)
        attempt.refresh_from_db()
        return attempt, results

    def test_game_zone_is_learner_only_and_shows_only_implemented_play_button(self):
        page = self.client.get(reverse("game_zone"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Quiz Challenge")
        self.assertContains(page, "Ready to play")
        self.assertContains(page, "Logic Sprint")
        self.assertContains(page, 'href="/game-zone/quiz-challenge/"')
        self.assertEqual(page.content.decode().count('class="btn game-disabled-button"'), 3)

        self.client.force_login(self.educator)
        self.assertEqual(self.client.get(reverse("game_zone")).status_code, 403)
        self.assertEqual(self.client.get(reverse("quiz_challenge")).status_code, 403)

    def test_instructions_start_attempt_and_question_shows_four_options(self):
        instructions = self.client.get(reverse("quiz_challenge"))
        self.assertEqual(instructions.status_code, 200)
        self.assertContains(instructions, "Before you begin")
        self.assertContains(instructions, "10")

        attempt = self.start_attempt()
        page = self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        self.assertContains(page, "Question")
        self.assertEqual(page.content.decode().count('class="quiz-option"'), 4)
        self.assertContains(page, 'data-quiz-timer')
        self.assertNotContains(page, self.questions[0].explanation)
        self.assertEqual(attempt.total_questions, 10)

    def test_correct_and_incorrect_answers_show_feedback_and_advance(self):
        attempt = self.start_attempt()
        first, second = self.questions[:2]

        response = self.submit_answer(attempt, first, first.correct_option)
        self.assertEqual(response.status_code, 302)
        self.assertIn("feedback=1", response["Location"])
        self.assertTrue(GameAttemptAnswer.objects.get(attempt=attempt, question=first).is_correct)
        feedback = self.client.get(response["Location"])
        self.assertContains(feedback, "That’s correct.")
        self.assertContains(feedback, first.explanation)

        next_question = self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        self.assertContains(next_question, second.prompt)
        wrong_option = next(value for value in Question.Option.values if value != second.correct_option)
        response = self.submit_answer(attempt, second, wrong_option)
        feedback = self.client.get(response["Location"])
        self.assertContains(feedback, "Not quite this time.")
        self.assertContains(feedback, second.get_option_text(second.correct_option))

    def test_repeat_submission_cannot_answer_a_second_question_or_duplicate_an_answer(self):
        attempt = self.start_attempt()
        question = self.questions[0]
        payload = {"question_id": str(question.pk), "option": question.correct_option}
        url = reverse("submit_quiz_answer", kwargs={"attempt_id": attempt.pk})
        self.client.post(url, payload)
        duplicate = self.client.post(url, payload)
        self.assertEqual(duplicate.status_code, 302)
        self.assertEqual(GameAttemptAnswer.objects.filter(attempt=attempt).count(), 1)
        self.assertFalse(GameAttemptAnswer.objects.filter(attempt=attempt, question=self.questions[1]).exists())

    def test_answers_must_be_current_and_use_one_of_the_four_choices(self):
        attempt = self.start_attempt()
        question = self.questions[0]
        invalid = self.submit_answer(attempt, question, "Z")
        self.assertEqual(invalid.status_code, 302)
        self.assertFalse(GameAttemptAnswer.objects.filter(attempt=attempt).exists())

        future_question = self.questions[1]
        response = self.submit_answer(attempt, future_question, future_question.correct_option)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GameAttemptAnswer.objects.filter(attempt=attempt).exists())

    def test_results_save_score_award_xp_and_allow_restart(self):
        attempt, results = self.complete_with_score(8)
        self.assertEqual(attempt.status, GameAttempt.Status.COMPLETED)
        self.assertEqual(attempt.correct_answers, 8)
        self.assertEqual(attempt.xp_awarded, 80)
        self.assertContains(results, "80")
        self.assertContains(results, "80 XP")
        self.learner.refresh_from_db()
        self.assertEqual(self.learner.total_xp, 80)

        restart = self.client.post(reverse("start_quiz"))
        self.assertEqual(restart.status_code, 302)
        self.assertContains(self.client.get(reverse("quiz_challenge")), "Start challenge")

    def test_learner_dashboard_shows_live_attempt_and_real_recent_activity(self):
        attempt = self.start_attempt()
        self.submit_answer(attempt, self.questions[0], self.questions[0].correct_option)

        dashboard = self.client.get(reverse("learner_dashboard"))
        self.assertContains(dashboard, "Resume Quiz Challenge")
        self.assertContains(dashboard, "1 of 10 questions answered")
        self.assertContains(dashboard, "Recent activity")
        self.assertContains(dashboard, "In progress")

    def test_final_answer_remains_completed_if_feedback_is_opened_after_deadline(self):
        attempt = self.start_attempt()
        for question in self.questions:
            self.submit_answer(attempt, question, question.correct_option)

        attempt.started_at = timezone.now() - timedelta(seconds=self.game.time_limit_seconds + 5)
        attempt.save(update_fields=("started_at",))
        feedback_url = f"{reverse('quiz_attempt', kwargs={'attempt_id': attempt.pk})}?feedback=1"
        feedback = self.client.get(feedback_url)

        self.assertContains(feedback, "That’s correct.")
        self.assertContains(feedback, "FINAL ANSWER SAVED")
        attempt.refresh_from_db()
        self.learner.refresh_from_db()
        self.assertEqual(attempt.status, GameAttempt.Status.COMPLETED)
        self.assertEqual(attempt.xp_awarded, self.game.xp_reward)
        self.assertEqual(self.learner.total_xp, self.game.xp_reward)

    def test_replays_only_award_the_difference_to_a_new_best_and_cannot_farm_xp(self):
        first_attempt, _ = self.complete_with_score(5)
        second_attempt, _ = self.complete_with_score(8)
        third_attempt, _ = self.complete_with_score(8)
        first_attempt.refresh_from_db()
        second_attempt.refresh_from_db()
        third_attempt.refresh_from_db()
        self.learner.refresh_from_db()
        self.assertEqual(first_attempt.xp_awarded, 50)
        self.assertEqual(second_attempt.xp_awarded, 30)
        self.assertEqual(third_attempt.xp_awarded, 0)
        self.assertEqual(self.learner.total_xp, 80)

    def test_expired_attempt_is_closed_server_side_without_xp(self):
        attempt = self.start_attempt()
        attempt.started_at = timezone.now() - timedelta(seconds=self.game.time_limit_seconds + 5)
        attempt.save(update_fields=("started_at",))
        response = self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk}))
        self.assertContains(response, "Challenge ended")
        attempt.refresh_from_db()
        self.learner.refresh_from_db()
        self.assertEqual(attempt.status, GameAttempt.Status.TIMED_OUT)
        self.assertEqual(attempt.xp_awarded, 0)
        self.assertEqual(self.learner.total_xp, 0)

    def test_attempt_urls_are_private_and_post_routes_reject_get(self):
        attempt = self.start_attempt()
        self.assertEqual(
            self.client.get(reverse("submit_quiz_answer", kwargs={"attempt_id": attempt.pk})).status_code,
            405,
        )
        other = User.objects.create_user(username="other", email="other@example.com", password=PASSWORD)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("quiz_attempt", kwargs={"attempt_id": attempt.pk})).status_code, 404)

        self.client.force_login(self.educator)
        self.assertEqual(self.client.post(reverse("start_quiz")).status_code, 403)
