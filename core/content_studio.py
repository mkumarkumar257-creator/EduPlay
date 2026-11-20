"""Ownership, publishing, question-ordering, and reporting helpers for authored content."""

from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.utils.text import slugify

from .models import (
    Challenge,
    ContentView,
    Game,
    GameAttempt,
    LearningLesson,
    LearnerContentProgress,
    PracticeActivity,
    Question,
    TeamChallenge,
)


CONTENT_MODELS = {
    "quiz": Game,
    "lesson": LearningLesson,
    "challenge": Challenge,
    "practice": PracticeActivity,
}
CONTENT_LABELS = {
    "quiz": "Quiz",
    "lesson": "Learning lesson",
    "challenge": "Team challenge",
    "practice": "Practice activity",
}


def content_model_for_type(content_type):
    try:
        return CONTENT_MODELS[content_type]
    except KeyError as error:
        raise ValidationError("Choose a supported content type.") from error


def owned_content(model, user):
    """Return only objects owned by this educator; superusers use Django admin."""
    return model.objects.filter(created_by=user)


def unique_content_slug(model, title, *, max_length, current_pk=None):
    base = slugify(title)[:max_length].strip("-") or "learning-content"
    candidate = base
    suffix = 2
    queryset = model.objects.all()
    if current_pk:
        queryset = queryset.exclude(pk=current_pk)
    while queryset.filter(slug=candidate).exists():
        postfix = f"-{suffix}"
        candidate = f"{base[: max_length - len(postfix)]}{postfix}"
        suffix += 1
    return candidate


def record_content_view(user, item):
    content_type = ContentType.objects.get_for_model(item, for_concrete_model=False)
    return ContentView.objects.create(user=user, content_type=content_type, object_id=item.pk)


def _empty_stats():
    return {"views": 0, "attempts": 0, "completions": 0, "average_score": None, "completion_rate": None}


def _completion_rate(completions, attempts):
    return round(completions / attempts * 100, 1) if attempts else None


def _apply_count_rows(stats, rows, *, count_field="attempts"):
    for row in rows:
        item_stats = stats[row["object_id"]]
        item_stats[count_field] = row["total"]
        item_stats["completions"] = row["completed"]
        item_stats["completion_rate"] = _completion_rate(row["completed"], row["total"])


def _content_stats(items_by_type):
    stats = {content_type: {pk: _empty_stats() for pk in ids} for content_type, ids in items_by_type.items()}
    type_objects = {
        key: ContentType.objects.get_for_model(model, for_concrete_model=False)
        for key, model in CONTENT_MODELS.items()
        if items_by_type.get(key)
    }
    content_types_by_id = {content_type.pk: key for key, content_type in type_objects.items()}
    all_type_ids = [content_type.pk for content_type in type_objects.values()]
    all_object_ids = [pk for ids in items_by_type.values() for pk in ids]
    if all_object_ids:
        for row in ContentView.objects.filter(
            content_type_id__in=all_type_ids, object_id__in=all_object_ids
        ).values("content_type_id", "object_id").annotate(total=Count("pk")):
            stats[content_types_by_id[row["content_type_id"]]][row["object_id"]]["views"] = row["total"]

    game_ids = items_by_type.get("quiz", set())
    if game_ids:
        for row in GameAttempt.objects.filter(game_id__in=game_ids).values("game_id").annotate(
            total=Count("pk"),
            completed=Count("pk", filter=Q(status=GameAttempt.Status.COMPLETED)),
            correct=Sum("correct_answers", filter=Q(status=GameAttempt.Status.COMPLETED)),
            questions=Sum("total_questions", filter=Q(status=GameAttempt.Status.COMPLETED)),
        ):
            target = stats["quiz"][row["game_id"]]
            target["attempts"] = row["total"]
            target["completions"] = row["completed"]
            target["completion_rate"] = _completion_rate(row["completed"], row["total"])
            target["average_score"] = (
                round(row["correct"] / row["questions"] * 100, 1)
                if row["questions"] else None
            )

    challenge_ids = items_by_type.get("challenge", set())
    if challenge_ids:
        rows = TeamChallenge.objects.filter(challenge_id__in=challenge_ids).values("challenge_id").annotate(
            total=Count("pk"), completed=Count("pk", filter=Q(status=TeamChallenge.Status.COMPLETED))
        )
        for row in rows:
            target = stats["challenge"][row["challenge_id"]]
            target["attempts"] = row["total"]
            target["completions"] = row["completed"]
            target["completion_rate"] = _completion_rate(row["completed"], row["total"])

    for content_type in ("lesson", "practice"):
        ids = items_by_type.get(content_type, set())
        if not ids:
            continue
        django_content_type = type_objects[content_type]
        rows = LearnerContentProgress.objects.filter(
            content_type=django_content_type, object_id__in=ids
        ).values("object_id").annotate(
            total=Count("pk"),
            completed=Count("pk", filter=Q(status=LearnerContentProgress.Status.COMPLETED)),
        )
        _apply_count_rows(stats[content_type], rows)
    return stats


