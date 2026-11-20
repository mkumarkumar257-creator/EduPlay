"""User account model for learner and educator access."""
import uuid
import secrets
import string

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        LEARNER = "learner", "Learner"
        EDUCATOR = "educator", "Educator"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.LEARNER)
    total_xp = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.get_full_name() or self.username


class ContentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    UNPUBLISHED = "unpublished", "Unpublished"
    ARCHIVED = "archived", "Archived"


class ContentVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"


class ContentDifficulty(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"


class Game(models.Model):
    class Category(models.TextChoices):
        QUIZ = "quiz", "Knowledge Quizzes"
        PUZZLE = "puzzle", "Logic & Puzzles"
        SIMULATION = "simulation", "Simulations"
        CHALLENGE = "challenge", "Challenges"

    class Difficulty(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    Status = ContentStatus
    Visibility = ContentVisibility

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.QUIZ)
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.BEGINNER)
    subject = models.CharField(max_length=100, blank=True)
    topic = models.ForeignKey(
        "LearningTopic", on_delete=models.SET_NULL, null=True, blank=True, related_name="games"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_games"
    )
    status = models.CharField(max_length=12, choices=ContentStatus.choices, default=ContentStatus.DRAFT)
    visibility = models.CharField(
        max_length=10, choices=ContentVisibility.choices, default=ContentVisibility.PUBLIC
    )
    xp_reward = models.PositiveSmallIntegerField(default=50)
    time_limit_seconds = models.PositiveSmallIntegerField(
        default=180, validators=[MinValueValidator(30), MaxValueValidator(900)]
    )
    is_active = models.BooleanField(default=True)
    is_implemented = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "title")
        indexes = [
            models.Index(fields=("created_by", "status"), name="game_owner_status_idx"),
            models.Index(fields=("status", "visibility"), name="game_public_status_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_learner_visible(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.visibility == self.Visibility.PUBLIC
            and self.is_active
            and self.is_implemented
        )


class Question(models.Model):
    class Option(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"
        D = "D", "D"

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    option_a = models.CharField(max_length=255)
    option_b = models.CharField(max_length=255)
    option_c = models.CharField(max_length=255)
    option_d = models.CharField(max_length=255)
    correct_option = models.CharField(max_length=1, choices=Option.choices)
    explanation = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=16, choices=Game.Difficulty.choices, default=Game.Difficulty.BEGINNER
    )
    order = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    topics = models.ManyToManyField("LearningTopic", blank=True, related_name="questions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("order", "id")
        constraints = [
            models.UniqueConstraint(fields=("game", "order"), name="uniq_game_question_order"),
        ]

    def __str__(self):
        return f"{self.game.title}: question {self.order}"

    def get_option_text(self, option_key):
        return {
            self.Option.A: self.option_a,
            self.Option.B: self.option_b,
            self.Option.C: self.option_c,
            self.Option.D: self.option_d,
        }.get(option_key, "")


class GameAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        TIMED_OUT = "timed_out", "Timed out"
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="game_attempts")
    game = models.ForeignKey(Game, on_delete=models.PROTECT, related_name="attempts")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    question_order = models.JSONField(default=list)
    total_questions = models.PositiveSmallIntegerField(default=0)
    correct_answers = models.PositiveSmallIntegerField(default=0)
    xp_awarded = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=("user", "game", "status"), name="attempt_user_game_status_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.game.title} · {self.get_status_display()}"

    @property
    def score_percent(self):
        if not self.total_questions:
            return 0
        return round(self.correct_answers / self.total_questions * 100)


class GameAttemptAnswer(models.Model):
    attempt = models.ForeignKey(GameAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="attempt_answers")
    selected_option = models.CharField(max_length=1, choices=Question.Option.choices)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("answered_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("attempt", "question"), name="uniq_attempt_question_answer"),
        ]

    def __str__(self):
        return f"{self.attempt_id} · {self.question_id} · {self.selected_option}"


class Simulation(models.Model):
    class Category(models.TextChoices):
        SYSTEMS = "systems", "Computer Systems"
        NETWORKING = "networking", "Networking"
        DATABASES = "databases", "Databases"
        SECURITY = "security", "Cybersecurity"

    class Difficulty(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.SYSTEMS)
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.BEGINNER)
    estimated_duration_minutes = models.PositiveSmallIntegerField(default=10)
    xp_reward = models.PositiveSmallIntegerField(default=30)
    icon = models.CharField(max_length=8, default="◉")
    topic = models.ForeignKey(
        "LearningTopic", on_delete=models.SET_NULL, null=True, blank=True, related_name="simulations"
    )
    is_active = models.BooleanField(default=True)
    is_implemented = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "title")

    def __str__(self):
        return self.title


