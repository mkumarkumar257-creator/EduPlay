"""User-scoped, database-backed analytics for learners and educators."""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Q
from django.utils import timezone

from .forms import AnalyticsFilterForm
from .models import (
    Challenge,
    ContentStatus,
    Game,
    GameAttempt,
    GameAttemptAnswer,
    LearnerContentProgress,
    LearningLesson,
    LearningTopic,
    PracticeActivity,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
    TeamActivity,
    TeamChallenge,
    TeamMembership,
    User,
)
from .simulation_engine import get_simulation_engine


DEFAULT_FILTERS = {"period": "30d", "activity_type": "all", "topic": ""}
COLLABORATION_ACTIVITY_EVENTS = (
    TeamActivity.Event.CHALLENGE_STARTED,
    TeamActivity.Event.CHALLENGE_PROGRESS_SAVED,
)


def _filter_form(params=None):
    has_filters = params and any(key in params for key in ("period", "activity_type", "topic"))
    form = AnalyticsFilterForm(params if has_filters else DEFAULT_FILTERS)
    if not form.is_valid():
        form = AnalyticsFilterForm(DEFAULT_FILTERS)
        form.is_valid()
    return form


def _scope_from_form(form):
    now = timezone.now()
    today = timezone.localdate(now)
    period = form.cleaned_data["period"]
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period)
    start_date = today - timedelta(days=days - 1) if days else None
    start_at = timezone.make_aware(datetime.combine(start_date, time.min)) if start_date else None
    end_at = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    topic = form.cleaned_data.get("topic")
    return {
        "period": period,
        "start_date": start_date,
        "start_at": start_at,
        "end_at": end_at,
        "activity_type": form.cleaned_data["activity_type"],
        "topic": topic,
        "topic_id": topic.pk if topic else None,
        "filters": form,
    }


def _date_filter(queryset, field, scope):
    if scope["start_at"]:
        queryset = queryset.filter(**{f"{field}__gte": scope["start_at"]})
    return queryset.filter(**{f"{field}__lt": scope["end_at"]})


def _game_type_filter(queryset, activity_type):
    if activity_type == "quiz":
        return queryset.filter(game__category=Game.Category.QUIZ)
    if activity_type == "game":
        return queryset.exclude(game__category=Game.Category.QUIZ)
    if activity_type in {"simulation", "collaboration", "lesson", "practice"}:
        return queryset.none()
    return queryset


def _authored_content_progress_rows(*, scope, learner=None):
    """Load one row per learner/content item without generic-FK N+1 queries."""
    content_rows = {}
    for kind, model in (("lesson", LearningLesson), ("practice", PracticeActivity)):
        activity_type = scope["activity_type"]
        if activity_type not in {"all", kind}:
            content_rows[kind] = []
            continue

        content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
        progress = LearnerContentProgress.objects.filter(content_type=content_type)
        if learner is not None:
            progress = progress.filter(learner=learner)
        else:
            progress = progress.filter(learner__role=User.Role.LEARNER)
        progress = _date_filter(progress, "updated_at", scope)
        if scope["topic"]:
            matching_ids = model.objects.filter(topic=scope["topic"]).values("pk")
            progress = progress.filter(object_id__in=matching_ids)

        rows = list(progress.values(
            "learner_id", "object_id", "status", "started_at", "completed_at", "updated_at"
        ))
        title_by_id = dict(
            model.objects.filter(pk__in={row["object_id"] for row in rows})
            .values_list("pk", "title")
        )
        content_rows[kind] = [
            {
                **row,
                "kind": kind,
                "title": title_by_id[row["object_id"]],
                "activity_date": row["completed_at"] or row["started_at"],
            }
            for row in rows
            if row["object_id"] in title_by_id
        ]
    return content_rows


def _active_team_challenges_for_user(user):
    return TeamChallenge.objects.filter(
        status=TeamChallenge.Status.COMPLETED,
        team__memberships__user=user,
        team__memberships__joined_at__lte=F("completed_at"),
    ).filter(
        Q(team__memberships__left_at__isnull=True)
        | Q(team__memberships__left_at__gte=F("completed_at"))
    ).distinct()


