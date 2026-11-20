"""Validated registration, login, and profile forms."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.forms import inlineformset_factory
from django.utils import timezone
from datetime import timedelta

from .models import (
    Challenge,
    ContentStatus,
    ContentVisibility,
    Game,
    LearningLesson,
    LearningTopic,
    PracticeActivity,
    Question,
    Team,
    User,
)


class SignUpForm(UserCreationForm):
    full_name = forms.CharField(
        label="Full name",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your full name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"})
    )
    role = forms.ChoiceField(
        label="I am joining as",
        choices=User.Role.choices,
        widget=forms.Select(),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "role")
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username", "placeholder": "Choose a username"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["password1"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Create a password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Repeat your password"}
        )

    def clean_full_name(self):
        full_name = " ".join(self.cleaned_data["full_name"].split())
        if not full_name:
            raise forms.ValidationError("Enter your name.")
        name_parts = full_name.split(maxsplit=1)
        self.instance.first_name = name_parts[0]
        self.instance.last_name = name_parts[1] if len(name_parts) > 1 else ""
        return full_name

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("An account with this username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        name_parts = self.cleaned_data["full_name"].split(maxsplit=1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        if commit:
            user.save()
        return user


class EduPlayAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "Username or email"}),
    )
    remember_me = forms.BooleanField(label="Remember me", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["password"].widget.attrs.update(
            {"autocomplete": "current-password", "placeholder": "Your password"}
        )
        self.fields["remember_me"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        identifier = self.cleaned_data.get("username")
        if identifier and "@" in identifier:
            account = User.objects.filter(email__iexact=identifier).only("username").first()
            if account:
                self.cleaned_data["username"] = account.get_username()
        return super().clean()


class ProfileForm(forms.ModelForm):
    full_name = forms.CharField(
        label="Full name",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your full name"}),
    )

    class Meta:
        model = User
        fields = ("email",)
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].initial = self.instance.get_full_name()
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_full_name(self):
        full_name = " ".join(self.cleaned_data["full_name"].split())
        if not full_name:
            raise forms.ValidationError("Enter your name.")
        return full_name

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        name_parts = self.cleaned_data["full_name"].split(maxsplit=1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        if commit:
            user.save()
        return user


TEAM_AVATAR_CHOICES = (
    ("", "Choose an icon"),
    ("⚡", "Lightning"),
    ("🎮", "Gamepad"),
    ("🧠", "Brain"),
    ("🚀", "Rocket"),
    ("🛡️", "Shield"),
    ("⭐", "Star"),
)


class TeamForm(forms.ModelForm):
    avatar = forms.ChoiceField(choices=TEAM_AVATAR_CHOICES, required=False, label="Team icon")

    class Meta:
        model = Team
        fields = ("name", "description", "avatar")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Byte Brigade", "maxlength": 60}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What is your team working toward?"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter a team name.")
        return name


class JoinTeamForm(forms.Form):
    join_code = forms.CharField(
        label="Team joining code",
        max_length=8,
        min_length=8,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "8-character code", "class": "form-control"}),
    )

    def clean_join_code(self):
        return self.cleaned_data["join_code"].replace(" ", "").upper()


class ChallengeSubmissionForm(forms.Form):
    submission_text = forms.CharField(
        label="Team submission",
        max_length=5000,
        widget=forms.Textarea(
            attrs={
                "rows": 7,
                "placeholder": "Describe your team’s solution and how it meets the challenge criteria.",
                "class": "form-control",
            }
        ),
    )

    def __init__(self, *args, minimum_characters=50, **kwargs):
        self.minimum_characters = minimum_characters
        super().__init__(*args, **kwargs)

    def clean_submission_text(self):
        value = " ".join(self.cleaned_data["submission_text"].split())
        if len(value) < self.minimum_characters:
            raise forms.ValidationError(
                f"Add at least {self.minimum_characters} characters so the team has a meaningful submission."
            )
        return value


class AnalyticsFilterForm(forms.Form):
    PERIOD_CHOICES = (
        ("7d", "Last 7 days"),
        ("30d", "Last 30 days"),
        ("90d", "Last 90 days"),
        ("all", "All time"),
    )
    ACTIVITY_CHOICES = (
        ("all", "All activity"),
        ("quiz", "Quizzes"),
        ("game", "Other games"),
        ("simulation", "Simulations"),
        ("collaboration", "Collaborative learning"),
        ("lesson", "Lessons"),
        ("practice", "Practice activities"),
    )

    period = forms.ChoiceField(choices=PERIOD_CHOICES, initial="30d", label="Date range")
    activity_type = forms.ChoiceField(choices=ACTIVITY_CHOICES, initial="all", label="Activity type")
    topic = forms.ModelChoiceField(
        queryset=LearningTopic.objects.none(),
        required=False,
        empty_label="All topics",
        label="Topic",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = LearningTopic.objects.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-select")


class ComputerPerformanceConfigForm(forms.Form):
    cpu_workload = forms.IntegerField(
        label="CPU workload",
        min_value=10,
        max_value=100,
        initial=55,
        widget=forms.NumberInput(attrs={"type": "range", "class": "simulation-range", "step": 1}),
    )
    process_count = forms.IntegerField(
        label="Number of processes",
        min_value=1,
        max_value=20,
        initial=4,
        widget=forms.NumberInput(attrs={"type": "range", "class": "simulation-range", "step": 1}),
    )
    ram_gb = forms.IntegerField(
        label="RAM allocation",
        min_value=1,
        max_value=32,
        initial=8,
        widget=forms.NumberInput(attrs={"type": "range", "class": "simulation-range", "step": 1}),
    )
    background_workload = forms.IntegerField(
        label="Background workload",
        min_value=0,
        max_value=100,
        initial=20,
        widget=forms.NumberInput(attrs={"type": "range", "class": "simulation-range", "step": 1}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bounds = {
            "cpu_workload": (10, 100, "%"),
            "process_count": (1, 20, " processes"),
            "ram_gb": (1, 32, " GB"),
            "background_workload": (0, 100, "%"),
        }
        for name, (minimum, maximum, unit) in bounds.items():
            self.fields[name].widget.attrs.update(
                {"min": minimum, "max": maximum, "data-simulation-input": name, "data-unit": unit}
            )


class EducatorContentChoiceForm(forms.Form):
    CONTENT_TYPES = (
        ("quiz", "Quiz"),
        ("lesson", "Learning lesson"),
        ("challenge", "Team challenge"),
        ("practice", "Practice activity"),
    )
    content_type = forms.ChoiceField(choices=CONTENT_TYPES, label="Content type")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content_type"].widget.attrs["class"] = "form-select"


class EducatorContentFilterForm(forms.Form):
    CONTENT_TYPES = (
        ("", "All content types"),
        ("quiz", "Quizzes"),
        ("lesson", "Lessons"),
        ("challenge", "Challenges"),
        ("practice", "Practice activities"),
    )
    STATUS_CHOICES = (("", "All statuses"),) + tuple(ContentStatus.choices)

    content_type = forms.ChoiceField(choices=CONTENT_TYPES, required=False, label="Content type")
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Status")
    subject = forms.ChoiceField(choices=(("", "All subjects"),), required=False, label="Subject")

    def __init__(self, *args, subjects=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].choices = (("", "All subjects"),) + tuple((name, name) for name in subjects)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select"


class LearnerContentFilterForm(forms.Form):
    CONTENT_TYPES = (
        ("", "All content"),
        ("quiz", "Quizzes"),
        ("lesson", "Lessons"),
        ("challenge", "Challenges"),
        ("practice", "Practice activities"),
    )
    content_type = forms.ChoiceField(choices=CONTENT_TYPES, required=False, label="Content type")
    subject = forms.ChoiceField(choices=(("", "All subjects"),), required=False, label="Subject")
    topic = forms.ModelChoiceField(
        queryset=LearningTopic.objects.none(), required=False, empty_label="All topics", label="Topic"
    )

    def __init__(self, *args, subjects=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].choices = (("", "All subjects"),) + tuple((name, name) for name in subjects)
        self.fields["topic"].queryset = LearningTopic.objects.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select"


class AuthoredContentFormMixin:
    class Meta:
        fields = (
            "title", "description", "subject", "topic", "difficulty",
            "estimated_duration_minutes", "visibility",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "estimated_duration_minutes": forms.NumberInput(attrs={"min": 1, "max": 600}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in ("topic", "difficulty", "visibility"):
            self.fields[field_name].widget.attrs["class"] = "form-select"
        self.fields["topic"].queryset = LearningTopic.objects.filter(is_active=True)


class LearningLessonForm(AuthoredContentFormMixin, forms.ModelForm):
    class Meta(AuthoredContentFormMixin.Meta):
        model = LearningLesson
        fields = AuthoredContentFormMixin.Meta.fields + ("body", "learning_objectives")
        widgets = {
            **AuthoredContentFormMixin.Meta.widgets,
            "body": forms.Textarea(attrs={"rows": 12, "placeholder": "Write the lesson content here."}),
            "learning_objectives": forms.Textarea(attrs={"rows": 4, "placeholder": "One learning objective per line."}),
        }


class PracticeActivityForm(AuthoredContentFormMixin, forms.ModelForm):
    class Meta(AuthoredContentFormMixin.Meta):
        model = PracticeActivity
        fields = AuthoredContentFormMixin.Meta.fields + ("instructions", "learning_objectives", "completion_criteria")
        widgets = {
            **AuthoredContentFormMixin.Meta.widgets,
            "instructions": forms.Textarea(attrs={"rows": 8, "placeholder": "Describe the practice steps."}),
            "learning_objectives": forms.Textarea(attrs={"rows": 3, "placeholder": "What should learners practice?"}),
            "completion_criteria": forms.Textarea(attrs={"rows": 3, "placeholder": "What should the learner do to complete this activity?"}),
        }


class QuizAuthoringForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = (
            "title", "description", "subject", "topic", "difficulty",
            "time_limit_seconds", "xp_reward", "visibility",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "time_limit_seconds": forms.NumberInput(attrs={"min": 30, "max": 900}),
            "xp_reward": forms.NumberInput(attrs={"min": 0, "max": 500}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in ("topic", "difficulty", "visibility"):
            self.fields[field_name].widget.attrs["class"] = "form-select"
        self.fields["topic"].queryset = LearningTopic.objects.filter(is_active=True)


class QuestionAuthoringForm(forms.ModelForm):
    order = forms.IntegerField(min_value=1, max_value=50, initial=1)

    class Meta:
        model = Question
        fields = (
            "order", "prompt", "option_a", "option_b", "option_c", "option_d",
            "correct_option", "explanation", "difficulty", "topics",
        )
        widgets = {
            "order": forms.NumberInput(attrs={"min": 1, "max": 50, "class": "form-control question-order"}),
            "prompt": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2}),
            "topics": forms.SelectMultiple(attrs={"class": "form-select", "size": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The extra inline row starts empty. Model defaults otherwise make its
        # difficulty select appear changed in a POST, causing blank drafts to
        # fail required-field validation before an educator adds a question.
        if not self.instance.pk:
            self.initial["difficulty"] = ""
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["correct_option"].widget.attrs["class"] = "form-select"
        self.fields["difficulty"].widget.attrs["class"] = "form-select"
        self.fields["topics"].queryset = LearningTopic.objects.filter(is_active=True)

    def _get_validation_exclusions(self):
        # Reordering requires temporary swaps (1↔2, etc.). The database
        # uniqueness constraint remains enforced when save_quiz_questions
        # assigns the final compact ordering inside a transaction.
        return super()._get_validation_exclusions() | {"order"}

    def clean(self):
        cleaned = super().clean()
        options = [cleaned.get(f"option_{letter}", "").strip().casefold() for letter in "abcd"]
        present_options = [value for value in options if value]
        if len(present_options) == 4 and len(set(present_options)) != 4:
            raise forms.ValidationError("Each answer option must be distinct.")
        return cleaned


QuizQuestionFormSet = inlineformset_factory(
    Game,
    Question,
    form=QuestionAuthoringForm,
    extra=1,
    can_delete=True,
    max_num=50,
    validate_max=True,
)


class ChallengeAuthoringForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        input_formats=("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    deadline = forms.DateTimeField(
        input_formats=("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Challenge
        fields = (
            "title", "description", "category", "subject", "topic", "difficulty", "xp_reward",
            "starts_at", "deadline", "visibility", "instructions", "completion_criteria",
            "minimum_submission_characters",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "instructions": forms.Textarea(attrs={"rows": 7}),
            "completion_criteria": forms.Textarea(attrs={"rows": 4}),
            "xp_reward": forms.NumberInput(attrs={"min": 0, "max": 500}),
            "minimum_submission_characters": forms.NumberInput(attrs={"min": 20, "max": 5000}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime()
        if not self.instance.pk:
            self.fields["starts_at"].initial = now.strftime("%Y-%m-%dT%H:%M")
            self.fields["deadline"].initial = (now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        for field_name in ("category", "topic", "difficulty", "visibility"):
            self.fields[field_name].widget.attrs["class"] = "form-select"
        self.fields["topic"].queryset = LearningTopic.objects.filter(is_active=True)

