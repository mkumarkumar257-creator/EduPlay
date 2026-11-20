from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Game,
    GameAttempt,
    GameAttemptAnswer,
    ContentView,
    LearningPath,
    LearningLesson,
    LearnerContentProgress,
    LearningPathItem,
    LearningTopic,
    PracticeActivity,
    Challenge,
    Question,
    Simulation,
    SimulationAttempt,
    SimulationCompletion,
    Team,
    TeamActivity,
    TeamChallenge,
    TeamMembership,
    User,
)


@admin.register(User)
class EduPlayUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (("EduPlay access", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Profile", {"fields": ("first_name", "last_name", "email", "role")}),)


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    fields = ("order", "prompt", "option_a", "option_b", "option_c", "option_d", "correct_option", "explanation", "difficulty", "topics", "is_active")


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "created_by", "status", "visibility", "difficulty", "xp_reward", "is_active", "is_implemented")
    list_filter = ("category", "status", "visibility", "difficulty", "is_active", "is_implemented")
    search_fields = ("title", "description", "subject", "created_by__username")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (QuestionInline,)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("game", "order", "prompt", "correct_option", "difficulty", "is_active")
    list_filter = ("game", "topics", "difficulty", "is_active")
    search_fields = ("prompt", "explanation", "topics__name")
    ordering = ("game", "order")


class GameAttemptAnswerInline(admin.TabularInline):
    model = GameAttemptAnswer
    extra = 0
    can_delete = False
    readonly_fields = ("question", "selected_option", "is_correct", "answered_at")


@admin.register(GameAttempt)
class GameAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "game", "status", "correct_answers", "total_questions", "xp_awarded", "started_at")
    list_filter = ("status", "game")
    search_fields = ("user__username", "user__email", "game__title")
    readonly_fields = (
        "user", "game", "status", "question_order", "total_questions", "correct_answers",
        "xp_awarded", "started_at", "ended_at",
    )
    inlines = (GameAttemptAnswerInline,)
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = (
        "title", "category", "topic", "difficulty", "estimated_duration_minutes", "xp_reward", "is_active", "is_implemented"
    )
    list_filter = ("category", "difficulty", "is_active", "is_implemented")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(SimulationAttempt)
class SimulationAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "simulation", "status", "xp_awarded", "completed_at")
    list_filter = ("simulation", "status")
    search_fields = ("user__username", "user__email", "simulation__title")
    readonly_fields = ("user", "simulation", "status", "parameters", "results", "xp_awarded", "completed_at")

    def has_add_permission(self, request):
        return False


@admin.register(SimulationCompletion)
class SimulationCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "simulation", "xp_awarded", "completed_at")
    search_fields = ("user__username", "user__email", "simulation__title")
    readonly_fields = ("user", "simulation", "first_attempt", "xp_awarded", "completed_at")

    def has_add_permission(self, request):
        return False


@admin.register(LearningTopic)
class LearningTopicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(LearningLesson)
class LearningLessonAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "topic", "created_by", "status", "visibility", "updated_at")
    list_filter = ("status", "visibility", "difficulty", "subject")
    search_fields = ("title", "description", "body", "created_by__username")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(PracticeActivity)
class PracticeActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "topic", "created_by", "status", "visibility", "updated_at")
    list_filter = ("status", "visibility", "difficulty", "subject")
    search_fields = ("title", "description", "instructions", "created_by__username")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(LearnerContentProgress)
class LearnerContentProgressAdmin(admin.ModelAdmin):
    list_display = ("learner", "content_type", "object_id", "status", "started_at", "completed_at")
    list_filter = ("status", "content_type", "started_at")
    search_fields = ("learner__username", "learner__email")
    readonly_fields = tuple(field.name for field in LearnerContentProgress._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(ContentView)
class ContentViewAdmin(admin.ModelAdmin):
    list_display = ("user", "content_type", "object_id", "viewed_at")
    list_filter = ("content_type", "viewed_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = tuple(field.name for field in ContentView._meta.fields)

    def has_add_permission(self, request):
        return False


class LearningPathItemInline(admin.TabularInline):
    model = LearningPathItem
    extra = 0
    fields = ("sequence", "title", "topic", "activity_type", "game", "simulation", "difficulty", "prerequisite", "expected_outcome")


@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_default", "is_active")
    list_filter = ("is_active", "is_default")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (LearningPathItemInline,)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "leader", "join_code", "total_xp", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "leader__username", "leader__email", "join_code")
    readonly_fields = ("join_code", "leader", "total_xp", "is_active", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("team", "user", "joined_at", "left_at")
    list_filter = ("team", "joined_at", "left_at")
    search_fields = ("team__name", "user__username", "user__email")
    readonly_fields = ("team", "user", "joined_at", "left_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "difficulty", "status", "starts_at", "deadline", "xp_reward", "is_seeded_sample")
    list_filter = ("category", "difficulty", "status", "is_seeded_sample")
    search_fields = ("title", "description", "instructions")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeamChallenge)
class TeamChallengeAdmin(admin.ModelAdmin):
    list_display = ("team", "challenge", "status", "xp_awarded", "joined_at", "completed_at")
    list_filter = ("status", "challenge", "joined_at")
    search_fields = ("team__name", "challenge__title", "submitted_by__username")
    readonly_fields = tuple(field.name for field in TeamChallenge._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeamActivity)
class TeamActivityAdmin(admin.ModelAdmin):
    list_display = ("team", "event_type", "actor", "xp_awarded", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("team__name", "actor__username", "message")
    readonly_fields = tuple(field.name for field in TeamActivity._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

