from datetime import timedelta

from django.db import migrations
from django.utils import timezone


SAMPLE_CHALLENGES = [
    {
        "title": "API Design Code Sprint",
        "slug": "api-design-code-sprint",
        "description": "Sketch a clear, safe request flow for a small course-enrollment API.",
        "category": "coding",
        "difficulty": "intermediate",
        "xp_reward": 80,
        "instructions": (
            "As a team, outline an endpoint for enrolling a learner in a course. Describe the request shape, "
            "validation, response codes, and one way to keep untrusted input safe. You may submit pseudocode, "
            "a short code sample, or a structured design explanation."
        ),
        "completion_criteria": "Submit a team response covering the endpoint, input validation, response behavior, and a security consideration.",
    },
    {
        "title": "Trace the Request",
        "slug": "trace-the-request",
        "description": "Map what happens from a browser action through an application server and back.",
        "category": "computer_science",
        "difficulty": "beginner",
        "xp_reward": 50,
        "instructions": (
            "Choose a familiar web action, such as loading a profile page. Work together to trace the client, "
            "DNS or network, HTTP request, application, data store, and response. Explain one failure point "
            "and how the client or server could respond."
        ),
        "completion_criteria": "Submit a team explanation with at least four request or response stages and one failure case.",
    },
    {
        "title": "Model a Campus Library",
        "slug": "model-a-campus-library",
        "description": "Design a relational data model for books, borrowers, and loans.",
        "category": "database",
        "difficulty": "intermediate",
        "xp_reward": 70,
        "instructions": (
            "Propose the tables and keys needed to track books, authors, borrowers, and loans. Explain how "
            "you would represent a book with multiple authors and how a loan record prevents confusing a "
            "book's inventory with a particular checkout."
        ),
        "completion_criteria": "Submit a team schema outline that names entities, relationships, and primary or foreign keys.",
    },
    {
        "title": "The Three Switches Logic Puzzle",
        "slug": "three-switches-logic-puzzle",
        "description": "Build a repeatable strategy for solving a small information-limited puzzle.",
        "category": "logical_reasoning",
        "difficulty": "beginner",
        "xp_reward": 45,
        "instructions": (
            "A room has three switches outside and one lamp inside. You may enter the room only once. "
            "Develop a strategy that identifies which switch controls the lamp. Explain what observations "
            "your team uses and why the strategy distinguishes all three switches."
        ),
        "completion_criteria": "Submit a step-by-step strategy and explain how each possible observation identifies a switch.",
    },
    {
        "title": "Safer Study Group Setup",
        "slug": "safer-study-group-setup",
        "description": "Create a practical security checklist for a small shared online study space.",
        "category": "general_technology",
        "difficulty": "intermediate",
        "xp_reward": 60,
        "instructions": (
            "Choose a shared study tool or hypothetical web app. Identify three realistic risks involving "
            "accounts, shared files, or links, then propose a practical control for each. Focus on actions "
            "learners can explain and apply."
        ),
        "completion_criteria": "Submit at least three risk-and-control pairs with a short reason for each control.",
    },
]


def seed_challenges(apps, schema_editor):
    Challenge = apps.get_model("core", "Challenge")
    database = schema_editor.connection.alias
    now = timezone.now()
    for item in SAMPLE_CHALLENGES:
        defaults = {
            **item,
            "starts_at": now - timedelta(days=1),
            "deadline": now + timedelta(days=90),
            "status": "published",
            "completion_criteria": item["completion_criteria"],
            "minimum_submission_characters": 50,
            "is_seeded_sample": True,
        }
        Challenge.objects.using(database).get_or_create(slug=item["slug"], defaults=defaults)


class Migration(migrations.Migration):
    dependencies = [("core", "0008_challenge_team_teamchallenge_teamactivity_and_more")]

    operations = [migrations.RunPython(seed_challenges, migrations.RunPython.noop)]
