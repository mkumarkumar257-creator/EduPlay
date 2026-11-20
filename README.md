# EduPlay

**Learn. Play. Level Up.**

EduPlay is an MCA academic project for a gamified learning experience platform. The current foundation includes public pages, learner and educator accounts, protected role-specific dashboards, profile editing, SQLite configuration, and a responsive dark design system. Implemented modules include the learner Game Zone and Quiz Challenge, Simulation Lab, Adaptive Learning, Collaboration Hub, Performance Analytics, and educator Content Studio; other modules remain planned or demo-only.

## Requirements

- Python 3.12 or newer
- Django 6.1 (`requirements.txt`)

Bootstrap 5, the suggested fonts, and Chart.js load from CDNs, so those assets need an internet connection. The custom CSS still provides layout and styling if the CDNs are unavailable; analytics summaries and tables remain available without Chart.js.

## Run locally (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:DJANGO_SECRET_KEY = py -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
py manage.py migrate
py manage.py createsuperuser
py manage.py runserver
```

Open `http://127.0.0.1:8000/`. The `DJANGO_SECRET_KEY` value is generated locally and kept in the current PowerShell session; set it again in a new session. Never commit a real secret. `DJANGO_DEBUG` defaults to on for local development. Set it to `0` and configure `DJANGO_ALLOWED_HOSTS` for a deployment; production also needs HTTPS and deployment-specific static-file settings.

## Accounts and roles

Public registration offers Learner and Educator roles and signs the new user in. Profile editing can update a user's name and email, but it does not accept role changes. Administrators can also manage roles in Django admin at `/admin/`. To access the admin, create a superuser with the command above.

Learners are sent to `/dashboard/learner/`; educators are sent to `/dashboard/educator/`. The shared `/dashboard/` route redirects signed-in users based on their role. Opening the other role's dashboard returns HTTP 403. Profile details are at `/profile/`.

Login accepts either username or email. Leaving “Remember me” unchecked expires the session when the browser closes; selecting it uses Django's normal persistent session expiry.

Authenticated pages share a responsive sidebar layout. Learners can open Game Zone, Simulation Lab, Adaptive Learning, and the Collaboration Hub from their dashboard or sidebar. Other unfinished learner and educator tools open role-checked “Coming Soon” pages at `/workspace/<feature>/`; these placeholders do not claim to perform future features. Legacy learner `/workspace/simulations/` and `/workspace/learning-paths/` links redirect to their implemented pages.

## Phase 4: Game-Based Learning

The Game Zone currently includes the implemented Quiz Challenge and clearly disabled cards for planned games. Quiz Challenge has a seeded bank of 10 computer science and IT questions, one-question-at-a-time play, immediate answer feedback, a 180-second server-enforced timer, score tracking, and a results/restart flow. The question bank is editable in Django admin under Games and Questions (staff access required); questions can also be managed inline on a game.

Learner XP is real account data. A completed quiz earns up to the game's configured XP reward based on the learner's best score; a later personal best awards only the difference, so replaying an equal or lower score cannot farm XP. Timed-out attempts do not award XP. The learner dashboard derives its streak, lesson completion, recent activity, and progress summary from saved records in the last 30 days.

Educators cannot access learner-only game URLs. Future quiz games can use the Game, Question, GameAttempt, and GameAttemptAnswer models; published educator-created quizzes use the same server-validated attempt and XP flow as Quiz Challenge.

## Phase 4: Interactive Simulations

The learner-only Simulation Lab currently contains the Computer System Performance Lab. Learners can adjust CPU workload (10–100%), process count (1–20), RAM allocation (1–32 GB), and background workload (0–100%). A live browser preview shows estimated CPU and memory utilization, memory demand, a system load index, performance score, system condition, bottleneck, and estimated response time. On submit, the same model is validated and recalculated by the Python simulation engine before the run is saved.

Results are educational estimates using a simplified four-core desktop profile, not measurements of the learner's device. Each learner's completed runs are stored as experiment history and can be compared side by side. A configured XP reward is granted once for the learner's first completed run of this simulation; later runs remain in history but do not award repeat XP. Completion is tracked separately from experiment history. Future simulations can be added as `Simulation` records; only slugs registered to an implemented engine are playable.