def _catalog(scope):
    activity_type = scope["activity_type"]
    topic_id = scope["topic_id"]
    game_ids = set()
    simulation_ids = set()
    challenge_ids = set()

    if activity_type in {"all", "quiz", "game"}:
        games = Game.objects.filter(
            is_active=True,
            is_implemented=True,
            status=Game.Status.PUBLISHED,
            visibility=Game.Visibility.PUBLIC,
        )
        if activity_type == "quiz":
            games = games.filter(category=Game.Category.QUIZ)
        elif activity_type == "game":
            games = games.exclude(category=Game.Category.QUIZ)
        if topic_id:
            games = games.filter(questions__topics=topic_id)
        game_ids = set(games.distinct().values_list("pk", flat=True))

    if activity_type in {"all", "simulation"}:
        simulations = Simulation.objects.filter(is_active=True, is_implemented=True)
        if topic_id:
            simulations = simulations.filter(topic_id=topic_id)
        simulation_ids = {
            pk for pk, slug in simulations.values_list("pk", "slug")
            if get_simulation_engine(slug) is not None
        }

    lesson_ids = set()
    practice_ids = set()
    if activity_type in {"all", "lesson"}:
        lessons = LearningLesson.objects.filter(
            status=ContentStatus.PUBLISHED, visibility=LearningLesson.Visibility.PUBLIC
        )
        if topic_id:
            lessons = lessons.filter(topic_id=topic_id)
        lesson_ids = set(lessons.values_list("pk", flat=True))
    if activity_type in {"all", "practice"}:
        practices = PracticeActivity.objects.filter(
            status=ContentStatus.PUBLISHED, visibility=PracticeActivity.Visibility.PUBLIC
        )
        if topic_id:
            practices = practices.filter(topic_id=topic_id)
        practice_ids = set(practices.values_list("pk", flat=True))

    if activity_type in {"all", "collaboration"} and not topic_id:
        challenge_ids = set(
            Challenge.objects.filter(
                status=Challenge.Status.PUBLISHED,
                visibility=Challenge.Visibility.PUBLIC,
            )
            .values_list("pk", flat=True)
        )

    return {
        "games": game_ids,
        "simulations": simulation_ids,
        "challenges": challenge_ids,
        "lessons": lesson_ids,
        "practice": practice_ids,
    }


def _catalog_count(catalog):
    return sum(len(items) for items in catalog.values())


def _topic_answer_rows(answer_queryset):
    return list(
        answer_queryset.filter(question__topics__is_active=True)
        .values("question__topics__id", "question__topics__name")
        .annotate(
            answer_count=Count("pk"),
            correct_count=Count("pk", filter=Q(is_correct=True)),
            question_count=Count("question_id", distinct=True),
        )
        .order_by("question__topics__name")
    )


def _enough_topic_evidence(row):
    return (
        row["answer_count"] >= getattr(settings, "ADAPTIVE_TOPIC_MIN_ANSWERS", 4)
        and row["question_count"] >= getattr(settings, "ADAPTIVE_TOPIC_MIN_DISTINCT_QUESTIONS", 2)
    )


def _topic_insights(rows):
    evidence_rows = []
    for row in rows:
        if not _enough_topic_evidence(row):
            continue
        accuracy = round(row["correct_count"] / row["answer_count"] * 100, 1)
        evidence_rows.append({**row, "accuracy": accuracy})
    evidence_rows.sort(key=lambda row: (row["accuracy"], -row["answer_count"]))
    strength_limit = getattr(settings, "ADAPTIVE_STRENGTH_MASTERY_THRESHOLD", 75)
    weakness_limit = getattr(settings, "ADAPTIVE_WEAKNESS_MASTERY_THRESHOLD", 55)
    strengths = [row for row in evidence_rows if row["accuracy"] >= strength_limit]
    weaknesses = [row for row in evidence_rows if row["accuracy"] < weakness_limit]
    return evidence_rows, strengths, weaknesses


def _activity_buckets(datetimes, scope):
    local_values = [timezone.localtime(value) for value in datetimes if value]
    if not local_values:
        return [], [], "day"
    today = timezone.localdate()
    if scope["period"] == "all":
        first_month = min(value.date() for value in local_values).replace(day=1)
        current_month = today.replace(day=1)
        months = []
        cursor = first_month
        while cursor <= current_month:
            months.append(cursor)
            next_month = cursor.month % 12 + 1
            next_year = cursor.year + (cursor.month == 12)
            cursor = cursor.replace(year=next_year, month=next_month)
        keys = [value.strftime("%Y-%m") for value in months]
        labels = [value.strftime("%b %Y") for value in months]
        return keys, labels, "month"
    if scope["period"] == "90d":
        first_day = scope["start_date"] - timedelta(days=scope["start_date"].weekday())
        current_week = today - timedelta(days=today.weekday())
        weeks = []
        cursor = first_day
        while cursor <= current_week:
            weeks.append(cursor)
            cursor += timedelta(days=7)
        return (
            [value.strftime("%Y-%m-%d") for value in weeks],
            [f"Week of {value.strftime('%b')} {value.day}" for value in weeks],
            "week",
        )
    dates = [scope["start_date"] + timedelta(days=offset) for offset in range((today - scope["start_date"]).days + 1)]
    return (
        [value.strftime("%Y-%m-%d") for value in dates],
        [f"{value.strftime('%b')} {value.day}" for value in dates],
        "day",
    )


def _bucket_key(value, granularity):
    local_date = timezone.localtime(value).date()
    if granularity == "month":
        return local_date.strftime("%Y-%m")
    if granularity == "week":
        monday = local_date - timedelta(days=local_date.weekday())
        return monday.strftime("%Y-%m-%d")
    return local_date.strftime("%Y-%m-%d")


