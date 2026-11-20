"""Data-backed learner analysis, adaptive recommendations, and path progress."""

from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Q
from django.urls import reverse

from .models import (
    Game,
    GameAttempt,
    GameAttemptAnswer,
    LearningPath,
    LearningPathItem,
    LearningTopic,
    Question,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
)
from .simulation_engine import get_simulation_engine


def _learning_path_state(user):
    path = (
        LearningPath.objects.filter(is_active=True, is_default=True)
        .prefetch_related("items__topic", "items__game", "items__simulation", "items__prerequisite")
        .first()
    )
    if path is None:
        return {
            "path": None,
            "items": [],
            "progress_percent": 0,
            "completed_count": 0,
            "pending_count": 0,
            "current_item": None,
            "completed_topics": [],
            "upcoming_topics": [],
            "locked_topics": [],
        }

    completed_game_ids = set(
        GameAttempt.objects.filter(
            user=user, status=GameAttempt.Status.COMPLETED, game__is_active=True, game__is_implemented=True
        ).values_list("game_id", flat=True).distinct()
    )
    completed_simulation_ids = set(
        SimulationCompletion.objects.filter(user=user).values_list("simulation_id", flat=True)
    )
    items = list(path.items.all())
    completed_item_ids = set()
    for item in items:
        if item.game_id and item.game_id in completed_game_ids:
            completed_item_ids.add(item.pk)
        elif item.simulation_id and item.simulation_id in completed_simulation_ids:
            completed_item_ids.add(item.pk)

    current_item = None
    item_states = []
    completed_topics = []
    upcoming_topics = []
    locked_topics = []
    for item in items:
        complete = item.pk in completed_item_ids
        locked = bool(item.prerequisite_id and item.prerequisite_id not in completed_item_ids)
        if complete:
            state = "completed"
            completed_topics.append(item.topic)
        elif locked:
            state = "locked"
            locked_topics.append(item.topic)
        elif current_item is None:
            state = "current"
            current_item = item
        else:
            state = "upcoming"
            upcoming_topics.append(item.topic)

        action_url = None
        activity_title = item.title
        activity_difficulty = item.get_difficulty_display()
        available = False
        if item.game_id:
            activity = item.game
            available = activity.is_active and activity.is_implemented
            activity_title = activity.title
            activity_difficulty = activity.get_difficulty_display()
            if available and activity.slug == "quiz-challenge":
                action_url = reverse("quiz_challenge")
        elif item.simulation_id:
            activity = item.simulation
            available = (
                activity.is_active
                and activity.is_implemented
                and get_simulation_engine(activity.slug) is not None
            )
            activity_title = activity.title
            activity_difficulty = activity.get_difficulty_display()
            if available:
                action_url = reverse("simulation_detail", kwargs={"slug": activity.slug})

        item_states.append(
            {
                "item": item,
                "topic": item.topic,
                "state": state,
                "completed": complete,
                "locked": locked,
                "available": available,
                "activity_title": activity_title,
                "activity_difficulty": activity_difficulty,
                "action_url": action_url,
            }
        )

    completed_count = len(completed_item_ids)
    total = len(items)
    return {
        "path": path,
        "items": item_states,
        "progress_percent": round(completed_count / total * 100) if total else 0,
        "completed_count": completed_count,
        "pending_count": total - completed_count,
        "current_item": next((entry for entry in item_states if entry["state"] == "current"), None),
        "completed_topics": completed_topics,
        "upcoming_topics": upcoming_topics,
        "locked_topics": locked_topics,
    }