## Phase 4: Adaptive Learning Paths

The learner-only Adaptive Learning page analyzes saved quiz answers and completed simulation experiments. Question topic tags and simulation topics connect those records to a seeded MCA Core Foundations path. Path completion is derived from completed `GameAttempt` and `SimulationCompletion` records; no duplicate per-user progress table is maintained. The path displays completed, current, upcoming, and prerequisite-locked items. Seeded items are not locked; future prerequisites must point to an earlier item in the same path.

Observed quiz accuracy is shown directly. Topic strengths and practice areas are inferred only after at least four answers span two distinct questions; one question repeated several times is still insufficient. Topic mastery combines accuracy (60%), question-bank coverage (20%), related activity completion (10%), and the last five answers (10%). Simulation performance outputs are displayed as system results, never as learner mastery scores.

Recommendation accuracy bands and evidence thresholds are centrally configurable in `config/settings.py`. The rule-based engine uses observed accuracy, recent answers, sufficiently evidenced topics, and current path progression. With fewer than five answers, learners receive a clearly labeled baseline activity rather than a personalized inference. Above 90% accuracy, no advanced recommendation is fabricated: the page explains when no implemented advanced activity exists. The initial quiz is intermediate and can be used for beginner-focused revision; the card distinguishes that suggested focus from the quiz's published difficulty.

## Phase 4: Collaborative Learning

Learners can create or join one active team through the Collaboration Hub. Team join codes are randomly generated, team size defaults to six (`EDUPLAY_MAX_TEAM_SIZE` in `config/settings.py`), and active membership constraints prevent duplicate memberships or joining multiple teams. Team leaders can edit team details, remove active members, and transfer leadership. A leader with other teammates must transfer leadership before leaving; a team with only its leader is archived when that learner leaves so its history remains intact.

The challenge catalog starts with five records explicitly labeled as seeded sample content; educators can also create and own new challenges in Content Studio. A team joins each challenge once, then a member can submit a response of the challenge's configured minimum length (50 characters for the seeded examples). This participation-based completion is stored but is not automatically graded for correctness. On completion, the team earns the challenge's XP once and every active member receives the same amount in their existing learner XP balance. The leaderboard ranks active teams using XP actually earned from completed challenges and stays empty until at least two active teams exist. Team activity comes from saved creation, membership, leadership, challenge, and reward events.

## Phase 5: Performance Analytics & Progress Tracking

The learner-only Performance Analytics page at `/analytics/learner/` reads the signed-in learner's quiz attempts and answers, game completions, simulation runs and first completions, collaboration events, and existing XP balance. It provides Last 7/30/90 days and all-time filters, activity and topic filters, KPI cards, recent records, rule-based insights, and responsive Chart.js charts for XP progression, activity, quiz accuracy, topic evidence, and activity mix. Empty states appear when a chart or insight does not yet have supporting records. The level display is derived from lifetime XP at 100 XP per level; it is not a separate stored account field.

The educator-only page at `/analytics/educator/` shows platform-wide learner activity, answer-level quiz accuracy, completion and participation rates, activity trends, learner records, and evidence-thresholded insights. The current database has no course enrollment or educator-to-class assignment model, so reporting is explicitly platform-wide and the course filter is disabled. Achievements also have no stored model yet and are labeled as untracked. No analytics tables or migrations were added; reports are computed from existing records. Educator results are protected by the existing role guard, and learner detail queries exclude educator accounts.

## Phase 6: Content Authoring & Customization Tools

Educators can manage their own quizzes, lessons, team challenges, and practice activities at `/educator/content/`. Content Studio supports drafts, previews, publishing, unpublishing, archiving, deletion when no protected attempt/team history exists, and filters by type, status, and subject. Quiz question editing supports four distinct answer options, explanations, topics, difficulty, ordering, additions, and deletions. Publishing validates required lesson or activity content and requires at least one valid question for quizzes. Editing a published item returns it to draft until it is reviewed and republished.

Learners browse public published content at `/learning/` and view reading lessons, practice instructions, published quizzes, and published team challenges. Lesson and practice views and completion are recorded; quiz attempts, answers, results, and XP reuse the existing game system. Draft, unpublished, archived, and private content is filtered server-side. The learner `/learning/progress/` page combines lesson/practice records with quiz attempts and team challenge participation.

