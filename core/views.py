"""Views for public pages and role-aware account workspaces."""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout as auth_logout
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .adaptive_learning import build_adaptive_snapshot
from .analytics import build_educator_analytics, build_learner_analytics
from .content_studio import (
    CONTENT_LABELS,
    CONTENT_MODELS,
    content_model_for_type,
    educator_content_library as build_content_library,
    owned_content,
    record_content_view,
    save_quiz_questions,
    unique_content_slug,
    validate_for_publish,
)
from .forms import (
    ChallengeAuthoringForm,
    ChallengeSubmissionForm,
    ComputerPerformanceConfigForm,
    EducatorContentChoiceForm,
    EducatorContentFilterForm,
    EduPlayAuthenticationForm,
    JoinTeamForm,
    LearnerContentFilterForm,
    LearningLessonForm,
    ProfileForm,
    PracticeActivityForm,
    QuizAuthoringForm,
    QuizQuestionFormSet,
    SignUpForm,
    TeamForm,
)
from .models import (
    ContentStatus,
    ContentView,
    Game,
    GameAttempt,
    GameAttemptAnswer,
    Question,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
    Challenge,
    LearningLesson,
    LearnerContentProgress,
    PracticeActivity,
    Team,
    TeamActivity,
    TeamChallenge,
    TeamMembership,
    User,
)
from .collaboration import (
    CollaborationRuleError,
    active_membership_for,
    complete_challenge,
    create_team,
    join_team,
    leave_team,
    remove_member,
    save_challenge_progress,
    start_challenge,
    transfer_leadership,
    update_team,
)
from .simulation_engine import get_simulation_engine


LEARNER_FEATURES = {
    "my-learning": ("Learning Modules", "Browse published quizzes, lessons, challenges, and practice activities."),
    "game-zone": ("Game Zone", "Quizzes, XP, and friendly challenges are available in the Game Zone."),
    "simulations": ("Simulation Lab", "Explore interactive, guided systems experiments."),
    "learning-paths": ("Adaptive Learning", "Your learning path, topic mastery, and next-step recommendations."),
    "analytics": ("Performance Analytics", "Review your recorded learning activity, quiz evidence, and progress."),
    "achievements": ("Achievements", "Earned badges and milestones will appear here when tracking is available."),
    "leaderboard": ("Leaderboard", "Friendly learner rankings will appear here when learning activity is tracked."),
}

EDUCATOR_FEATURES = {
    "my-courses": ("My Courses", "Course creation and publishing tools are planned for a later phase."),
    "learners": ("Learners", "Learner lists and management tools will appear here when course enrollment is available."),
    "content-library": ("Content Library", "Review and manage your educator-owned learning content."),
    "create-content": ("Create Learning Content", "Create quizzes, lessons, challenges, and practice activities."),
    "analytics": ("Analytics", "Review platform-wide learner participation and performance using recorded activity."),
}

SETTINGS_FEATURE = ("Settings", "Account preferences are not available yet. You can update your name and email from My Profile.")

LEARNER_MODULES = [
    {"title": "Game-Based Learning", "description": "Quizzes, points, and playful practice activities.", "icon": "✦", "available": True, "route": "game_zone", "action": "Open Game Zone"},
    {"title": "Interactive Simulations", "description": "Explore scenarios and virtual experiments.", "icon": "◉", "available": True, "route": "simulation_lab", "action": "Open Simulation Lab"},
    {"title": "Adaptive Learning Paths", "description": "Follow a path shaped around your learning needs.", "icon": "⌁", "available": True, "route": "adaptive_learning", "action": "Open Learning Path"},
    {"title": "Collaborative Learning", "description": "Build a team, take on shared challenges, and earn XP together.", "icon": "◎", "available": True, "route": "collaboration_hub", "action": "Open Collaboration Hub"},
    {"title": "Performance Analytics", "description": "Understand activity, quiz trends, and progress across learning topics.", "icon": "▥", "available": True, "route": "learner_analytics", "action": "View Analytics"},
    {"title": "Learning Modules", "description": "Browse published lessons, quizzes, practice activities, and team challenges.", "icon": "▧", "available": True, "route": "learner_content_library", "action": "Browse Modules"},
]

UPCOMING_GAMES = [
    {"title": "Logic Sprint", "category": "Logic & Puzzles", "description": "Short reasoning challenges for your next study break.", "difficulty": "Beginner", "icon": "⌁"},
    {"title": "IT Escape Room", "category": "Challenges", "description": "Work through a series of connected IT problems.", "difficulty": "Intermediate", "icon": "◇"},
    {"title": "Network Lab", "category": "Simulations", "description": "Explore networking concepts in guided scenarios.", "difficulty": "Intermediate", "icon": "◎"},
]

SIMULATION_COMPARISON_METRICS = (
    ("CPU utilization", "cpu_utilization_percent", "%"),
    ("Memory utilization", "memory_utilization_percent", "%"),
    ("System load index", "system_load", "×"),
    ("Performance score", "performance_score", "/100"),
    ("Estimated response time", "estimated_response_ms", "ms"),
)


def _quiz_game_or_404(slug="quiz-challenge"):
    return get_object_or_404(
        Game,
        slug=slug,
        category=Game.Category.QUIZ,
        status=Game.Status.PUBLISHED,
        visibility=Game.Visibility.PUBLIC,
        is_active=True,
        is_implemented=True,
    )


def _attempt_remaining_seconds(attempt, now=None):
    now = now or timezone.now()
    elapsed_seconds = max(0, int((now - attempt.started_at).total_seconds()))
    return max(0, attempt.game.time_limit_seconds - elapsed_seconds)