def _make_chart_series(activity_events, xp_events, scope):
    all_times = [event["date"] for event in activity_events]
    keys, labels, granularity = _activity_buckets(all_times, scope)
    if not keys:
        empty = {"labels": [], "values": []}
        return empty, empty, 0
    activity_count = Counter(_bucket_key(event["date"], granularity) for event in activity_events)
    xp_by_bucket = Counter()
    period_xp = 0
    for event in xp_events:
        amount = int(event["amount"] or 0)
        if amount > 0:
            xp_by_bucket[_bucket_key(event["date"], granularity)] += amount
            period_xp += amount
    cumulative = 0
    xp_values = []
    activity_values = []
    for key in keys:
        cumulative += xp_by_bucket[key]
        xp_values.append(cumulative)
        activity_values.append(activity_count[key])
    return (
        {"labels": labels, "values": xp_values},
        {"labels": labels, "values": activity_values},
        period_xp,
    )


def _current_streak(activity_dates, today=None):
    today = today or timezone.localdate()
    unique_dates = set(activity_dates)
    cursor = today if today in unique_dates else today - timedelta(days=1)
    streak = 0
    while cursor in unique_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _learner_scope_queries(user, scope):
    activity_type = scope["activity_type"]
    topic = scope["topic"]

    games_qs = _date_filter(
        GameAttempt.objects.filter(
            user=user,
            status=GameAttempt.Status.COMPLETED,
            game__is_implemented=True,
        ),
        "ended_at",
        scope,
    )
    games_qs = _game_type_filter(games_qs, activity_type)
    if topic:
        games_qs = games_qs.filter(answers__question__topics=topic).distinct()
    game_rows = list(
        games_qs.order_by("ended_at", "pk").values(
            "pk", "game_id", "game__title", "game__category", "ended_at",
            "correct_answers", "total_questions", "xp_awarded",
        )
    )

    if activity_type in {"all", "quiz"}:
        quiz_qs = _date_filter(
            GameAttempt.objects.filter(
                user=user,
                status=GameAttempt.Status.COMPLETED,
                game__category=Game.Category.QUIZ,
                game__is_implemented=True,
                ended_at__isnull=False,
            ),
            "ended_at",
            scope,
        )
        if topic:
            quiz_qs = quiz_qs.filter(answers__question__topics=topic).distinct()
        quiz_attempts = list(
            quiz_qs.annotate(
                answer_count=Count("answers__pk", distinct=True),
                correct_count=Count("answers__pk", filter=Q(answers__is_correct=True), distinct=True),
            ).filter(answer_count__gt=0).order_by("ended_at", "pk").values(
                "pk", "game__title", "ended_at", "answer_count", "correct_count"
            )
        )
        answers_qs = _date_filter(
            GameAttemptAnswer.objects.filter(
                attempt__user=user,
                attempt__status=GameAttempt.Status.COMPLETED,
                attempt__game__category=Game.Category.QUIZ,
                attempt__game__is_implemented=True,
            ),
            "attempt__ended_at",
            scope,
        )
        if topic:
            answers_qs = answers_qs.filter(question__topics=topic)
        topic_rows = _topic_answer_rows(answers_qs)
    else:
        quiz_attempts = []
        answers_qs = GameAttemptAnswer.objects.none()
        topic_rows = []

    simulations_qs = Simulation.objects.none()
    if activity_type in {"all", "simulation"}:
        simulations_qs = SimulationCompletion.objects.filter(
            user=user, simulation__is_implemented=True
        )
        simulations_qs = _date_filter(simulations_qs, "completed_at", scope)
        if topic:
            simulations_qs = simulations_qs.filter(simulation__topic=topic)
    simulation_completions = list(
        simulations_qs.order_by("completed_at", "pk").values(
            "simulation_id", "simulation__title", "completed_at", "xp_awarded"
        )
    )

    runs_qs = SimulationAttempt.objects.none()
    if activity_type in {"all", "simulation"}:
        runs_qs = SimulationAttempt.objects.filter(
            user=user, status=SimulationAttempt.Status.COMPLETED, simulation__is_implemented=True
        )
        runs_qs = _date_filter(runs_qs, "completed_at", scope)
        if topic:
            runs_qs = runs_qs.filter(simulation__topic=topic)
    simulation_runs = list(
        runs_qs.order_by("completed_at", "pk").values(
            "simulation_id", "simulation__title", "completed_at", "xp_awarded", "results"
        )
    )

    team_challenges_qs = TeamChallenge.objects.none()
    team_events_qs = TeamActivity.objects.none()
    if activity_type in {"all", "collaboration"} and not topic:
        team_challenges_qs = _date_filter(_active_team_challenges_for_user(user), "completed_at", scope)
        team_events_qs = _date_filter(
            TeamActivity.objects.filter(
                actor=user,
                event_type__in=COLLABORATION_ACTIVITY_EVENTS,
            ),
            "created_at",
            scope,
        )
    team_completions = list(
        team_challenges_qs.order_by("completed_at", "pk").values(
            "team_id", "team__name", "challenge_id", "challenge__title", "completed_at", "xp_awarded"
        )
    )
    team_events = list(
        team_events_qs.order_by("created_at", "pk").values(
            "event_type", "message", "created_at", "team__name"
        )
    )

    content_progress = _authored_content_progress_rows(scope=scope, learner=user)
    lesson_progress = content_progress["lesson"]
    practice_progress = content_progress["practice"]

    practice_dates = []
    practice_dates.extend(row["ended_at"] for row in game_rows if row["ended_at"])
    if activity_type in {"all", "quiz"}:
        practice_answers = GameAttemptAnswer.objects.filter(
            attempt__user=user,
            attempt__status__in=(
                GameAttempt.Status.COMPLETED,
                GameAttempt.Status.IN_PROGRESS,
                GameAttempt.Status.TIMED_OUT,
            ),
            attempt__game__category=Game.Category.QUIZ,
            attempt__game__is_implemented=True,
        )
        practice_answers = _date_filter(practice_answers, "answered_at", scope)
        if topic:
            practice_answers = practice_answers.filter(question__topics=topic)
        practice_dates.extend(practice_answers.values_list("answered_at", flat=True))
    practice_dates.extend(row["completed_at"] for row in simulation_runs)
    practice_dates.extend(row["created_at"] for row in team_events)
    practice_dates.extend(row["completed_at"] for row in team_completions)
    practice_dates.extend(row["activity_date"] for row in lesson_progress + practice_progress)

    activity_events = []
    xp_events = []
    for row in game_rows:
        activity_events.append({
            "date": row["ended_at"],
            "kind": "quiz" if row["game__category"] == Game.Category.QUIZ else "game",
            "title": row["game__title"],
            "detail": f"{row['correct_answers']}/{row['total_questions']} correct",
            "xp": row["xp_awarded"],
        })
        xp_events.append({"date": row["ended_at"], "amount": row["xp_awarded"], "kind": "quiz"})
    for row in simulation_runs:
        activity_events.append({
            "date": row["completed_at"],
            "kind": "simulation",
            "title": row["simulation__title"],
            "detail": "Simulation run completed · system output, not a learner score",
            "xp": row["xp_awarded"],
        })
        xp_events.append({"date": row["completed_at"], "amount": row["xp_awarded"], "kind": "simulation"})
    for row in team_events:
        activity_events.append({
            "date": row["created_at"],
            "kind": "collaboration",
            "title": row["team__name"],
            "detail": row["message"],
            "xp": 0,
        })
    for row in team_completions:
        activity_events.append({
            "date": row["completed_at"],
            "kind": "collaboration",
            "title": row["challenge__title"],
            "detail": f"{row['team__name']} completed the challenge · personal team reward recorded",
            "xp": row["xp_awarded"],
        })
        xp_events.append({"date": row["completed_at"], "amount": row["xp_awarded"], "kind": "collaboration"})
    for row in lesson_progress + practice_progress:
        status_label = "completed" if row["status"] == LearnerContentProgress.Status.COMPLETED else "in progress"
        activity_events.append({
            "date": row["activity_date"],
            "kind": row["kind"],
            "title": row["title"],
            "detail": f"{row['kind'].title()} {status_label}",
            "xp": 0,
        })
    activity_events.sort(key=lambda event: event["date"], reverse=True)

    return {
        "game_rows": game_rows,
        "quiz_attempts": quiz_attempts,
        "answers_qs": answers_qs,
        "topic_rows": topic_rows,
        "simulation_completions": simulation_completions,
        "simulation_runs": simulation_runs,
        "team_completions": team_completions,
        "team_events": team_events,
        "lesson_progress": lesson_progress,
        "practice_progress": practice_progress,
        "practice_dates": [timezone.localtime(value).date() for value in practice_dates],
        "activity_events": activity_events,
        "xp_events": xp_events,
    }


