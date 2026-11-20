from django.db import migrations


QUESTIONS = [
    {
        "prompt": "Which set of properties is represented by ACID in database transactions?",
        "option_a": "Atomicity, Consistency, Isolation, Durability",
        "option_b": "Accuracy, Control, Integrity, Distribution",
        "option_c": "Access, Concurrency, Indexing, Data",
        "option_d": "Atomicity, Compilation, Integration, Dependency",
        "correct_option": "A",
        "explanation": "ACID describes transaction guarantees: atomicity, consistency, isolation, and durability.",
    },
    {
        "prompt": "What is the most direct way to prevent SQL injection in a Django query?",
        "option_a": "Remove spaces from the user's input",
        "option_b": "Use parameterized queries or Django ORM filters",
        "option_c": "Store the input in a cookie",
        "option_d": "Convert the input to uppercase",
        "correct_option": "B",
        "explanation": "Parameterized queries keep user input separate from SQL instructions. Django ORM filters handle this safely for normal query construction.",
    },
    {
        "prompt": "What does HTTP status code 404 indicate?",
        "option_a": "The request succeeded",
        "option_b": "The user is not authenticated",
        "option_c": "The requested resource was not found",
        "option_d": "The server encountered an internal error",
        "correct_option": "C",
        "explanation": "HTTP 404 means the server could not find the requested resource.",
    },
    {
        "prompt": "What is the average time complexity of binary search on a sorted list?",
        "option_a": "O(1)",
        "option_b": "O(log n)",
        "option_c": "O(n)",
        "option_d": "O(n²)",
        "correct_option": "B",
        "explanation": "Binary search halves the remaining search interval at each step, giving logarithmic time complexity.",
    },
    {
        "prompt": "What is the main goal of first normal form (1NF) in relational database design?",
        "option_a": "Ensure each field contains a single, atomic value",
        "option_b": "Remove every foreign key",
        "option_c": "Store all data in one table",
        "option_d": "Encrypt every column",
        "correct_option": "A",
        "explanation": "First normal form requires each row-column intersection to contain one atomic value rather than a repeating group.",
    },
    {
        "prompt": "Which HTTP method is intended to replace a resource and is idempotent?",
        "option_a": "POST",
        "option_b": "PATCH",
        "option_c": "PUT",
        "option_d": "CONNECT",
        "correct_option": "C",
        "explanation": "PUT replaces a resource representation and is defined to be idempotent when repeated with the same request.",
    },
    {
        "prompt": "In symmetric encryption, how are data encryption and decryption keys related?",
        "option_a": "They are the same shared secret key",
        "option_b": "They are unrelated public keys",
        "option_c": "The decryption key is always a username",
        "option_d": "No key is used for decryption",
        "correct_option": "A",
        "explanation": "Symmetric encryption uses the same secret key for both encryption and decryption.",
    },
    {
        "prompt": "Which statement best describes Git?",
        "option_a": "A relational database engine",
        "option_b": "A distributed version control system",
        "option_c": "A web application firewall",
        "option_d": "A programming language runtime",
        "correct_option": "B",
        "explanation": "Git is a distributed version control system that records and coordinates changes to files.",
    },
    {
        "prompt": "What is a key responsibility of an operating system's process scheduler?",
        "option_a": "Translate domain names into IP addresses",
        "option_b": "Choose which ready process gets CPU time",
        "option_c": "Compile source code into machine code",
        "option_d": "Validate HTML forms",
        "correct_option": "B",
        "explanation": "The process scheduler selects among ready processes and allocates CPU time according to the scheduling policy.",
    },
    {
        "prompt": "What does Django's CSRF protection help prevent?",
        "option_a": "Cross-site request forgery using a victim's authenticated session",
        "option_b": "All SQL query errors",
        "option_c": "Password guessing",
        "option_d": "A user's browser from loading CSS",
        "correct_option": "A",
        "explanation": "CSRF protection checks a token on unsafe requests so another site cannot silently submit a forged action using the user's session.",
    },
]


def seed_quiz_challenge(apps, schema_editor):
    Game = apps.get_model("core", "Game")
    Question = apps.get_model("core", "Question")
    game, _ = Game.objects.using(schema_editor.connection.alias).get_or_create(
        slug="quiz-challenge",
        defaults={
            "title": "Quiz Challenge",
            "description": "A timed knowledge check covering databases, web development, security, algorithms, and IT fundamentals.",
            "category": "quiz",
            "difficulty": "intermediate",
            "xp_reward": 100,
            "time_limit_seconds": 180,
            "is_active": True,
            "is_implemented": True,
        },
    )
    for order, question in enumerate(QUESTIONS, start=1):
        Question.objects.using(schema_editor.connection.alias).get_or_create(
            game_id=game.pk,
            order=order,
            defaults=question,
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0002_game_user_total_xp_gameattempt_question_and_more")]

    operations = [migrations.RunPython(seed_quiz_challenge, migrations.RunPython.noop)]