def _topic_analysis(user, completed_game_ids, completed_simulation_ids):
    active_topics = list(LearningTopic.objects.filter(is_active=True))
    stats = {
        topic.pk: {
            "topic": topic,
            "answers": 0,
            "correct": 0,
            "question_ids": set(),
            "recent_correct": [],
            "wrong_by_question": defaultdict(int),
        }
        for topic in active_topics
    }

    eligible_answers = GameAttemptAnswer.objects.filter(
        attempt__user=user,
        attempt__game__category=Game.Category.QUIZ,
        attempt__game__is_active=True,
        attempt__game__is_implemented=True,
    ).exclude(attempt__status=GameAttempt.Status.ABANDONED)
    records = eligible_answers.filter(question__topics__is_active=True).values(
        "question_id",
        "is_correct",
        "question__topics__id",
    ).order_by("-answered_at", "-pk")
    for record in records:
        topic_stats = stats.get(record["question__topics__id"])
        if topic_stats is None:
            continue
        topic_stats["answers"] += 1
        topic_stats["correct"] += int(record["is_correct"])
        topic_stats["question_ids"].add(record["question_id"])
        if len(topic_stats["recent_correct"]) < 5:
            topic_stats["recent_correct"].append(int(record["is_correct"]))
        if not record["is_correct"]:
            topic_stats["wrong_by_question"][record["question_id"]] += 1

    bank_counts = {
        row["topics__id"]: row["question_count"]
        for row in Question.objects.filter(
            is_active=True, game__is_active=True, game__is_implemented=True, topics__is_active=True
        ).values("topics__id").annotate(question_count=Count("pk", distinct=True))
    }
    topic_game_map = defaultdict(set)
    for topic_id, game_id in Question.objects.filter(
        is_active=True, game__is_active=True, game__is_implemented=True, topics__is_active=True
    ).values_list("topics__id", "game_id").distinct():
        topic_game_map[topic_id].add(game_id)
    topic_simulation_map = defaultdict(set)
    for topic_id, simulation_id in Simulation.objects.filter(
        is_active=True, is_implemented=True, topic__is_active=True
    ).values_list("topic_id", "pk"):
        topic_simulation_map[topic_id].add(simulation_id)

    simulation_run_scores = defaultdict(list)
    for topic_id, result in SimulationAttempt.objects.filter(
        user=user, simulation__topic__is_active=True
    ).values_list("simulation__topic_id", "results"):
        score = result.get("performance_score") if isinstance(result, dict) else None
        if isinstance(score, (int, float)):
            simulation_run_scores[topic_id].append(float(score))

    mastery_weights = getattr(settings, "ADAPTIVE_MASTERY_WEIGHTS", {})
    weight_total = sum(mastery_weights.values()) or 100
    minimum_answers = getattr(settings, "ADAPTIVE_TOPIC_MIN_ANSWERS", 4)
    minimum_questions = getattr(settings, "ADAPTIVE_TOPIC_MIN_DISTINCT_QUESTIONS", 2)
    strong_threshold = getattr(settings, "ADAPTIVE_STRENGTH_MASTERY_THRESHOLD", 75)
    weak_threshold = getattr(settings, "ADAPTIVE_WEAKNESS_MASTERY_THRESHOLD", 55)
    level_thresholds = getattr(
        settings,
        "ADAPTIVE_MASTERY_LEVEL_THRESHOLDS",
        {"mastered": 90, "proficient": 75, "developing": 50},
    )

    topic_rows = []
    for topic in active_topics:
        row = stats[topic.pk]
        answer_count = row["answers"]
        question_count = len(row["question_ids"])
        accuracy = round(row["correct"] / answer_count * 100) if answer_count else None
        available_question_count = bank_counts.get(topic.pk, 0)
        coverage = min(100, round(question_count / available_question_count * 100)) if available_question_count else 0
        recent_accuracy = round(sum(row["recent_correct"]) / len(row["recent_correct"]) * 100) if row["recent_correct"] else None
        repeated_mistakes = sum(wrong_count >= 2 for wrong_count in row["wrong_by_question"].values())
        enough_evidence = answer_count >= minimum_answers and question_count >= minimum_questions
        activity_completed = bool(
            topic_game_map.get(topic.pk, set()) & completed_game_ids
            or topic_simulation_map.get(topic.pk, set()) & completed_simulation_ids
        )
        simulation_scores = simulation_run_scores.get(topic.pk, [])
        average_simulation_score = round(sum(simulation_scores) / len(simulation_scores)) if simulation_scores else None

        mastery_score = None
        if enough_evidence and accuracy is not None and recent_accuracy is not None:
            weighted_value = (
                accuracy * mastery_weights.get("accuracy", 0)
                + coverage * mastery_weights.get("coverage", 0)
                + int(activity_completed) * 100 * mastery_weights.get("completion", 0)
                + recent_accuracy * mastery_weights.get("recency", 0)
            )
            mastery_score = round(weighted_value / weight_total)

        if not answer_count:
            mastery_level = "Not Started"
            evidence_state = "not_started"
        elif not enough_evidence:
            mastery_level = "Insufficient data"
            evidence_state = "insufficient"
        elif mastery_score >= level_thresholds["mastered"]:
            mastery_level = "Mastered"
            evidence_state = "observed"
        elif mastery_score >= level_thresholds["proficient"]:
            mastery_level = "Proficient"
            evidence_state = "observed"
        elif mastery_score >= level_thresholds["developing"]:
            mastery_level = "Developing"
            evidence_state = "observed"
        else:
            mastery_level = "Beginner"
            evidence_state = "observed"

        inferred_strength = bool(
            enough_evidence and mastery_score >= strong_threshold and accuracy >= 70
        )
        inferred_weakness = bool(
            enough_evidence
            and (mastery_score < weak_threshold or (accuracy < 60 and repeated_mistakes > 0))
        )
        topic_rows.append(
            {
                "topic": topic,
                "answer_count": answer_count,
                "question_count": question_count,
                "available_question_count": available_question_count,
                "observed_accuracy": accuracy,
                "has_observed_accuracy": accuracy is not None,
                "recent_accuracy": recent_accuracy,
                "has_recent_accuracy": recent_accuracy is not None,
                "repeated_mistakes": repeated_mistakes,
                "activity_completed": activity_completed,
                "mastery_score": mastery_score,
                "has_mastery_score": mastery_score is not None,
                "mastery_level": mastery_level,
                "evidence_state": evidence_state,
                "enough_evidence": enough_evidence,
                "is_strength": inferred_strength,
                "is_weakness": inferred_weakness,
                "average_simulation_score": average_simulation_score,
                "simulation_run_count": len(simulation_scores),
            }
        )

    strengths = [row for row in topic_rows if row["is_strength"]]
    weaknesses = [row for row in topic_rows if row["is_weakness"]]
    mastery_scores = [row["mastery_score"] for row in topic_rows if row["mastery_score"] is not None]
    overall_mastery = round(sum(mastery_scores) / len(mastery_scores)) if mastery_scores else None
    return topic_rows, strengths, weaknesses, overall_mastery