def _learner_insights(topic_rows, quiz_attempts, practice_dates, quiz_answer_count, quiz_accuracy):
    evidence_rows, strengths, weaknesses = _topic_insights(topic_rows)
    facts = []
    recommendations = []
    if quiz_answer_count >= getattr(settings, "ADAPTIVE_RECOMMENDATION_MIN_ANSWERS", 5) and quiz_accuracy is not None:
        facts.append(
            f"Your recorded quiz accuracy is {quiz_accuracy:.1f}% across {quiz_answer_count} answers in this filter range."
        )
    if evidence_rows:
        most_practiced = max(evidence_rows, key=lambda row: row["answer_count"])
        facts.append(
            f"You practiced {most_practiced['question__topics__name']} most often: "
            f"{most_practiced['answer_count']} answers across {most_practiced['question_count']} questions."
        )
        if weaknesses:
            weakest = weaknesses[0]
            facts.append(
                f"Observed accuracy in {weakest['question__topics__name']} is {weakest['accuracy']:.1f}% "
                f"({weakest['answer_count']} answers across {weakest['question_count']} questions)."
            )
            recommendations.append(
                f"Consider revisiting {weakest['question__topics__name']}; its observed accuracy is below "
                f"the {getattr(settings, 'ADAPTIVE_WEAKNESS_MASTERY_THRESHOLD', 55)}% practice threshold."
            )
        elif strengths:
            strongest = strengths[-1]
            facts.append(
                f"{strongest['question__topics__name']} is a current strength based on "
                f"{strongest['answer_count']} answers across {strongest['question_count']} questions."
            )
    if len(quiz_attempts) >= 4:
        midpoint = len(quiz_attempts) // 2
        earlier = [row["correct_count"] / row["answer_count"] * 100 for row in quiz_attempts[:midpoint]]
        later = [row["correct_count"] / row["answer_count"] * 100 for row in quiz_attempts[midpoint:]]
        change = (sum(later) / len(later)) - (sum(earlier) / len(earlier))
        if change >= 5:
            facts.append(f"Average quiz accuracy improved by {change:.1f} points between the earlier and later attempts in this range.")
        elif change <= -5:
            facts.append(f"Average quiz accuracy was {abs(change):.1f} points lower in the later attempts; this is a trend to review, not a mastery judgment.")
    active_days = len(set(practice_dates))
    if active_days >= 3:
        facts.append(f"You recorded learning activity on {active_days} distinct days in this filter range.")
    return facts, recommendations, evidence_rows