class SimulationAttempt(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="simulation_attempts")
    simulation = models.ForeignKey(Simulation, on_delete=models.PROTECT, related_name="attempts")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    parameters = models.JSONField(default=dict)
    results = models.JSONField(default=dict)
    xp_awarded = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-completed_at",)
        indexes = [
            models.Index(fields=("user", "simulation", "status"), name="sim_user_sim_status_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.simulation.title} · {self.get_status_display()}"


class SimulationCompletion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="simulation_completions")
    simulation = models.ForeignKey(Simulation, on_delete=models.PROTECT, related_name="completions")
    first_attempt = models.ForeignKey(
        SimulationAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="first_completions",
    )
    xp_awarded = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-completed_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "simulation"), name="uniq_user_simulation_completion"),
        ]
        indexes = [
            models.Index(fields=("user", "completed_at"), name="sim_completion_user_date_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.simulation.title} completed"


class LearningTopic(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name


class AuthoredLearningContent(models.Model):
    """Shared metadata for educator-owned lessons and practice activities."""

    class Status(models.TextChoices):
        DRAFT = ContentStatus.DRAFT, "Draft"
        PUBLISHED = ContentStatus.PUBLISHED, "Published"
        UNPUBLISHED = ContentStatus.UNPUBLISHED, "Unpublished"
        ARCHIVED = ContentStatus.ARCHIVED, "Archived"

    class Visibility(models.TextChoices):
        PUBLIC = ContentVisibility.PUBLIC, "Public"
        PRIVATE = ContentVisibility.PRIVATE, "Private"

    class Difficulty(models.TextChoices):
        BEGINNER = ContentDifficulty.BEGINNER, "Beginner"
        INTERMEDIATE = ContentDifficulty.INTERMEDIATE, "Intermediate"
        ADVANCED = ContentDifficulty.ADVANCED, "Advanced"

    title = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField()
    subject = models.CharField(max_length=100, blank=True)
    topic = models.ForeignKey(
        LearningTopic, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_items"
    )
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.BEGINNER)
    estimated_duration_minutes = models.PositiveSmallIntegerField(default=10)
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def is_learner_visible(self):
        return self.status == self.Status.PUBLISHED and self.visibility == self.Visibility.PUBLIC


class LearningLesson(AuthoredLearningContent):
    body = models.TextField()
    learning_objectives = models.TextField(blank=True)

    class Meta:
        ordering = ("-updated_at", "title")
        indexes = [
            models.Index(fields=("created_by", "status"), name="lesson_owner_status_idx"),
            models.Index(fields=("status", "visibility"), name="lesson_public_status_idx"),
        ]

    def __str__(self):
        return self.title


class PracticeActivity(AuthoredLearningContent):
    instructions = models.TextField()
    learning_objectives = models.TextField(blank=True)
    completion_criteria = models.TextField(blank=True)

    class Meta:
        ordering = ("-updated_at", "title")
        indexes = [
            models.Index(fields=("created_by", "status"), name="practice_owner_status_idx"),
            models.Index(fields=("status", "visibility"), name="practice_public_status_idx"),
        ]

    def __str__(self):
        return self.title


class ContentView(models.Model):
    """A learner page view attached to one supported content object."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="content_views")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    viewed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=("content_type", "object_id", "viewed_at"), name="content_view_target_idx"),
        ]
        ordering = ("-viewed_at", "-pk")


class LearnerContentProgress(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="content_progress")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("learner", "content_type", "object_id"), name="uniq_learner_content_progress"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="in_progress", completed_at__isnull=True)
                    | models.Q(status="completed", completed_at__isnull=False)
                ),
                name="content_progress_completion_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=("content_type", "object_id", "status"), name="content_progress_target_idx"),
        ]


class LearningPath(models.Model):
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title


class LearningPathItem(models.Model):
    class ActivityType(models.TextChoices):
        QUIZ = "quiz", "Quiz"
        SIMULATION = "simulation", "Simulation"

    class Difficulty(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="items")
    sequence = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=140)
    topic = models.ForeignKey(LearningTopic, on_delete=models.PROTECT, related_name="path_items")
    activity_type = models.CharField(max_length=16, choices=ActivityType.choices)
    game = models.ForeignKey(Game, on_delete=models.PROTECT, null=True, blank=True, related_name="path_items")
    simulation = models.ForeignKey(
        Simulation, on_delete=models.PROTECT, null=True, blank=True, related_name="path_items"
    )
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.BEGINNER)
    expected_outcome = models.TextField()
    prerequisite = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="unlocked_items"
    )

    class Meta:
        ordering = ("path", "sequence")
        constraints = [
            models.UniqueConstraint(fields=("path", "sequence"), name="uniq_path_item_sequence"),
            models.CheckConstraint(
                condition=(
                    models.Q(activity_type="quiz", game__isnull=False, simulation__isnull=True)
                    | models.Q(activity_type="simulation", game__isnull=True, simulation__isnull=False)
                ),
                name="path_item_has_matching_activity",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.prerequisite_id:
            prerequisite = self.prerequisite
            if prerequisite.path_id != self.path_id:
                raise ValidationError({"prerequisite": "Choose a prerequisite from this learning path."})
            if prerequisite.sequence >= self.sequence:
                raise ValidationError({"prerequisite": "A prerequisite must appear earlier in the learning path."})

    def __str__(self):
        return f"{self.path.title} · {self.sequence}. {self.title}"


class Team(models.Model):
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=300, blank=True)
    avatar = models.CharField(max_length=8, blank=True)
    join_code = models.CharField(max_length=8, unique=True, editable=False)
    leader = models.ForeignKey(User, on_delete=models.PROTECT, related_name="led_teams")
    total_xp = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=("is_active", "-total_xp"), name="team_active_xp_idx")]

    def save(self, *args, **kwargs):
        if not self.join_code:
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            while True:
                candidate = "".join(secrets.choice(alphabet) for _ in range(8))
                if not type(self).objects.filter(join_code=candidate).exists():
                    self.join_code = candidate
                    break
        super().save(*args, **kwargs)

    @property
    def active_member_count(self):
        return self.memberships.filter(left_at__isnull=True).count()

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("joined_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user",), condition=models.Q(left_at__isnull=True),
                name="collab_one_active_team_user",
            ),
            models.UniqueConstraint(
                fields=("team", "user"), condition=models.Q(left_at__isnull=True),
                name="collab_active_member_pair",
            ),
        ]
        indexes = [
            models.Index(fields=("team", "left_at"), name="collab_team_member_idx"),
            models.Index(fields=("user", "left_at"), name="collab_user_member_idx"),
        ]

    @property
    def is_active(self):
        return self.left_at is None

    @property
    def is_leader(self):
        return self.team.leader_id == self.user_id

    def __str__(self):
        return f"{self.user.username} · {self.team.name}"


class Challenge(models.Model):
    class Category(models.TextChoices):
        CODING = "coding", "Coding"
        COMPUTER_SCIENCE = "computer_science", "Computer Science"
        DATABASE = "database", "Database"
        LOGICAL_REASONING = "logical_reasoning", "Logical Reasoning"
        GENERAL_TECHNOLOGY = "general_technology", "General Technology"

    class Difficulty(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class Status(models.TextChoices):
        DRAFT = ContentStatus.DRAFT, "Draft"
        PUBLISHED = ContentStatus.PUBLISHED, "Published"
        UNPUBLISHED = ContentStatus.UNPUBLISHED, "Unpublished"
        ARCHIVED = ContentStatus.ARCHIVED, "Archived"

    Visibility = ContentVisibility

    title = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=24, choices=Category.choices)
    subject = models.CharField(max_length=100, blank=True)
    topic = models.ForeignKey(
        LearningTopic, on_delete=models.SET_NULL, null=True, blank=True, related_name="challenges"
    )
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, default=Difficulty.BEGINNER)
    xp_reward = models.PositiveSmallIntegerField(default=50)
    starts_at = models.DateTimeField()
    deadline = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(
        max_length=10, choices=ContentVisibility.choices, default=ContentVisibility.PUBLIC
    )
    instructions = models.TextField()
    completion_criteria = models.TextField()
    minimum_submission_characters = models.PositiveSmallIntegerField(default=50)
    is_seeded_sample = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_team_challenges"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("starts_at", "title")
        indexes = [
            models.Index(fields=("status", "starts_at"), name="challenge_status_start_idx"),
            models.Index(fields=("status", "deadline"), name="challenge_status_deadline_idx"),
            models.Index(fields=("created_by", "status"), name="challenge_owner_status_idx"),
            models.Index(fields=("status", "visibility"), name="challenge_public_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(deadline__gt=models.F("starts_at")), name="challenge_deadline_after_start"),
            models.CheckConstraint(
                condition=models.Q(minimum_submission_characters__gte=20),
                name="challenge_minimum_submission_size",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.starts_at and self.deadline and self.deadline <= self.starts_at:
            raise ValidationError({"deadline": "The deadline must be after the challenge start date."})
        if self.minimum_submission_characters < 20:
            raise ValidationError({"minimum_submission_characters": "Require at least 20 characters for a submission."})

    @property
    def availability_status(self):
        if self.status == self.Status.DRAFT:
            return "draft"
        if self.status == self.Status.UNPUBLISHED:
            return "unpublished"
        if self.status == self.Status.ARCHIVED:
            return "archived"
        now = timezone.now()
        if now < self.starts_at:
            return "upcoming"
        if now > self.deadline:
            return "closed"
        return "active"

    @property
    def availability_label(self):
        return {
            "draft": "Draft",
            "unpublished": "Unpublished",
            "archived": "Archived",
            "upcoming": "Upcoming",
            "active": "Open",
            "closed": "Closed",
        }[self.availability_status]

    @property
    def is_joinable(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.visibility == self.Visibility.PUBLIC
            and self.availability_status == "active"
        )

    @property
    def is_learner_visible(self):
        return self.status == self.Status.PUBLISHED and self.visibility == self.Visibility.PUBLIC

    def __str__(self):
        return self.title


class TeamChallenge(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="team_challenges")
    challenge = models.ForeignKey(Challenge, on_delete=models.PROTECT, related_name="team_participations")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    submission_text = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="team_challenge_submissions"
    )
    xp_awarded = models.PositiveSmallIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-joined_at",)
        constraints = [
            models.UniqueConstraint(fields=("team", "challenge"), name="uniq_team_challenge_join"),
            models.CheckConstraint(
                condition=(
                    models.Q(status="in_progress", completed_at__isnull=True, xp_awarded=0)
                    | models.Q(
                        status="completed",
                        completed_at__isnull=False,
                        submitted_by__isnull=False,
                    ) & ~models.Q(submission_text="")
                ),
                name="team_challenge_completion_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=("team", "status"), name="team_challenge_state_idx"),
            models.Index(fields=("challenge", "status"), name="challenge_team_state_idx"),
        ]

    @property
    def progress_percent(self):
        if self.status == self.Status.COMPLETED:
            return 100
        return 50 if self.submission_text.strip() else 0

    def __str__(self):
        return f"{self.team.name} · {self.challenge.title}"


class TeamActivity(models.Model):
    class Event(models.TextChoices):
        TEAM_CREATED = "team_created", "Team created"
        MEMBER_JOINED = "member_joined", "Member joined"
        MEMBER_LEFT = "member_left", "Member left"
        MEMBER_REMOVED = "member_removed", "Member removed"
        LEADER_TRANSFERRED = "leader_transferred", "Leadership transferred"
        TEAM_UPDATED = "team_updated", "Team updated"
        TEAM_ARCHIVED = "team_archived", "Team archived"
        CHALLENGE_STARTED = "challenge_started", "Challenge started"
        CHALLENGE_PROGRESS_SAVED = "challenge_progress_saved", "Challenge progress saved"
        CHALLENGE_COMPLETED = "challenge_completed", "Challenge completed"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="team_activity_events"
    )
    team_challenge = models.ForeignKey(
        TeamChallenge, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_events"
    )
    event_type = models.CharField(max_length=24, choices=Event.choices)
    message = models.CharField(max_length=240)
    xp_awarded = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("team", "-created_at"), name="team_activity_recent_idx")]

    def __str__(self):
        return f"{self.team.name} · {self.get_event_type_display()}"