def _available_item(item):
    if item.game_id:
        game = item.game
        return game.is_active and game.is_implemented and game.slug == "quiz-challenge"
    if item.simulation_id:
        simulation = item.simulation
        return (
            simulation.is_active
            and simulation.is_implemented
            and get_simulation_engine(simulation.slug) is not None
        )
    return False


def _item_recommendation(item, topic, difficulty, reason, outcome):
    if item.game_id:
        game = item.game
        url = reverse("quiz_challenge")
        actual_difficulty = game.get_difficulty_display()
        action = "Open Quiz Challenge"
    else:
        simulation = item.simulation
        url = reverse("simulation_detail", kwargs={"slug": simulation.slug})
        actual_difficulty = simulation.get_difficulty_display()
        action = "Open Simulation Lab"
    return {
        "activity_name": item.title,
        "topic": topic.name,
        "recommended_difficulty": difficulty,
        "activity_difficulty": actual_difficulty,
        "reason": reason,
        "expected_outcome": outcome,
        "action_url": url,
        "action_label": action,
    }


def recommendation_band_for_accuracy(accuracy):
    if accuracy is None:
        return None
    return next(
        (entry for entry in getattr(settings, "ADAPTIVE_RECOMMENDATION_BANDS", ())
         if entry["minimum"] <= accuracy <= entry["maximum"]),
        None,
    )