Content Studio statistics are computed from saved views, quiz attempts, team starts, and learner completion rows. “Average score” is based on completed quiz attempts; challenge completion represents participation, not an automated correctness grade. A course-enrollment model and graded practice submissions are not implemented yet.

## Try both roles manually

1. Start the server and open `/accounts/register/`.
2. Create a learner account with a unique username and email. Signup takes you to the learner dashboard.
3. Log out, then register a second account and choose Educator. Signup takes that account to the educator dashboard.
4. To check the role guard, sign in as a learner and open `/dashboard/educator/`; it should return HTTP 403. Repeat as an educator at `/dashboard/learner/`.
5. Open `/profile/` for either account. Name and email can be changed; role and username are read-only.
6. As the learner, open `/game-zone/`, start Quiz Challenge, answer the seeded questions, and review the feedback, score, XP, recent activity, and replay behavior.
7. Open `/simulation-lab/`, adjust the four resource controls, and run the Computer System Performance Lab. Compare the saved run against a previous experiment; the first completion earns XP once.
8. Open `/adaptive-learning/` to review observed accuracy, topic evidence, path progress, and the next recommendation. Repeat Quiz Challenge to build evidence across multiple questions and see topic mastery become available.
9. Open `/collaboration/` to create a team or join with a joining code. As team leader, transfer leadership or remove members from the team page. Start one of the seeded sample challenges and submit the required team response to verify team and learner XP.
10. Open `/analytics/learner/` to inspect one learner's XP, activity, progress, filters, charts, and empty-data behavior. Open `/analytics/educator/` as an educator to review platform-wide participation and learner rows. Trying either page as the other role should return HTTP 403.
11. As an educator, open `/educator/content/`, create a quiz with questions, preview it, publish it, and verify that it appears at `/learning/`. As a learner, complete the quiz and inspect its saved score and XP. Also create and publish a lesson or practice activity, then verify learner access and completion at `/learning/progress/` and `/analytics/learner/`.

The automated suite also exercises both roles with `py manage.py test`.

## Checks

```powershell
py manage.py check
py manage.py test
```

## Current routes

- `/` — landing page
- `/about/` — project direction and current phase
- `/accounts/register/` — learner or educator registration
- `/accounts/login/` — username/email login
- `/accounts/logout/` — CSRF-protected logout (POST)
- `/dashboard/` — role-based redirect
- `/dashboard/learner/` — learner-only dashboard
- `/dashboard/educator/` — educator-only dashboard
- `/profile/` — protected profile
- `/game-zone/` — learner-only game catalog
- `/game-zone/quiz-challenge/` — learner-only quiz instructions
- `/game-zone/quiz-challenge/start/` — POST to create a quiz attempt
- `/game-zone/quiz-challenge/attempt/<uuid>/` — private quiz attempt and results
- `/game-zone/quiz-challenge/attempt/<uuid>/answer/` — POST a quiz answer
- `/simulation-lab/` — learner-only simulation catalog
- `/simulation-lab/computer-system-performance-lab/` — learner-only performance experiment
- `/simulation-lab/computer-system-performance-lab/run/` — POST a validated simulation run
- `/adaptive-learning/` — learner-only performance analysis and learning path
- `/analytics/learner/` — private learner progress analytics
- `/analytics/educator/` — role-protected platform-wide learner analytics
- `/educator/content/` — educator-owned Content Studio and actual content statistics
- `/educator/content/create/` — choose a content type to author
- `/learning/` — learner library of published public content
- `/learning/progress/` — learner lesson, practice, quiz, and team challenge progress
- `/learning/quizzes/<slug>/` — quiz instructions for an available published quiz
- `/learning/quizzes/<slug>/start/` — POST to create an educator-authored quiz attempt
- `/learning/<content-type>/<slug>/` — published lesson or practice detail
- `/learning/<content-type>/<id>/complete/` — POST to record lesson/practice completion
- `/collaboration/` — learner-only Collaboration Hub
- `/collaboration/teams/<id>/` — active-member team workspace and leader tools
- `/collaboration/challenges/<slug>/` — challenge details and team submission
- `/workspace/<feature>/` — role-checked roadmap placeholder
- `/admin/` — Django administration