def build_learner_analytics(user, params=None):
    form = _filter_form(params)
    scope = _scope_from_form(form)
    records = _learner_scope_queries(user, scope)
    quiz_answer_count = sum(row["answer_count"] for row in records["quiz_attempts"])
    quiz_correct_count = sum(row["correct_count"] for row in records["quiz_attempts"])
    quiz_accuracy = (
        round(quiz_correct_count / quiz_answer_count * 100, 1) if quiz_answer_count else None
    )
    catalog = _catalog(scope)
    completed_game_ids = {row["game_id"] for row in records["game_rows"]} & catalog["games"]
    completed_simulation_ids = {
        row["simulation_id"] for row in records["simulation_completions"]
    } & catalog["simulations"]
    completed_challenge_ids = {row["challenge_id"] for row in records["team_completions"]} & catalog["challenges"]
    completed_lesson_ids = {
        row["object_id"] for row in records["lesson_progress"]
        if row["status"] == LearnerContentProgress.Status.COMPLETED
    } & catalog["lessons"]
    completed_practice_ids = {
        row["object_id"] for row in records["practice_progress"]
        if row["status"] == LearnerContentProgress.Status.COMPLETED
    } & catalog["practice"]
    completed_targets = (
        len(completed_game_ids) + len(completed_simulation_ids) + len(completed_challenge_ids)
        + len(completed_lesson_ids) + len(completed_practice_ids)
    )
    catalog_size = _catalog_count(catalog)
    progress = round(completed_targets / catalog_size * 100) if catalog_size else None

    xp_series, activity_series, period_xp = _make_chart_series(
        records["activity_events"], records["xp_events"], scope
    )
    quiz_labels = [
        f"{timezone.localtime(row['ended_at']).strftime('%b')} {timezone.localtime(row['ended_at']).day} · {row['game__title']}"
        for row in records["quiz_attempts"]
    ]
    quiz_scores = [round(row["correct_count"] / row["answer_count"] * 100, 1) for row in records["quiz_attempts"]]
    min_topic_answers = getattr(settings, "ADAPTIVE_TOPIC_MIN_ANSWERS", 4)
    min_topic_questions = getattr(settings, "ADAPTIVE_TOPIC_MIN_DISTINCT_QUESTIONS", 2)
    facts, recommendations, topic_evidence = _learner_insights(
        records["topic_rows"], records["quiz_attempts"], records["practice_dates"],
        quiz_answer_count, quiz_accuracy,
    )
    topic_chart_rows = [
        row for row in topic_evidence
        if row["answer_count"] >= min_topic_answers and row["question_count"] >= min_topic_questions
    ]
    distribution = Counter(event["kind"] for event in records["activity_events"])
    distribution_labels = [
        "Quiz completions", "Other game completions", "Simulation runs", "Team challenge activity",
        "Lessons completed", "Practice activities completed",
    ]
    lesson_completion_count = sum(
        row["status"] == LearnerContentProgress.Status.COMPLETED for row in records["lesson_progress"]
    )
    practice_completion_count = sum(
        row["status"] == LearnerContentProgress.Status.COMPLETED for row in records["practice_progress"]
    )
    distribution_values = [
        distribution["quiz"], distribution["game"], distribution["simulation"], distribution["collaboration"],
        lesson_completion_count, practice_completion_count,
    ]
    today = timezone.localdate()
    streak = _current_streak(records["practice_dates"], today)
    active_days = len(set(records["practice_dates"]))
    current_level = user.total_xp // 100 + 1
    recent_activity = records["activity_events"][:10]
    return {
        "filters": form,
        "scope": scope,
        "total_xp": user.total_xp,
        "xp_in_period": period_xp,
        "level": current_level,
        "xp_into_level": user.total_xp % 100,
        "xp_to_next_level": 100 - user.total_xp % 100,
        "games_completed": len(records["game_rows"]),
        "simulations_completed": len(records["simulation_completions"]),
        "team_challenges_completed": len(records["team_completions"]),
        "lessons_completed": lesson_completion_count,
        "practice_activities_completed": practice_completion_count,
        "quiz_accuracy": quiz_accuracy,
        "quiz_answer_count": quiz_answer_count,
        "quiz_correct_count": quiz_correct_count,
        "has_quiz_accuracy": quiz_accuracy is not None,
        "learning_streak": streak,
        "active_days": active_days,
        "overall_progress": progress,
        "has_overall_progress": progress is not None,
        "completed_targets": completed_targets,
        "catalog_size": catalog_size,
        "total_activities": len(records["activity_events"]),
        "recent_activity": recent_activity,
        "facts": facts,
        "recommendations": recommendations,
        "has_insights": bool(facts or recommendations),
        "insufficient_insight_data": not bool(facts or recommendations),
        "topic_evidence": topic_evidence,
        "min_topic_answers": min_topic_answers,
        "min_topic_questions": min_topic_questions,
        "charts": {
            "xp": xp_series,
            "activity": activity_series,
            "quiz": {"labels": quiz_labels, "values": quiz_scores},
            "topics": {
                "labels": [row["question__topics__name"] for row in topic_chart_rows],
                "values": [row["accuracy"] for row in topic_chart_rows],
            },
            "distribution": {"labels": distribution_labels, "values": distribution_values},
        },
        "chart_has_data": {
            "xp": period_xp > 0,
            "activity": bool(records["activity_events"]),
            "quiz": bool(quiz_scores),
            "topics": bool(topic_chart_rows),
            "distribution": any(distribution_values),
        },
        "show_course_filter": False,
        "topic_filter_note": bool(scope["topic_id"]),
        "achievements_tracked": False,
    }