def _build_recommendation(user, path_state, topic_rows, weaknesses, accuracy, answer_count, recent_accuracy):
    minimum_answers = getattr(settings, "ADAPTIVE_RECOMMENDATION_MIN_ANSWERS", 5)
    if accuracy is None or answer_count < minimum_answers:
        return None, "insufficient"

    band = recommendation_band_for_accuracy(accuracy)
    if band is None:
        return None, "unconfigured"

    matching_topic = min(
        weaknesses,
        key=lambda row: (row["mastery_score"], row["observed_accuracy"], -row["repeated_mistakes"]),
        default=None,
    )
    current_path_entry = path_state.get("current_item")
    use_path_progression = bool(
        not weaknesses
        and current_path_entry
        and current_path_entry["available"]
        and band["difficulty"] == "Intermediate"
    )
    if matching_topic is None and not use_path_progression:
        matching_topic = min(
            (row for row in topic_rows if row["enough_evidence"] and row["observed_accuracy"] is not None),
            key=lambda row: (row["observed_accuracy"], row["mastery_score"]),
            default=None,
        )
    topic = (
        current_path_entry["topic"]
        if use_path_progression
        else matching_topic["topic"] if matching_topic else LearningTopic.objects.filter(slug="it-fundamentals").first()
    )
    reason = f"Your observed quiz accuracy is {accuracy}% across {answer_count} answers."
    if matching_topic and matching_topic["is_weakness"]:
        reason += f" {topic.name} is an inferred practice area based on {matching_topic['answer_count']} answers across {matching_topic['question_count']} questions."
    if recent_accuracy is not None and recent_accuracy < accuracy - 15:
        reason += f" Your last 10 answers are at {recent_accuracy}%, so a short practice pass is recommended."
    elif recent_accuracy is not None:
        reason += f" Your recent accuracy is {recent_accuracy}%."
    if use_path_progression:
        reason += f" The next open activity in your learning path is {current_path_entry['activity_title']}."
    if topic is None:
        return None, "no_topic"

    items = [entry["item"] for entry in path_state["items"] if entry["available"]]
    selected_item = current_path_entry["item"] if use_path_progression else None
    if selected_item is None:
        selected_item = next((item for item in items if item.topic_id == topic.pk), None)
    if selected_item is None:
        selected_item = next((item for item in items if item.game_id), None)

    if band["difficulty"] == "Advanced":
        advanced_item = next(
            (
                item for item in LearningPathItem.objects.filter(path__is_active=True)
                .select_related("game", "simulation", "topic")
                if item.difficulty == LearningPathItem.Difficulty.ADVANCED and _available_item(item)
            ),
            None,
        )
        if advanced_item is None:
            return None, "advanced_unavailable"
        selected_item = advanced_item

    if selected_item is None:
        return None, "no_available_activity"

    outcome = (
        f"Build confidence in {topic.name} through the activity's current questions and feedback."
        if selected_item.game_id
        else f"Apply {topic.name} concepts by adjusting the system and interpreting the resulting metrics."
    )
    return (
        _item_recommendation(selected_item, topic, band["difficulty"], reason, outcome),
        "ready",
    )


