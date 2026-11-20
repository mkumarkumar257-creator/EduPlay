from django.db import migrations


TOPICS = [
    ("it-fundamentals", "Core IT Fundamentals", "Broad baseline across the existing computer science and IT quiz bank.", 1),
    ("databases", "Databases & Data Modeling", "Transactions, relational design, and data integrity.", 2),
    ("web-http", "Web & HTTP", "HTTP behavior, web protocols, and application request handling.", 3),
    ("algorithms", "Algorithms & Data Structures", "Algorithmic reasoning and complexity analysis.", 4),
    ("security", "Security & Cryptography", "Application security, threat prevention, and cryptographic concepts.", 5),
    ("operating-systems", "Operating Systems", "Processes, scheduling, memory, and system behavior.", 6),
    ("developer-tools", "Developer Tools & Version Control", "Source control and development workflow fundamentals.", 7),
    ("computer-systems", "Computer Systems", "CPU, memory, processes, and measured system behavior.", 8),
]

QUESTION_TOPIC_SLUGS = {
    1: ("databases",),
    2: ("web-http",),
    3: ("web-http",),
    4: ("algorithms",),
    5: ("databases",),
    6: ("web-http",),
    7: ("security",),
    8: ("developer-tools",),
    9: ("operating-systems", "computer-systems"),
    10: ("security", "web-http"),
}


def seed_adaptive_learning(apps, schema_editor):
    LearningTopic = apps.get_model("core", "LearningTopic")
    Question = apps.get_model("core", "Question")
    LearningPath = apps.get_model("core", "LearningPath")
    LearningPathItem = apps.get_model("core", "LearningPathItem")
    Game = apps.get_model("core", "Game")
    Simulation = apps.get_model("core", "Simulation")
    database = schema_editor.connection.alias

    topics = {}
    for slug, name, description, order in TOPICS:
        topic, _ = LearningTopic.objects.using(database).get_or_create(
            slug=slug,
            defaults={"name": name, "description": description, "sort_order": order, "is_active": True},
        )
        topics[slug] = topic

    questions = Question.objects.using(database).filter(game__slug="quiz-challenge")
    for question in questions:
        tagged_topics = [topics["it-fundamentals"]]
        tagged_topics.extend(topics[slug] for slug in QUESTION_TOPIC_SLUGS.get(question.order, ()))
        question.topics.add(*tagged_topics)

    performance_lab = Simulation.objects.using(database).filter(
        slug="computer-system-performance-lab"
    ).first()
    if performance_lab:
        performance_lab.topic = topics["computer-systems"]
        performance_lab.save(using=database, update_fields=("topic",))

    path, _ = LearningPath.objects.using(database).get_or_create(
        slug="mca-core-foundations",
        defaults={
            "title": "MCA Core Foundations",
            "description": "Build a baseline across core IT concepts, then explore how computer resources shape system performance.",
            "is_active": True,
            "is_default": True,
        },
    )
    quiz = Game.objects.using(database).filter(slug="quiz-challenge").first()
    if quiz:
        LearningPathItem.objects.using(database).get_or_create(
            path=path,
            sequence=1,
            defaults={
                "title": "Quiz Challenge — IT fundamentals baseline",
                "topic": topics["it-fundamentals"],
                "activity_type": "quiz",
                "game": quiz,
                "difficulty": "intermediate",
                "expected_outcome": "Build a baseline across databases, web, algorithms, security, tools, and operating systems.",
            },
        )
    if performance_lab:
        LearningPathItem.objects.using(database).get_or_create(
            path=path,
            sequence=2,
            defaults={
                "title": "Computer System Performance Lab",
                "topic": topics["computer-systems"],
                "activity_type": "simulation",
                "simulation": performance_lab,
                "difficulty": "intermediate",
                "expected_outcome": "Investigate how CPU workload, processes, RAM, and background work change modeled system performance.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0006_learningpath_learningtopic_question_topics_and_more")]

    operations = [migrations.RunPython(seed_adaptive_learning, migrations.RunPython.noop)]
