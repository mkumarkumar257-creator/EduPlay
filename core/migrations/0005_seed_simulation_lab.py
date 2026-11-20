from django.db import migrations


SIMULATIONS = [
    {
        "title": "Computer System Performance Lab",
        "slug": "computer-system-performance-lab",
        "description": "Adjust CPU work, process count, RAM, and background tasks to investigate resource utilization and system performance.",
        "category": "systems",
        "difficulty": "intermediate",
        "estimated_duration_minutes": 15,
        "xp_reward": 40,
        "icon": "◉",
        "is_active": True,
        "is_implemented": True,
    },
    {
        "title": "Network Traffic Explorer",
        "slug": "network-traffic-explorer",
        "description": "Explore how traffic volume, latency, and packet loss affect a network path.",
        "category": "networking",
        "difficulty": "intermediate",
        "estimated_duration_minutes": 12,
        "xp_reward": 30,
        "icon": "◎",
        "is_active": True,
        "is_implemented": False,
    },
    {
        "title": "Database Query Tuning",
        "slug": "database-query-tuning",
        "description": "Compare query plans and indexing choices on a modeled data set.",
        "category": "databases",
        "difficulty": "advanced",
        "estimated_duration_minutes": 18,
        "xp_reward": 35,
        "icon": "▤",
        "is_active": True,
        "is_implemented": False,
    },
    {
        "title": "Cybersecurity Incident Room",
        "slug": "cybersecurity-incident-room",
        "description": "Practice structured decisions during a simulated security incident.",
        "category": "security",
        "difficulty": "intermediate",
        "estimated_duration_minutes": 20,
        "xp_reward": 35,
        "icon": "◇",
        "is_active": True,
        "is_implemented": False,
    },
]


def seed_simulations(apps, schema_editor):
    Simulation = apps.get_model("core", "Simulation")
    database = schema_editor.connection.alias
    for simulation in SIMULATIONS:
        Simulation.objects.using(database).get_or_create(
            slug=simulation["slug"], defaults=simulation
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0004_simulation_simulationattempt_simulationcompletion_and_more")]

    operations = [migrations.RunPython(seed_simulations, migrations.RunPython.noop)]