def _recent_activity(user):
    quiz_runs = GameAttempt.objects.filter(
        user=user, game__category=Game.Category.QUIZ, game__is_implemented=True
    ).select_related("game").annotate(
        answered_count=Count("answers"),
        correct_count=Count("answers", filter=Q(answers__is_correct=True)),
    ).order_by("-started_at")[:6]
    activities = [
        {
            "kind": "quiz",
            "title": attempt.game.title,
            "date": attempt.ended_at or attempt.started_at,
            "detail": f"{attempt.correct_count}/{attempt.answered_count} correct · {attempt.get_status_display()}",
            "score": attempt.score_percent if attempt.status == GameAttempt.Status.COMPLETED else None,
            "has_score": attempt.status == GameAttempt.Status.COMPLETED,
        }
        for attempt in quiz_runs
    ]
    for run in SimulationAttempt.objects.filter(user=user).select_related("simulation").order_by("-completed_at")[:6]:
        performance_score = run.results.get("performance_score")
        activities.append(
            {
                "kind": "simulation",
                "title": run.simulation.title,
                "date": run.completed_at,
                "detail": f"Experiment output: system score {performance_score}/100 · not a learner score",
                "score": None,
                "has_score": False,
            }
        )
    return sorted(activities, key=lambda activity: activity["date"], reverse=True)[:8]


def build_adaptive_snapshot(user):
    """Build one learner-scoped view model from existing quiz/simulation records."""
    answers = GameAttemptAnswer.objects.filter(
        attempt__user=user,
        attempt__game__category=Game.Category.QUIZ,
        attempt__game__is_active=True,
        attempt__game__is_implemented=True,
    ).exclude(attempt__status=GameAttempt.Status.ABANDONED)
    totals = answers.aggregate(
        answer_count=Count("pk"),
        correct_count=Count("pk", filter=Q(is_correct=True)),
    )
    answer_count = totals["answer_count"] or 0
    correct_count = totals["correct_count"] or 0
    accuracy = round(correct_count / answer_count * 100) if answer_count else None
    recent_values = list(answers.order_by("-answered_at", "-pk").values_list("is_correct", flat=True)[:10])
    recent_accuracy = round(sum(recent_values) / len(recent_values) * 100) if recent_values else None
    completed_game_ids = set(
        GameAttempt.objects.filter(
            user=user, status=GameAttempt.Status.COMPLETED, game__is_implemented=True
        ).values_list("game_id", flat=True).distinct()
    )
    completed_simulation_ids = set(
        SimulationCompletion.objects.filter(user=user).values_list("simulation_id", flat=True)
    )
    path_state = _learning_path_state(user)
    topic_rows, strengths, weaknesses, overall_mastery = _topic_analysis(
        user, completed_game_ids, completed_simulation_ids
    )
    recommendation, recommendation_state = _build_recommendation(
        user, path_state, topic_rows, weaknesses, accuracy, answer_count, recent_accuracy
    )
    simulation_count = SimulationCompletion.objects.filter(user=user).count()
    experiment_count = SimulationAttempt.objects.filter(user=user).count()
    completed_game_count = len(completed_game_ids)
    onboarding_activity = path_state["current_item"]
    return {
        "accuracy": accuracy,
        "has_accuracy": accuracy is not None,
        "correct_answer_count": correct_count,
        "answer_count": answer_count,
        "recent_accuracy": recent_accuracy,
        "completed_quiz_count": GameAttempt.objects.filter(
            user=user, status=GameAttempt.Status.COMPLETED, game__category=Game.Category.QUIZ
        ).count(),
        "completed_game_count": completed_game_count,
        "completed_simulation_count": simulation_count,
        "experiment_count": experiment_count,
        "topics": topic_rows,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_mastery": overall_mastery,
        "has_overall_mastery": overall_mastery is not None,
        "path_state": path_state,
        "recommendation": recommendation,
        "recommendation_state": recommendation_state,
        "onboarding_activity": onboarding_activity,
        "recent_activity": _recent_activity(user),
        "has_performance_data": answer_count > 0 or experiment_count > 0,
        "enough_recommendation_data": answer_count >= getattr(settings, "ADAPTIVE_RECOMMENDATION_MIN_ANSWERS", 5),
    }