def educator_content_library(user, filters):
    querysets = {
        "quiz": owned_content(Game, user).filter(category=Game.Category.QUIZ).select_related("topic"),
        "lesson": owned_content(LearningLesson, user).select_related("topic"),
        "challenge": owned_content(Challenge, user).select_related("topic"),
        "practice": owned_content(PracticeActivity, user).select_related("topic"),
    }
    if filters.get("status"):
        for key in querysets:
            querysets[key] = querysets[key].filter(status=filters["status"])
    if filters.get("subject"):
        for key in querysets:
            querysets[key] = querysets[key].filter(subject=filters["subject"])

    selected_type = filters.get("content_type")
    if selected_type:
        querysets = {selected_type: querysets[selected_type]}

    item_rows = []
    items_by_type = defaultdict(set)
    for content_type, queryset in querysets.items():
        for item in queryset:
            items_by_type[content_type].add(item.pk)
            item_rows.append({
                "type": content_type,
                "type_label": CONTENT_LABELS[content_type],
                "item": item,
            })
    stats = _content_stats(items_by_type)
    for row in item_rows:
        row["stats"] = stats[row["type"]][row["item"].pk]
    item_rows.sort(key=lambda row: row["item"].updated_at, reverse=True)

    subject_values = set()
    all_owned = {
        "quiz": owned_content(Game, user).filter(category=Game.Category.QUIZ),
        "lesson": owned_content(LearningLesson, user),
        "challenge": owned_content(Challenge, user),
        "practice": owned_content(PracticeActivity, user),
    }
    for queryset in all_owned.values():
        subject_values.update(queryset.exclude(subject="").values_list("subject", flat=True).distinct())
    return item_rows, sorted(subject_values, key=str.casefold)


def save_quiz_questions(game, formset):
    """Save additions, edits, deletions, and order changes without unique-order collisions."""
    deleted_forms = list(formset.deleted_forms)
    for form in deleted_forms:
        form.instance.delete()

    kept_forms = [
        form for form in formset.forms
        if form not in deleted_forms and form.cleaned_data
    ]
    kept_forms.sort(key=lambda form: form.cleaned_data["order"])
    existing = list(game.questions.order_by("pk"))
    occupied = {question.order for question in existing}
    final_orders = set(range(1, len(kept_forms) + 1))
    temporary_orders = [
        value for value in range(1, 32768) if value not in occupied and value not in final_orders
    ][:len(existing)]
    if len(temporary_orders) < len(existing):
        raise ValidationError("The question bank is too large to safely reorder. Remove unused questions first.")

    for question, temporary_order in zip(existing, temporary_orders):
        Question.objects.filter(pk=question.pk).update(order=temporary_order)

    for index, form in enumerate(kept_forms, start=1):
        question = form.save(commit=False)
        question.game = game
        question.order = index
        question.save()
        form.save_m2m()
        if game.topic_id:
            question.topics.add(game.topic_id)
    formset.instance = game


def validate_for_publish(content_type, item):
    if content_type == "quiz":
        questions = list(item.questions.filter(is_active=True))
        if not questions:
            raise ValidationError("Add at least one active question before publishing this quiz.")
        for question in questions:
            options = [question.option_a, question.option_b, question.option_c, question.option_d]
            if any(not option.strip() for option in options):
                raise ValidationError("Every active question needs four answer options.")
            if len({option.strip().casefold() for option in options}) != 4:
                raise ValidationError("Each active question must have four distinct answer options.")
    elif content_type == "lesson":
        if not item.body.strip():
            raise ValidationError("Add lesson content before publishing.")
    elif content_type == "practice":
        if not item.instructions.strip():
            raise ValidationError("Add practice instructions before publishing.")
    elif content_type == "challenge":
        if not item.instructions.strip() or not item.completion_criteria.strip():
            raise ValidationError("Add challenge instructions and completion criteria before publishing.")
        item.full_clean()