def _finish_attempt(attempt, status):
    """Close an attempt once and award only XP earned by a new personal best."""
    with transaction.atomic():
        attempt = GameAttempt.objects.select_for_update().select_related("game").get(pk=attempt.pk)
        if attempt.status != GameAttempt.Status.IN_PROGRESS:
            return attempt

        correct_answers = attempt.answers.filter(is_correct=True).count()
        attempt.correct_answers = correct_answers
        attempt.status = status
        attempt.ended_at = timezone.now()
        attempt.xp_awarded = 0

        if status == GameAttempt.Status.COMPLETED and attempt.total_questions:
            previous_scores = GameAttempt.objects.filter(
                user_id=attempt.user_id,
                game_id=attempt.game_id,
                status=GameAttempt.Status.COMPLETED,
            ).exclude(pk=attempt.pk).values_list("correct_answers", "total_questions")
            current_entitlement = (attempt.game.xp_reward * correct_answers + attempt.total_questions // 2) // attempt.total_questions
            previous_entitlement = max(
                (
                    (attempt.game.xp_reward * correct + total // 2) // total
                    for correct, total in previous_scores
                    if total
                ),
                default=0,
            )
            attempt.xp_awarded = max(0, current_entitlement - previous_entitlement)
            if attempt.xp_awarded:
                User.objects.filter(pk=attempt.user_id).update(total_xp=F("total_xp") + attempt.xp_awarded)

        attempt.save(update_fields=("correct_answers", "status", "ended_at", "xp_awarded"))
        return attempt


def _render_attempt_results(request, attempt):
    request.user.refresh_from_db(fields=("total_xp",))
    return render(
        request,
        "core/quiz_results.html",
        {"attempt": attempt, "score_percent": attempt.score_percent, "answered_count": attempt.answers.count()},
    )


def home(request):
    return render(request, "core/home.html")


def about(request):
    return render(request, "core/about.html")


class RoleBasedLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = EduPlayAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        requested_url = self.get_redirect_url()
        if requested_url:
            return requested_url
        if self.request.user.role == User.Role.EDUCATOR:
            return reverse("educator_dashboard")
        return reverse("learner_dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(None if form.cleaned_data["remember_me"] else 0)
        messages.success(self.request, "You are now signed in.")
        return response


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome to EduPlay as a {user.get_role_display().lower()}.")
        destination = "educator_dashboard" if user.role == User.Role.EDUCATOR else "learner_dashboard"
        return redirect(destination)

    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    if request.user.role == User.Role.EDUCATOR:
        return redirect("educator_dashboard")
    return redirect("learner_dashboard")


def role_required(required_role):
    """Require a signed-in user with the requested EduPlay role."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role != required_role:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


@role_required(User.Role.LEARNER)
def learner_dashboard(request):
    adaptive = build_adaptive_snapshot(request.user)
    dashboard_analytics = build_learner_analytics(
        request.user, {"period": "30d", "activity_type": "all", "topic": ""}
    )
    active_attempt = (
        GameAttempt.objects.filter(
            user=request.user,
            status=GameAttempt.Status.IN_PROGRESS,
            game__status=Game.Status.PUBLISHED,
            game__visibility=Game.Visibility.PUBLIC,
            game__is_active=True,
            game__is_implemented=True,
        )
        .select_related("game")
        .order_by("-started_at")
        .first()
    )
    active_attempt_answered = active_attempt.answers.count() if active_attempt else 0
    return render(
        request,
        "core/dashboard.html",
        {
            "active_nav": "dashboard",
            "modules": LEARNER_MODULES,
            "available_module_count": sum(module.get("available", False) for module in LEARNER_MODULES),
            "recent_activity": dashboard_analytics["recent_activity"],
            "dashboard_analytics": dashboard_analytics,
            "active_attempt": active_attempt,
            "active_attempt_answered": active_attempt_answered,
            "adaptive": adaptive,
        },
    )


@role_required(User.Role.EDUCATOR)
def educator_dashboard(request):
    analytics = build_educator_analytics({"period": "30d", "activity_type": "all", "topic": ""})
    return render(
        request,
        "core/educator_dashboard.html",
        {
            "active_nav": "dashboard",
            "analytics_summary": analytics,
        },
    )


@role_required(User.Role.LEARNER)
def learner_analytics(request):
    return render(
        request,
        "core/learner_analytics.html",
        {**build_learner_analytics(request.user, request.GET), "active_nav": "analytics"},
    )


@role_required(User.Role.EDUCATOR)
def educator_analytics(request):
    analytics = build_educator_analytics(request.GET)
    page_obj = Paginator(analytics["learners"], 25).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "core/educator_analytics.html",
        {
            **analytics,
            "active_nav": "analytics",
            "page_obj": page_obj,
            "query_without_page": query_params.urlencode(),
        },
    )


CONTENT_TYPE_CARDS = (
    ("quiz", "QUIZ", "Create a scored quiz with four-option questions.", "?"),
    ("lesson", "LEARNING LESSON", "Write a structured lesson with objectives and topic tags.", "▤"),
    ("challenge", "TEAM CHALLENGE", "Set up a timed collaborative challenge for learner teams.", "◎"),
    ("practice", "PRACTICE ACTIVITY", "Give learners guided practice with clear completion criteria.", "⌁"),
)


def _owned_content_or_404(content_type, pk, user):
    try:
        model = content_model_for_type(content_type)
    except ValidationError as error:
        raise Http404 from error
    queryset = owned_content(model, user)
    if model is Game:
        queryset = queryset.filter(category=Game.Category.QUIZ)
    return get_object_or_404(queryset, pk=pk)


def _content_form(content_type, data=None, instance=None):
    if content_type == "quiz":
        return QuizAuthoringForm(data, instance=instance)
    if content_type == "lesson":
        return LearningLessonForm(data, instance=instance)
    if content_type == "practice":
        return PracticeActivityForm(data, instance=instance)
    if content_type == "challenge":
        return ChallengeAuthoringForm(data, instance=instance)
    raise Http404


def _content_subjects(user, *, learner_visible=False):
    result = set()
    for model, category in (
        (Game, Game.Category.QUIZ),
        (LearningLesson, None),
        (Challenge, None),
        (PracticeActivity, None),
    ):
        queryset = model.objects.all()
        if learner_visible:
            queryset = queryset.filter(status=ContentStatus.PUBLISHED, visibility="public")
            if model is Game:
                queryset = queryset.filter(category=category, is_active=True, is_implemented=True)
        else:
            queryset = queryset.filter(created_by=user)
            if category:
                queryset = queryset.filter(category=category)
        result.update(queryset.exclude(subject="").values_list("subject", flat=True).distinct())
    return sorted(result, key=str.casefold)


@role_required(User.Role.EDUCATOR)
def educator_content_library(request):
    subjects = _content_subjects(request.user)
    filters = EducatorContentFilterForm(request.GET or None, subjects=subjects)
    cleaned_filters = filters.cleaned_data if filters.is_valid() else {}
    content_items, _ = build_content_library(request.user, cleaned_filters)
    return render(
        request,
        "core/educator_content_library.html",
        {"content_items": content_items, "filters": filters, "active_nav": "content-library"},
    )


@role_required(User.Role.EDUCATOR)
def educator_content_create(request):
    form = EducatorContentChoiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect("educator_content_new", content_type=form.cleaned_data["content_type"])
    return render(
        request,
        "core/educator_content_create.html",
        {"form": form, "content_type_cards": CONTENT_TYPE_CARDS, "active_nav": "create-content"},
    )


@role_required(User.Role.EDUCATOR)
def educator_content_new(request, content_type):
    if content_type not in CONTENT_MODELS:
        raise Http404
    instance = None
    if content_type == "quiz":
        instance = Game(
            category=Game.Category.QUIZ,
            is_active=False,
            is_implemented=True,
            status=Game.Status.DRAFT,
            created_by=request.user,
        )
    form = _content_form(content_type, request.POST or None, instance=instance)
    question_formset = None
    if content_type == "quiz":
        question_formset = QuizQuestionFormSet(
            request.POST or None, instance=instance, prefix="questions"
        )
    valid = form.is_valid()
    if question_formset is not None:
        valid = question_formset.is_valid() and valid
    if request.method == "POST" and valid:
        try:
            with transaction.atomic():
                item = form.save(commit=False)
                item.slug = unique_content_slug(
                    CONTENT_MODELS[content_type], form.cleaned_data["title"],
                    max_length=CONTENT_MODELS[content_type]._meta.get_field("slug").max_length,
                )
                item.created_by = request.user
                item.status = ContentStatus.DRAFT
                if content_type == "quiz":
                    item.category = Game.Category.QUIZ
                    item.is_active = False
                    item.is_implemented = True
                elif content_type == "challenge":
                    item.is_seeded_sample = False
                item.save()
                form.save_m2m()
                if question_formset is not None:
                    question_formset.instance = item
                    save_quiz_questions(item, question_formset)
        except (ValidationError, IntegrityError) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                form.add_error(None, "The content could not be saved. Review its fields and try again.")
        else:
            messages.success(request, f"{CONTENT_LABELS[content_type]} saved as a draft.")
            return redirect("educator_content_edit", content_type=content_type, pk=item.pk)
    return render(
        request,
        "core/educator_content_editor.html",
        {
            "form": form,
            "question_formset": question_formset,
            "content_type": content_type,
            "content_type_label": CONTENT_LABELS[content_type],
            "is_create": True,
            "active_nav": "create-content",
        },
    )


@role_required(User.Role.EDUCATOR)
def educator_content_edit(request, content_type, pk):
    content = _owned_content_or_404(content_type, pk, request.user)
    form = _content_form(content_type, request.POST or None, instance=content)
    question_formset = None
    if content_type == "quiz":
        question_formset = QuizQuestionFormSet(
            request.POST or None, instance=content, prefix="questions"
        )
    valid = form.is_valid()
    if question_formset is not None:
        valid = question_formset.is_valid() and valid
    if request.method == "POST" and valid:
        has_edits = form.has_changed() or bool(question_formset and question_formset.has_changed())
        try:
            with transaction.atomic():
                old_status = content.status
                item = form.save(commit=False)
                if old_status == ContentStatus.PUBLISHED and has_edits:
                    item.status = ContentStatus.DRAFT
                    if content_type == "quiz":
                        item.is_active = False
                if content_type == "quiz":
                    item.is_implemented = True
                item.save()
                form.save_m2m()
                if question_formset is not None:
                    save_quiz_questions(item, question_formset)
        except (ValidationError, IntegrityError, ProtectedError) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            elif isinstance(error, ProtectedError):
                form.add_error(None, "A question used by a learner attempt cannot be deleted.")
            else:
                form.add_error(None, "The content could not be saved. Review its fields and try again.")
        else:
            if old_status == ContentStatus.PUBLISHED and has_edits:
                messages.info(request, "Changes were saved as a draft. Republish when they are ready for learners.")
            else:
                messages.success(request, f"{CONTENT_LABELS[content_type]} changes saved.")
            return redirect("educator_content_edit", content_type=content_type, pk=item.pk)
    return render(
        request,
        "core/educator_content_editor.html",
        {
            "form": form,
            "question_formset": question_formset,
            "content": content,
            "content_type": content_type,
            "content_type_label": CONTENT_LABELS[content_type],
            "is_create": False,
            "active_nav": "content-library",
        },
    )


@role_required(User.Role.EDUCATOR)
def educator_content_preview(request, content_type, pk):
    content = _owned_content_or_404(content_type, pk, request.user)
    questions = list(content.questions.filter(is_active=True).prefetch_related("topics")) if content_type == "quiz" else []
    return render(
        request,
        "core/educator_content_preview.html",
        {
            "content": content,
            "content_type": content_type,
            "content_type_label": CONTENT_LABELS[content_type],
            "questions": questions,
            "active_nav": "content-library",
        },
    )


@role_required(User.Role.EDUCATOR)
@require_POST
def educator_content_action(request, content_type, pk, action):
    if action not in {"publish", "unpublish", "archive", "delete"}:
        raise Http404
    content = _owned_content_or_404(content_type, pk, request.user)
    if action == "publish":
        if content.status not in {ContentStatus.DRAFT, ContentStatus.UNPUBLISHED}:
            messages.error(request, "Only draft or unpublished content can be published.")
        else:
            try:
                validate_for_publish(content_type, content)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
            else:
                content.status = ContentStatus.PUBLISHED
                if content_type == "quiz":
                    content.is_active = True
                    content.is_implemented = True
                content.save()
                messages.success(request, f"{CONTENT_LABELS[content_type]} published.")
    elif action == "unpublish":
        if content.status != ContentStatus.PUBLISHED:
            messages.error(request, "Only published content can be unpublished.")
        else:
            content.status = ContentStatus.UNPUBLISHED
            if content_type == "quiz":
                content.is_active = False
            content.save()
            messages.success(request, f"{CONTENT_LABELS[content_type]} is no longer available to learners.")
    elif action == "archive":
        if content.status == ContentStatus.ARCHIVED:
            messages.info(request, "This content is already archived.")
        else:
            content.status = ContentStatus.ARCHIVED
            if content_type == "quiz":
                content.is_active = False
            content.save()
            messages.success(request, f"{CONTENT_LABELS[content_type]} archived.")
    else:
        content_type_record = ContentType.objects.get_for_model(content, for_concrete_model=False)
        try:
            with transaction.atomic():
                LearnerContentProgress.objects.filter(
                    content_type=content_type_record, object_id=content.pk
                ).delete()
                ContentView.objects.filter(content_type=content_type_record, object_id=content.pk).delete()
                content.delete()
        except ProtectedError:
            messages.error(request, "This content has learner attempt or team history and cannot be deleted. Archive it instead.")
        else:
            messages.success(request, f"{CONTENT_LABELS[content_type]} deleted.")
    return redirect("educator_content_library")


@role_required(User.Role.LEARNER)
def adaptive_learning(request):
    return render(
        request,
        "core/adaptive_learning.html",
        {"adaptive": build_adaptive_snapshot(request.user), "active_nav": "adaptive-learning"},
    )


@role_required(User.Role.LEARNER)
def learner_content_library(request):
    subjects = _content_subjects(request.user, learner_visible=True)
    filters = LearnerContentFilterForm(request.GET or None, subjects=subjects)
    cleaned = filters.cleaned_data if filters.is_valid() else {"content_type": "", "subject": "", "topic": None}
    content_type = cleaned.get("content_type") or ""
    subject = cleaned.get("subject") or ""
    topic = cleaned.get("topic")
    querysets = {
        "quiz": Game.objects.filter(
            category=Game.Category.QUIZ,
            status=Game.Status.PUBLISHED,
            visibility=Game.Visibility.PUBLIC,
            is_active=True,
            is_implemented=True,
        ).select_related("topic").prefetch_related("questions"),
        "lesson": LearningLesson.objects.filter(
            status=LearningLesson.Status.PUBLISHED, visibility=LearningLesson.Visibility.PUBLIC
        ).select_related("topic"),
        "practice": PracticeActivity.objects.filter(
            status=PracticeActivity.Status.PUBLISHED, visibility=PracticeActivity.Visibility.PUBLIC
        ).select_related("topic"),
        "challenge": Challenge.objects.filter(
            status=Challenge.Status.PUBLISHED, visibility=Challenge.Visibility.PUBLIC
        ).select_related("topic"),
    }
    if content_type:
        querysets = {content_type: querysets[content_type]}
    content_items = []
    for item_type, queryset in querysets.items():
        if subject:
            queryset = queryset.filter(subject=subject)
        if topic:
            if item_type == "quiz":
                queryset = queryset.filter(Q(topic=topic) | Q(questions__topics=topic)).distinct()
            else:
                queryset = queryset.filter(topic=topic)
        for item in queryset:
            if item_type in {"lesson", "practice"}:
                duration_label = f"{item.estimated_duration_minutes} min"
            elif item_type == "quiz":
                duration_label = f"{item.time_limit_seconds} sec"
            else:
                duration_label = item.availability_label
            content_items.append({
                "type": item_type,
                "type_label": CONTENT_LABELS[item_type],
                "item": item,
                "duration": duration_label,
            })
    content_items.sort(key=lambda row: row["item"].updated_at, reverse=True)
    return render(
        request,
        "core/learner_content_library.html",
        {"content_items": content_items, "filters": filters, "active_nav": "my-learning"},
    )


def _published_content_or_404(content_type, *, slug=None, pk=None):
    try:
        model = content_model_for_type(content_type)
    except ValidationError as error:
        raise Http404 from error
    queryset = model.objects.filter(status=ContentStatus.PUBLISHED, visibility="public")
    if model is Game:
        queryset = queryset.filter(
            category=Game.Category.QUIZ, is_active=True, is_implemented=True
        )
    lookup = {"slug": slug} if slug else {"pk": pk}
    return get_object_or_404(queryset, **lookup)


@role_required(User.Role.LEARNER)
def content_quiz_instructions(request, slug):
    game = _quiz_game_or_404(slug)
    question_count = game.questions.filter(is_active=True).count()
    if not question_count:
        raise Http404
    record_content_view(request.user, game)
    return render(
        request,
        "core/quiz_instructions.html",
        {"game": game, "question_count": question_count, "active_nav": "my-learning"},
    )


@role_required(User.Role.LEARNER)
def learner_content_detail(request, content_type, slug):
    if content_type not in {"lesson", "practice"}:
        raise Http404
    content = _published_content_or_404(content_type, slug=slug)
    record_content_view(request.user, content)
    content_type_record = ContentType.objects.get_for_model(content, for_concrete_model=False)
    progress, _ = LearnerContentProgress.objects.get_or_create(
        learner=request.user,
        content_type=content_type_record,
        object_id=content.pk,
        defaults={"status": LearnerContentProgress.Status.IN_PROGRESS},
    )
    objectives = content.learning_objectives
    content.objectives_list = [
        line.strip(" \t•-") for line in objectives.splitlines() if line.strip(" \t•-")
    ]
    return render(
        request,
        "core/learner_content_detail.html",
        {"content": content, "content_type": content_type, "progress": progress, "active_nav": "my-learning"},
    )


@role_required(User.Role.LEARNER)
@require_POST
def learner_content_complete(request, content_type, pk):
    if content_type not in {"lesson", "practice"}:
        raise Http404
    content = _published_content_or_404(content_type, pk=pk)
    content_type_record = ContentType.objects.get_for_model(content, for_concrete_model=False)
    progress, _ = LearnerContentProgress.objects.get_or_create(
        learner=request.user,
        content_type=content_type_record,
        object_id=content.pk,
        defaults={"status": LearnerContentProgress.Status.IN_PROGRESS},
    )
    if progress.status != LearnerContentProgress.Status.COMPLETED:
        progress.status = LearnerContentProgress.Status.COMPLETED
        progress.completed_at = timezone.now()
        progress.save(update_fields=("status", "completed_at", "updated_at"))
        messages.success(request, f"{content.title} marked complete.")
    else:
        messages.info(request, "This activity is already recorded as complete.")
    return redirect("learner_content_detail", content_type=content_type, slug=content.slug)


def _learner_progress_rows(user, model):
    content_type_record = ContentType.objects.get_for_model(model, for_concrete_model=False)
    rows = list(LearnerContentProgress.objects.filter(learner=user, content_type=content_type_record))
    content_by_id = {
        content.pk: content
        for content in model.objects.filter(
            pk__in={row.object_id for row in rows}, status=ContentStatus.PUBLISHED, visibility="public"
        )
    }
    for row in rows:
        row.content_object = content_by_id.get(row.object_id)
    return rows


@role_required(User.Role.LEARNER)
def learner_content_progress(request):
    lesson_progress = _learner_progress_rows(request.user, LearningLesson)
    practice_progress = _learner_progress_rows(request.user, PracticeActivity)
    quiz_attempts = list(
        GameAttempt.objects.filter(user=request.user, game__category=Game.Category.QUIZ)
        .select_related("game")[:25]
    )
    challenge_progress = list(
        TeamChallenge.objects.filter(team__memberships__user=request.user)
        .select_related("team", "challenge")
        .distinct()[:25]
    )
    return render(
        request,
        "core/learner_content_progress.html",
        {
            "lesson_progress": lesson_progress,
            "practice_progress": practice_progress,
            "lesson_completed_count": sum(row.status == LearnerContentProgress.Status.COMPLETED for row in lesson_progress),
            "practice_completed_count": sum(row.status == LearnerContentProgress.Status.COMPLETED for row in practice_progress),
            "quiz_attempts": quiz_attempts,
            "challenge_progress": challenge_progress,
            "completed_challenges": [row for row in challenge_progress if row.status == TeamChallenge.Status.COMPLETED],
            "active_nav": "progress",
        },
    )


def _collaboration_hub_context(user, create_form=None, join_form=None):
    membership = active_membership_for(user)
    team = membership.team if membership else None
    active_member_count = 0
    active_team_challenges = []
    completed_team_challenges = []
    team_activity = []
    member_rows = []
    if team:
        member_rows = list(
            team.memberships.filter(left_at__isnull=True).select_related("user").order_by("joined_at", "pk")
        )
        active_member_count = len(member_rows)
        participations = team.team_challenges.select_related("challenge", "submitted_by")
        active_team_challenges = list(participations.filter(status=TeamChallenge.Status.IN_PROGRESS)[:6])
        completed_team_challenges = list(participations.filter(status=TeamChallenge.Status.COMPLETED)[:6])
        team_activity = list(team.activity.select_related("actor", "team_challenge__challenge")[:8])

    leaderboard_query = Team.objects.filter(is_active=True).annotate(
        leaderboard_member_count=Count("memberships", filter=Q(memberships__left_at__isnull=True), distinct=True),
        challenges_completed=Count(
            "team_challenges",
            filter=Q(team_challenges__status=TeamChallenge.Status.COMPLETED),
            distinct=True,
        ),
    ).filter(leaderboard_member_count__gt=0).order_by("-total_xp", "-challenges_completed", "name")
    active_team_count = leaderboard_query.count()
    leaderboard = list(leaderboard_query[:10]) if active_team_count >= 2 else []

    now = timezone.now()
    published = Challenge.objects.filter(
        status=Challenge.Status.PUBLISHED, visibility=Challenge.Visibility.PUBLIC
    )
    available_challenges = list(published.filter(starts_at__lte=now, deadline__gte=now).order_by("deadline", "title"))
    upcoming_challenges = list(published.filter(starts_at__gt=now).order_by("starts_at", "title")[:4])
    return {
        "active_nav": "collaboration",
        "membership": membership,
        "team": team,
        "team_members": member_rows,
        "active_member_count": active_member_count,
        "max_team_size": getattr(settings, "EDUPLAY_MAX_TEAM_SIZE", 6),
        "active_team_challenges": active_team_challenges,
        "completed_team_challenges": completed_team_challenges,
        "team_activity": team_activity,
        "available_challenges": available_challenges,
        "upcoming_challenges": upcoming_challenges,
        "leaderboard": leaderboard,
        "leaderboard_team_count": active_team_count,
        "create_form": create_form or TeamForm(),
        "join_form": join_form or JoinTeamForm(),
    }


@role_required(User.Role.LEARNER)
def collaboration_hub(request):
    return render(request, "core/collaboration_hub.html", _collaboration_hub_context(request.user))


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_create_team(request):
    form = TeamForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "core/collaboration_hub.html",
            _collaboration_hub_context(request.user, create_form=form),
            status=400,
        )
    try:
        team = create_team(request.user, form.cleaned_data)
    except (CollaborationRuleError, IntegrityError) as error:
        messages.error(request, str(error) or "Your team could not be created. Please refresh and try again.")
        return redirect("collaboration_hub")
    messages.success(request, f"{team.name} is ready. Share joining code {team.join_code} with your teammates.")
    return redirect("collaboration_team", team_id=team.pk)


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_join_team(request):
    form = JoinTeamForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "core/collaboration_hub.html",
            _collaboration_hub_context(request.user, join_form=form),
            status=400,
        )
    try:
        membership, created = join_team(request.user, form.cleaned_data["join_code"])
    except (CollaborationRuleError, IntegrityError) as error:
        messages.error(request, str(error) or "That team code could not be used.")
        return redirect("collaboration_hub")
    if created:
        messages.success(request, f"You joined {membership.team.name}.")
    else:
        messages.info(request, f"You are already a member of {membership.team.name}.")
    return redirect("collaboration_team", team_id=membership.team_id)


def _team_detail_context(team, user, team_form=None):
    member_rows = list(
        team.memberships.filter(left_at__isnull=True).select_related("user").order_by("joined_at", "pk")
    )
    current_membership = next((row for row in member_rows if row.user_id == user.pk), None)
    team_challenges = list(team.team_challenges.select_related("challenge", "submitted_by")[:12])
    challenges_completed_count = team.team_challenges.filter(status=TeamChallenge.Status.COMPLETED).count()
    return {
        "active_nav": "collaboration",
        "team": team,
        "team_members": member_rows,
        "active_member_count": len(member_rows),
        "max_team_size": getattr(settings, "EDUPLAY_MAX_TEAM_SIZE", 6),
        "team_challenges": team_challenges,
        "challenges_joined_count": team.team_challenges.count(),
        "challenges_completed_count": challenges_completed_count,
        "team_activity": list(team.activity.select_related("actor", "team_challenge__challenge")[:12]),
        "is_team_leader": bool(current_membership and team.leader_id == user.pk),
        "can_archive_team": bool(current_membership and team.leader_id == user.pk and len(member_rows) == 1),
        "team_form": team_form or TeamForm(instance=team),
    }


@role_required(User.Role.LEARNER)
def collaboration_team(request, team_id):
    team = get_object_or_404(
        Team.objects.filter(
            is_active=True,
            memberships__user=request.user,
            memberships__left_at__isnull=True,
        ).distinct(),
        pk=team_id,
    )
    return render(request, "core/team_detail.html", _team_detail_context(team, request.user))


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_update_team(request, team_id):
    team = get_object_or_404(
        Team.objects.filter(is_active=True, memberships__user=request.user, memberships__left_at__isnull=True).distinct(),
        pk=team_id,
    )
    form = TeamForm(request.POST, instance=team)
    if not form.is_valid():
        return render(
            request,
            "core/team_detail.html",
            _team_detail_context(team, request.user, team_form=form),
            status=400,
        )
    try:
        update_team(request.user, team.pk, form.cleaned_data)
    except CollaborationRuleError as error:
        messages.error(request, str(error))
        return redirect("collaboration_team", team_id=team.pk)
    messages.success(request, "Team details updated.")
    return redirect("collaboration_team", team_id=team.pk)


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_leave_team(request, team_id):
    try:
        team = leave_team(request.user, team_id)
    except CollaborationRuleError as error:
        messages.error(request, str(error))
        return redirect("collaboration_hub")
    if team.is_active:
        messages.success(request, f"You left {team.name}.")
    else:
        messages.success(request, f"{team.name} was archived because its only member left.")
    return redirect("collaboration_hub")


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_transfer_leadership(request, team_id, member_id):
    try:
        transfer_leadership(request.user, team_id, member_id)
    except CollaborationRuleError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Team leadership transferred.")
    return redirect("collaboration_team", team_id=team_id)


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_remove_member(request, team_id, member_id):
    try:
        remove_member(request.user, team_id, member_id)
    except CollaborationRuleError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The learner was removed from your team.")
    return redirect("collaboration_team", team_id=team_id)


@role_required(User.Role.LEARNER)
def collaboration_challenge(request, slug):
    challenge = get_object_or_404(
        Challenge,
        slug=slug,
        status=Challenge.Status.PUBLISHED,
        visibility=Challenge.Visibility.PUBLIC,
    )
    record_content_view(request.user, challenge)
    membership = active_membership_for(request.user)
    participation = None
    if membership:
        participation = TeamChallenge.objects.filter(team=membership.team, challenge=challenge).first()
    submission_form = ChallengeSubmissionForm(
        minimum_characters=challenge.minimum_submission_characters,
        initial={"submission_text": participation.submission_text} if participation else None,
    )
    return render(
        request,
        "core/collaboration_challenge.html",
        {
            "active_nav": "collaboration",
            "challenge": challenge,
            "membership": membership,
            "participation": participation,
            "submission_form": submission_form,
        },
    )


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_start_challenge(request, slug):
    challenge = get_object_or_404(
        Challenge,
        slug=slug,
        status=Challenge.Status.PUBLISHED,
        visibility=Challenge.Visibility.PUBLIC,
    )
    try:
        participation, created = start_challenge(request.user, challenge.pk)
    except CollaborationRuleError as error:
        messages.error(request, str(error))
    else:
        if created:
            messages.success(request, f"{participation.team.name} started {challenge.title}.")
        else:
            messages.info(request, "Your team has already started this challenge.")
    return redirect("collaboration_challenge", slug=slug)


@role_required(User.Role.LEARNER)
@require_POST
def collaboration_submit_challenge(request, slug, participation_id):
    challenge = get_object_or_404(
        Challenge,
        slug=slug,
        status=Challenge.Status.PUBLISHED,
        visibility=Challenge.Visibility.PUBLIC,
    )
    membership = active_membership_for(request.user)
    if membership is None:
        messages.error(request, "An active team membership is required to submit this challenge.")
        return redirect("collaboration_challenge", slug=slug)
    participation = get_object_or_404(
        TeamChallenge.objects.select_related("team", "challenge"),
        pk=participation_id,
        team=membership.team,
        challenge=challenge,
    )
    action = request.POST.get("action", "complete")
    minimum_characters = 20 if action == "save" else challenge.minimum_submission_characters
    form = ChallengeSubmissionForm(request.POST, minimum_characters=minimum_characters)
    if not form.is_valid():
        return render(
            request,
            "core/collaboration_challenge.html",
            {
                "active_nav": "collaboration",
                "challenge": challenge,
                "membership": membership,
                "participation": participation,
                "submission_form": form,
            },
            status=400,
        )
    try:
        if action == "save":
            participation = save_challenge_progress(
                request.user, participation.pk, form.cleaned_data["submission_text"]
            )
            messages.success(request, "Team progress saved. Submit a final response when you are ready to complete the challenge.")
            return redirect("collaboration_challenge", slug=slug)
        if action != "complete":
            raise CollaborationRuleError("Choose whether to save progress or submit the completed challenge.")
        participation = complete_challenge(request.user, participation.pk, form.cleaned_data["submission_text"])
    except CollaborationRuleError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            f"Challenge completed. Your team earned {participation.xp_awarded} team XP, and active members received learner XP.",
        )
    return redirect("collaboration_challenge", slug=slug)


@role_required(User.Role.LEARNER)
def game_zone(request):
    games = []
    for game in Game.objects.filter(
        category=Game.Category.QUIZ,
        status=Game.Status.PUBLISHED,
        visibility=Game.Visibility.PUBLIC,
        is_active=True,
        is_implemented=True,
    ).prefetch_related("questions"):
        active_question_count = sum(question.is_active for question in game.questions.all())
        playable = active_question_count > 0
        games.append({"game": game, "question_count": active_question_count, "playable": playable})

    return render(
        request,
        "core/game_zone.html",
        {
            "active_nav": "game-zone",
            "games": games,
            "upcoming_games": UPCOMING_GAMES,
            "categories": Game.Category.choices,
        },
    )


@role_required(User.Role.LEARNER)
def simulation_lab(request):
    simulations = list(Simulation.objects.filter(is_active=True))
    simulation_ids = [simulation.pk for simulation in simulations]
    completed_ids = set(
        SimulationCompletion.objects.filter(
            user=request.user, simulation_id__in=simulation_ids
        ).values_list("simulation_id", flat=True)
    )
    attempt_counts = {
        row["simulation_id"]: row["run_count"]
        for row in SimulationAttempt.objects.filter(
            user=request.user, simulation_id__in=simulation_ids
        ).values("simulation_id").annotate(run_count=Count("pk"))
    }
    cards = [
        {
            "simulation": simulation,
            "playable": simulation.is_implemented and get_simulation_engine(simulation.slug) is not None,
            "completed": simulation.pk in completed_ids,
            "attempt_count": attempt_counts.get(simulation.pk, 0),
        }
        for simulation in simulations
    ]
    return render(
        request,
        "core/simulation_lab.html",
        {
            "cards": cards,
            "categories": Simulation.Category.choices,
            "completed_count": len(completed_ids),
            "active_nav": "simulation-lab",
        },
    )


def _simulation_or_404(slug):
    simulation = get_object_or_404(Simulation, slug=slug, is_active=True, is_implemented=True)
    if get_simulation_engine(simulation.slug) is None:
        raise Http404
    return simulation


@role_required(User.Role.LEARNER)
def simulation_detail(request, slug):
    simulation = _simulation_or_404(slug)
    history = list(
        SimulationAttempt.objects.filter(user=request.user, simulation=simulation)[:8]
    )
    run_attempt = None
    run_token = request.GET.get("run")
    if run_token:
        try:
            run_id = int(run_token)
        except (TypeError, ValueError):
            raise Http404
        run_attempt = get_object_or_404(
            SimulationAttempt, pk=run_id, user=request.user, simulation=simulation
        )

    compare_attempt = None
    compare_token = request.GET.get("compare")
    if compare_token:
        try:
            compare_id = int(compare_token)
        except (TypeError, ValueError):
            raise Http404
        compare_attempt = get_object_or_404(
            SimulationAttempt, pk=compare_id, user=request.user, simulation=simulation
        )

    comparison_rows = []
    if run_attempt and compare_attempt and run_attempt.pk != compare_attempt.pk:
        for label, key, unit in SIMULATION_COMPARISON_METRICS:
            current = run_attempt.results.get(key)
            previous = compare_attempt.results.get(key)
            comparison_rows.append(
                {
                    "label": label,
                    "current": current,
                    "previous": previous,
                    "delta": round(current - previous, 2) if current is not None and previous is not None else None,
                    "unit": unit,
                }
            )

    if run_attempt:
        form = ComputerPerformanceConfigForm(initial=run_attempt.parameters)
    else:
        form = ComputerPerformanceConfigForm()
    return render(
        request,
        "core/simulation_detail.html",
        {
            "simulation": simulation,
            "form": form,
            "run_attempt": run_attempt,
            "history": history,
            "compare_attempt": compare_attempt,
            "comparison_rows": comparison_rows,
            "active_nav": "simulation-lab",
        },
    )


@role_required(User.Role.LEARNER)
@require_POST
def run_simulation(request, slug):
    simulation = _simulation_or_404(slug)
    form = ComputerPerformanceConfigForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "core/simulation_detail.html",
            {
                "simulation": simulation,
                "form": form,
                "history": SimulationAttempt.objects.filter(
                    user=request.user, simulation=simulation
                )[:8],
                "active_nav": "simulation-lab",
            },
        )

    engine = get_simulation_engine(simulation.slug)
    parameters = form.cleaned_data
    results = engine(parameters)
    xp_awarded = 0
    with transaction.atomic():
        attempt = SimulationAttempt.objects.create(
            user=request.user,
            simulation=simulation,
            parameters=parameters,
            results=results,
        )
        try:
            # The unique completion row makes the configured XP reward a
            # one-time grant, even if the learner repeats the experiment.
            with transaction.atomic():
                SimulationCompletion.objects.create(
                    user=request.user,
                    simulation=simulation,
                    first_attempt=attempt,
                    xp_awarded=simulation.xp_reward,
                )
            xp_awarded = simulation.xp_reward
            User.objects.filter(pk=request.user.pk).update(total_xp=F("total_xp") + xp_awarded)
        except IntegrityError:
            pass

        attempt.xp_awarded = xp_awarded
        attempt.save(update_fields=("xp_awarded",))

    if xp_awarded:
        messages.success(request, f"Experiment complete. You earned {xp_awarded} XP.")
    else:
        messages.info(request, "Experiment saved. Your first-completion XP was already earned.")
    return redirect(f"{reverse('simulation_detail', kwargs={'slug': simulation.slug})}?run={attempt.pk}")


@role_required(User.Role.LEARNER)
def quiz_challenge(request):
    game = _quiz_game_or_404()
    question_count = game.questions.filter(is_active=True).count()
    if not question_count:
        raise Http404
    record_content_view(request.user, game)
    return render(
        request,
        "core/quiz_instructions.html",
        {"game": game, "question_count": question_count, "active_nav": "game-zone"},
    )


@role_required(User.Role.LEARNER)
@require_POST
def start_quiz(request, slug=None):
    game = _quiz_game_or_404(slug or "quiz-challenge")
    question_ids = list(game.questions.filter(is_active=True).order_by("order", "pk").values_list("pk", flat=True))
    if not question_ids:
        messages.error(request, "This quiz is not ready yet. Please try again later.")
        return redirect("game_zone")

    now = timezone.now()
    GameAttempt.objects.filter(
        user=request.user,
        game=game,
        status=GameAttempt.Status.IN_PROGRESS,
    ).update(status=GameAttempt.Status.ABANDONED, ended_at=now)
    attempt = GameAttempt.objects.create(
        user=request.user,
        game=game,
        question_order=question_ids,
        total_questions=len(question_ids),
        started_at=now,
    )
    return redirect("quiz_attempt", attempt_id=attempt.pk)


@role_required(User.Role.LEARNER)
def quiz_attempt(request, attempt_id):
    attempt = get_object_or_404(
        GameAttempt.objects.select_related("game"), pk=attempt_id, user=request.user
    )
    if not attempt.game.is_learner_visible:
        raise Http404
    answered_count = attempt.answers.count()
    if attempt.status == GameAttempt.Status.IN_PROGRESS:
        if answered_count >= attempt.total_questions:
            # The final answer was accepted before the deadline; reading its
            # feedback must not turn a completed quiz into a timeout.
            attempt = _finish_attempt(attempt, GameAttempt.Status.COMPLETED)
        elif _attempt_remaining_seconds(attempt) == 0:
            attempt = _finish_attempt(attempt, GameAttempt.Status.TIMED_OUT)
            messages.warning(request, "Challenge ended. Time is up; your answers have been saved and the quiz has ended.")

    show_final_feedback = (
        attempt.status == GameAttempt.Status.COMPLETED
        and answered_count >= attempt.total_questions
        and request.GET.get("feedback") == "1"
    )
    if request.GET.get("feedback") == "1" and answered_count and (
        attempt.status == GameAttempt.Status.IN_PROGRESS or show_final_feedback
    ):
        answer = attempt.answers.select_related("question").order_by("-answered_at", "-pk").first()
        feedback = {
            "answer": answer,
            "question_number": answered_count,
            "selected_text": answer.question.get_option_text(answer.selected_option),
            "correct_text": answer.question.get_option_text(answer.question.correct_option),
            "correct_so_far": attempt.answers.filter(is_correct=True).count(),
        }
        return render(
            request,
            "core/quiz_feedback.html",
            {
                "attempt": attempt,
                "feedback": feedback,
                  "time_remaining": (
                      _attempt_remaining_seconds(attempt)
                      if attempt.status == GameAttempt.Status.IN_PROGRESS
                      else None
                  ),
                "is_last_question": answered_count >= attempt.total_questions,
                "progress_percent": round(answered_count / attempt.total_questions * 100),
                "active_nav": "game-zone",
            },
        )

    if attempt.status != GameAttempt.Status.IN_PROGRESS:
        return _render_attempt_results(request, attempt)

    if answered_count >= attempt.total_questions:
        attempt = _finish_attempt(attempt, GameAttempt.Status.COMPLETED)
        return _render_attempt_results(request, attempt)

    question_id = attempt.question_order[answered_count]
    question = get_object_or_404(Question, pk=question_id, game_id=attempt.game_id)
    options = [
        (Question.Option.A, question.option_a),
        (Question.Option.B, question.option_b),
        (Question.Option.C, question.option_c),
        (Question.Option.D, question.option_d),
    ]
    return render(
        request,
        "core/quiz_play.html",
        {
            "attempt": attempt,
            "question": question,
            "options": options,
            "question_number": answered_count + 1,
            "answered_count": answered_count,
            "correct_so_far": attempt.answers.filter(is_correct=True).count(),
            "progress_percent": round(answered_count / attempt.total_questions * 100),
            "time_remaining": _attempt_remaining_seconds(attempt),
            "active_nav": "game-zone",
        },
    )


@role_required(User.Role.LEARNER)
@require_POST
def submit_quiz_answer(request, attempt_id):
    attempt = get_object_or_404(
        GameAttempt.objects.select_related("game"), pk=attempt_id, user=request.user
    )
    if not attempt.game.is_learner_visible:
        raise Http404
    if attempt.status != GameAttempt.Status.IN_PROGRESS:
        return redirect("quiz_attempt", attempt_id=attempt.pk)

    if _attempt_remaining_seconds(attempt) == 0:
        _finish_attempt(attempt, GameAttempt.Status.TIMED_OUT)
        messages.warning(request, "Challenge ended. Time is up; your answers have been saved and the quiz has ended.")
        return redirect("quiz_attempt", attempt_id=attempt.pk)

    answered_count = attempt.answers.count()
    if answered_count >= attempt.total_questions:
        return redirect("quiz_attempt", attempt_id=attempt.pk)

    submitted_question_id = request.POST.get("question_id", "")
    current_question_id = attempt.question_order[answered_count]
    if str(current_question_id) != submitted_question_id:
        already_answered = attempt.answers.filter(question_id=submitted_question_id).exists()
        if already_answered:
            return redirect(f"{reverse('quiz_attempt', kwargs={'attempt_id': attempt.pk})}?feedback=1")
        messages.error(request, "That question is no longer current. Please continue with the quiz.")
        return redirect("quiz_attempt", attempt_id=attempt.pk)

    selected_option = request.POST.get("option", "")
    if selected_option not in Question.Option.values:
        messages.error(request, "Choose one of the four answer options.")
        return redirect("quiz_attempt", attempt_id=attempt.pk)

    question = get_object_or_404(Question, pk=current_question_id, game_id=attempt.game_id)
    try:
        with transaction.atomic():
            GameAttemptAnswer.objects.create(
                attempt=attempt,
                question=question,
                selected_option=selected_option,
                is_correct=selected_option == question.correct_option,
            )
    except IntegrityError:
        # A repeated or concurrent submission cannot create a second answer.
        pass

    return redirect(f"{reverse('quiz_attempt', kwargs={'attempt_id': attempt.pk})}?feedback=1")


@login_required
def workspace_placeholder(request, feature):
    if feature == "analytics":
        return redirect("educator_analytics" if request.user.role == User.Role.EDUCATOR else "learner_analytics")
    if feature == "my-learning":
        if request.user.role != User.Role.LEARNER:
            raise PermissionDenied
        return redirect("learner_content_library")
    if feature == "content-library":
        if request.user.role != User.Role.EDUCATOR:
            raise PermissionDenied
        return redirect("educator_content_library")
    if feature == "create-content":
        if request.user.role != User.Role.EDUCATOR:
            raise PermissionDenied
        return redirect("educator_content_create")
    if feature == "game-zone":
        if request.user.role != User.Role.LEARNER:
            raise PermissionDenied
        return redirect("game_zone")
    if feature == "simulations":
        if request.user.role != User.Role.LEARNER:
            raise PermissionDenied
        return redirect("simulation_lab")
    if feature == "learning-paths":
        if request.user.role != User.Role.LEARNER:
            raise PermissionDenied
        return redirect("adaptive_learning")
    if feature == "settings":
        title, description = SETTINGS_FEATURE
    elif request.user.role == User.Role.LEARNER and feature in LEARNER_FEATURES:
        title, description = LEARNER_FEATURES[feature]
    elif request.user.role == User.Role.EDUCATOR and feature in EDUCATOR_FEATURES:
        title, description = EDUCATOR_FEATURES[feature]
    elif feature in LEARNER_FEATURES or feature in EDUCATOR_FEATURES:
        raise PermissionDenied
    else:
        raise Http404

    return render(
        request,
        "core/coming_soon.html",
        {"active_nav": feature, "feature_title": title, "feature_description": description},
    )


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("profile")
    return render(request, "core/profile.html", {"form": form, "active_nav": "profile"})


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("home")