def _educator_team_completion_rows(scope):
    if scope["activity_type"] not in {"all", "collaboration"} or scope["topic_id"]:
        return []
    queryset = TeamChallenge.objects.filter(
        status=TeamChallenge.Status.COMPLETED,
        team__memberships__user__role=User.Role.LEARNER,
        team__memberships__joined_at__lte=F("completed_at"),
    ).filter(
        Q(team__memberships__left_at__isnull=True)
        | Q(team__memberships__left_at__gte=F("completed_at"))
    )
    queryset = _date_filter(queryset, "completed_at", scope)
    return list(
        queryset.values(
            "team__memberships__user_id", "team_id", "challenge_id", "challenge__title",
            "completed_at", "xp_awarded",
        ).distinct()
    )


def build_educator_analytics(params=None):
    form = _filter_form(params)
    scope = _scope_from_form(form)
    learners = list(
        User.objects.filter(role=User.Role.LEARNER)
        .only("pk", "username", "first_name", "last_name", "total_xp", "date_joined")
        .order_by("username")
    )
    learner_ids = [learner.pk for learner in learners]
    game_queryset = _date_filter(
        GameAttempt.objects.filter(
            user__role=User.Role.LEARNER,
            status=GameAttempt.Status.COMPLETED,
            game__is_implemented=True,
        ),
        "ended_at",
        scope,
    )
    game_queryset = _game_type_filter(game_queryset, scope["activity_type"])
    if scope["topic"]:
        game_queryset = game_queryset.filter(answers__question__topics=scope["topic"]).distinct()
    game_rows = list(
        game_queryset.values(
            "user_id", "game_id", "game__category", "game__title", "ended_at",
            "correct_answers", "total_questions", "xp_awarded",
        )
    )

    answer_queryset = GameAttemptAnswer.objects.filter(
        attempt__user__role=User.Role.LEARNER,
        attempt__status=GameAttempt.Status.COMPLETED,
        attempt__game__category=Game.Category.QUIZ,
        attempt__game__is_implemented=True,
    )
    answer_queryset = _date_filter(answer_queryset, "attempt__ended_at", scope)
    if scope["activity_type"] not in {"all", "quiz"}:
        answer_queryset = answer_queryset.none()
    if scope["topic"]:
        answer_queryset = answer_queryset.filter(question__topics=scope["topic"])
    answer_totals = answer_queryset.aggregate(
        total=Count("pk"),
        correct=Count("pk", filter=Q(is_correct=True)),
    )
    quiz_topic_rows = _topic_answer_rows(answer_queryset)
    answer_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    for row in answer_queryset.values("attempt__user_id").annotate(
        total=Count("pk"), correct=Count("pk", filter=Q(is_correct=True))
    ):
        answer_stats[row["attempt__user_id"]] = {"total": row["total"], "correct": row["correct"]}

    simulation_completions = []
    simulation_runs = []
    if scope["activity_type"] in {"all", "simulation"}:
        completion_queryset = _date_filter(
            SimulationCompletion.objects.filter(
                user__role=User.Role.LEARNER, simulation__is_implemented=True
            ),
            "completed_at",
            scope,
        )
        runs_queryset = _date_filter(
            SimulationAttempt.objects.filter(
                user__role=User.Role.LEARNER,
                status=SimulationAttempt.Status.COMPLETED,
                simulation__is_implemented=True,
            ),
            "completed_at",
            scope,
        )
        if scope["topic"]:
            completion_queryset = completion_queryset.filter(simulation__topic=scope["topic"])
            runs_queryset = runs_queryset.filter(simulation__topic=scope["topic"])
        simulation_completions = list(
            completion_queryset.values("user_id", "simulation_id", "completed_at")
        )
        simulation_runs = list(runs_queryset.values("user_id", "simulation_id", "completed_at", "xp_awarded"))

    team_completions = _educator_team_completion_rows(scope)
    team_events = []
    if scope["activity_type"] in {"all", "collaboration"} and not scope["topic"]:
        event_queryset = _date_filter(
            TeamActivity.objects.filter(
                actor__role=User.Role.LEARNER,
                event_type__in=COLLABORATION_ACTIVITY_EVENTS,
            ),
            "created_at",
            scope,
        )
        team_events = list(event_queryset.values("actor_id", "created_at", "event_type"))

    content_progress = _authored_content_progress_rows(scope=scope)
    lesson_progress = content_progress["lesson"]
    practice_progress = content_progress["practice"]

    catalog = _catalog(scope)
    catalog_size = _catalog_count(catalog)
    game_pairs = {
        (row["user_id"], row["game_id"])
        for row in game_rows
        if row["game_id"] in catalog["games"]
    }
    simulation_pairs = {
        (row["user_id"], row["simulation_id"])
        for row in simulation_completions
        if row["simulation_id"] in catalog["simulations"]
    }
    challenge_pairs = {
        (row["team__memberships__user_id"], row["challenge_id"])
        for row in team_completions
        if row["challenge_id"] in catalog["challenges"]
    }
    lesson_pairs = {
        (row["learner_id"], row["object_id"])
        for row in lesson_progress
        if row["status"] == LearnerContentProgress.Status.COMPLETED
        and row["object_id"] in catalog["lessons"]
    }
    practice_pairs = {
        (row["learner_id"], row["object_id"])
        for row in practice_progress
        if row["status"] == LearnerContentProgress.Status.COMPLETED
        and row["object_id"] in catalog["practice"]
    }
    completed_by_learner = defaultdict(set)
    for learner_id, content_id in game_pairs:
        completed_by_learner[learner_id].add(("game", content_id))
    for learner_id, content_id in simulation_pairs:
        completed_by_learner[learner_id].add(("simulation", content_id))
    for learner_id, content_id in challenge_pairs:
        completed_by_learner[learner_id].add(("challenge", content_id))
    for learner_id, content_id in lesson_pairs:
        completed_by_learner[learner_id].add(("lesson", content_id))
    for learner_id, content_id in practice_pairs:
        completed_by_learner[learner_id].add(("practice", content_id))

    activities_by_learner = Counter()
    last_activity = {}
    active_learners = set()
    xp_rows = Counter()
    for row in game_rows:
        learner_id = row["user_id"]
        activities_by_learner[learner_id] += 1
        active_learners.add(learner_id)
        last_activity[learner_id] = max(last_activity.get(learner_id, row["ended_at"]), row["ended_at"])
        xp_rows[learner_id] += row["xp_awarded"]
    for row in simulation_runs:
        activities_by_learner[row["user_id"]] += 1
        active_learners.add(row["user_id"])
        last_activity[row["user_id"]] = max(last_activity.get(row["user_id"], row["completed_at"]), row["completed_at"])
        xp_rows[row["user_id"]] += row["xp_awarded"]
    for row in team_completions:
        learner_id = row["team__memberships__user_id"]
        activities_by_learner[learner_id] += 1
        active_learners.add(learner_id)
        last_activity[learner_id] = max(last_activity.get(learner_id, row["completed_at"]), row["completed_at"])
        xp_rows[learner_id] += row["xp_awarded"]
    for row in team_events:
        learner_id = row["actor_id"]
        active_learners.add(learner_id)
        activities_by_learner[learner_id] += 1
        last_activity[learner_id] = max(last_activity.get(learner_id, row["created_at"]), row["created_at"])

    for row in lesson_progress + practice_progress:
        learner_id = row["learner_id"]
        active_learners.add(learner_id)
        activities_by_learner[learner_id] += 1
        last_activity[learner_id] = max(
            last_activity.get(learner_id, row["activity_date"]), row["activity_date"]
        )

    available_learners = len(learners)
    completed_pairs_count = (
        len(game_pairs) + len(simulation_pairs) + len(challenge_pairs)
        + len(lesson_pairs) + len(practice_pairs)
    )
    possible_completions = available_learners * catalog_size
    completion_rate = round(completed_pairs_count / possible_completions * 100, 1) if possible_completions else None
    average_accuracy = (
        round(answer_totals["correct"] / answer_totals["total"] * 100, 1)
        if answer_totals["total"] else None
    )

    table_rows = []
    for learner in learners:
        stats = answer_stats[learner.pk]
        accuracy = round(stats["correct"] / stats["total"] * 100, 1) if stats["total"] else None
        completed_count = len(completed_by_learner[learner.pk])
        table_rows.append({
            "learner": learner,
            "xp": learner.total_xp,
            "period_xp": xp_rows[learner.pk],
            "activities_count": activities_by_learner[learner.pk],
            "quiz_accuracy": accuracy,
            "quiz_answer_count": stats["total"],
            "learning_progress": round(completed_count / catalog_size * 100) if catalog_size else None,
            "completed_count": completed_count,
            "catalog_size": catalog_size,
            "last_activity": last_activity.get(learner.pk),
        })
    table_rows.sort(key=lambda row: (row["last_activity"] is not None, row["last_activity"] or timezone.make_aware(datetime.min)), reverse=True)

    evidence_rows, _, _ = _topic_insights(quiz_topic_rows)
    lower_topics = [row for row in evidence_rows if row["accuracy"] < 60]
    minimum_answers = getattr(settings, "ADAPTIVE_RECOMMENDATION_MIN_ANSWERS", 5)
    high_performers = [
        row for row in table_rows
        if row["quiz_answer_count"] >= minimum_answers and row["quiz_accuracy"] is not None and row["quiz_accuracy"] >= 80
    ]
    support_learners = [
        row for row in table_rows
        if row["quiz_answer_count"] >= minimum_answers and row["quiz_accuracy"] is not None and row["quiz_accuracy"] < 50
    ]
    recent_inactive = len(learners) - len(active_learners)
    distribution = Counter()
    for row in game_rows:
        distribution["Quizzes" if row["game__category"] == Game.Category.QUIZ else "Other games"] += 1
    distribution["Simulations"] = len(simulation_runs)
    distribution["Collaborative learning"] = len(team_completions) + len(team_events)
    distribution["Lessons"] = sum(
        row["status"] == LearnerContentProgress.Status.COMPLETED for row in lesson_progress
    )
    distribution["Practice activities"] = sum(
        row["status"] == LearnerContentProgress.Status.COMPLETED for row in practice_progress
    )
    activity_rows = game_rows + [
        {"ended_at": row["completed_at"], "kind": "simulation"} for row in simulation_runs
    ] + [
        {"ended_at": row["completed_at"], "kind": "collaboration"} for row in team_completions
    ] + [
        {"ended_at": row["created_at"], "kind": "collaboration"} for row in team_events
    ] + [
        {"ended_at": row["activity_date"], "kind": row["kind"]}
        for row in lesson_progress + practice_progress
    ]
    all_dates = [row.get("ended_at") for row in activity_rows if row.get("ended_at")]
    labels, bucket_labels, granularity = _activity_buckets(all_dates, scope)
    counts_by_bucket = Counter(_bucket_key(value, granularity) for value in all_dates) if granularity else Counter()
    activity_chart = {"labels": bucket_labels, "values": [counts_by_bucket[key] for key in labels]}
    period_xp = sum(xp_rows.values())

    return {
        "filters": form,
        "scope": scope,
        "total_learners": available_learners,
        "active_learners": len(active_learners),
        "inactive_learners": recent_inactive,
        "total_activities": sum(activities_by_learner.values()),
        "average_performance": average_accuracy,
        "completion_rate": completion_rate,
        "participation_rate": round(len(active_learners) / available_learners * 100, 1) if available_learners else None,
        "quiz_answer_count": answer_totals["total"],
        "catalog_size": catalog_size,
        "learners": table_rows,
        "high_performers": high_performers,
        "support_learners": support_learners,
        "low_performing_topics": lower_topics,
        "topic_evidence": evidence_rows,
        "min_answers": minimum_answers,
        "min_topic_answers": getattr(settings, "ADAPTIVE_TOPIC_MIN_ANSWERS", 4),
        "min_topic_questions": getattr(settings, "ADAPTIVE_TOPIC_MIN_DISTINCT_QUESTIONS", 2),
        "activity_distribution": {
            "labels": list(distribution.keys()),
            "values": list(distribution.values()),
        },
        "activity_chart": activity_chart,
        "has_activity_chart_data": bool(all_dates),
        "has_distribution_data": any(distribution.values()),
        "period_xp": period_xp,
        "show_course_filter": False,
        "has_learners": bool(learners),
        "active_definition": "At least one recorded quiz, simulation, lesson, practice, or team challenge activity in the selected period.",
        "performance_definition": "Answer-level accuracy from completed quiz attempts; simulation output scores are excluded.",
    }
