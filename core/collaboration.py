"""Transactional rules for learner teams and collaborative challenges."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    Challenge,
    Team,
    TeamActivity,
    TeamChallenge,
    TeamMembership,
    User,
)


class CollaborationRuleError(Exception):
    """A collaboration action violates a product rule."""


def active_membership_for(user):
    return (
        TeamMembership.objects.filter(user=user, left_at__isnull=True, team__is_active=True)
        .select_related("team", "team__leader")
        .first()
    )


def _active_membership(team, user):
    return TeamMembership.objects.filter(team=team, user=user, left_at__isnull=True).first()


def _require_leader(team, user):
    if team.leader_id != user.pk or _active_membership(team, user) is None:
        raise CollaborationRuleError("Only the active team leader can manage this team.")


def _record_activity(team, event_type, message, actor=None, team_challenge=None, xp_awarded=0):
    return TeamActivity.objects.create(
        team=team,
        actor=actor,
        team_challenge=team_challenge,
        event_type=event_type,
        message=message,
        xp_awarded=xp_awarded,
    )


@transaction.atomic
def create_team(user, cleaned_data):
    User.objects.select_for_update().get(pk=user.pk)
    if active_membership_for(user):
        raise CollaborationRuleError("Leave your current team before creating another one.")
    team = Team.objects.create(leader=user, **cleaned_data)
    TeamMembership.objects.create(team=team, user=user)
    _record_activity(team, TeamActivity.Event.TEAM_CREATED, f"{user.username} created the team.", actor=user)
    _record_activity(team, TeamActivity.Event.MEMBER_JOINED, f"{user.username} joined as team leader.", actor=user)
    return team


@transaction.atomic
def join_team(user, join_code):
    User.objects.select_for_update().get(pk=user.pk)
    team = Team.objects.select_for_update().filter(join_code__iexact=join_code, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("That team code is not valid or the team is no longer active.")

    current_membership = active_membership_for(user)
    if current_membership:
        if current_membership.team_id == team.pk:
            return current_membership, False
        raise CollaborationRuleError("You are already in a team. Leave it before joining another.")

    max_size = getattr(settings, "EDUPLAY_MAX_TEAM_SIZE", 6)
    if team.memberships.filter(left_at__isnull=True).count() >= max_size:
        raise CollaborationRuleError("This team has reached its member limit.")

    try:
        membership = TeamMembership.objects.create(team=team, user=user)
    except IntegrityError:
        raise CollaborationRuleError("Your team membership changed. Refresh and try again.") from None
    _record_activity(team, TeamActivity.Event.MEMBER_JOINED, f"{user.username} joined the team.", actor=user)
    return membership, True


@transaction.atomic
def leave_team(user, team_id):
    team = Team.objects.select_for_update().filter(pk=team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    membership = _active_membership(team, user)
    if membership is None:
        raise CollaborationRuleError("You are not an active member of this team.")

    active_count = team.memberships.filter(left_at__isnull=True).count()
    if team.leader_id == user.pk and active_count > 1:
        raise CollaborationRuleError("Transfer leadership to another member before leaving the team.")

    membership.left_at = timezone.now()
    membership.save(update_fields=("left_at",))
    _record_activity(team, TeamActivity.Event.MEMBER_LEFT, f"{user.username} left the team.", actor=user)
    if team.leader_id == user.pk:
        team.is_active = False
        team.save(update_fields=("is_active", "updated_at"))
        _record_activity(team, TeamActivity.Event.TEAM_ARCHIVED, "The team was archived after its leader left.", actor=user)
    return team


@transaction.atomic
def update_team(user, team_id, cleaned_data):
    team = Team.objects.select_for_update().filter(pk=team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    _require_leader(team, user)
    for field in ("name", "description", "avatar"):
        setattr(team, field, cleaned_data[field])
    team.save(update_fields=("name", "description", "avatar", "updated_at"))
    _record_activity(team, TeamActivity.Event.TEAM_UPDATED, f"{user.username} updated team details.", actor=user)
    return team


@transaction.atomic
def transfer_leadership(user, team_id, new_leader_id):
    team = Team.objects.select_for_update().filter(pk=team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    _require_leader(team, user)
    target_membership = TeamMembership.objects.select_for_update().filter(
        team=team, user_id=new_leader_id, left_at__isnull=True
    ).select_related("user").first()
    if target_membership is None:
        raise CollaborationRuleError("Choose an active team member to receive leadership.")
    if target_membership.user_id == user.pk:
        raise CollaborationRuleError("You are already the team leader.")
    team.leader = target_membership.user
    team.save(update_fields=("leader", "updated_at"))
    _record_activity(
        team,
        TeamActivity.Event.LEADER_TRANSFERRED,
        f"{user.username} transferred leadership to {target_membership.user.username}.",
        actor=user,
    )
    return team


@transaction.atomic
def remove_member(user, team_id, member_id):
    team = Team.objects.select_for_update().filter(pk=team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    _require_leader(team, user)
    membership = TeamMembership.objects.select_for_update().filter(
        team=team, user_id=member_id, left_at__isnull=True
    ).select_related("user").first()
    if membership is None:
        raise CollaborationRuleError("That learner is not an active member of this team.")
    if membership.user_id == team.leader_id:
        raise CollaborationRuleError("Transfer leadership before removing the team leader.")
    membership.left_at = timezone.now()
    membership.save(update_fields=("left_at",))
    _record_activity(
        team,
        TeamActivity.Event.MEMBER_REMOVED,
        f"{user.username} removed {membership.user.username} from the team.",
        actor=user,
    )
    return team


@transaction.atomic
def start_challenge(user, challenge_id):
    membership = active_membership_for(user)
    if membership is None:
        raise CollaborationRuleError("Create or join a team before starting a challenge.")
    team = Team.objects.select_for_update().filter(pk=membership.team_id, is_active=True).first()
    challenge = Challenge.objects.select_for_update().filter(pk=challenge_id).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    if challenge is None or not challenge.is_joinable:
        raise CollaborationRuleError("This challenge is not currently open for teams.")

    team_challenge, created = TeamChallenge.objects.get_or_create(team=team, challenge=challenge)
    if created:
        _record_activity(
            team,
            TeamActivity.Event.CHALLENGE_STARTED,
            f"{team.name} started {challenge.title}.",
            actor=user,
            team_challenge=team_challenge,
        )
    return team_challenge, created


@transaction.atomic
def save_challenge_progress(user, team_challenge_id, submission_text):
    membership = active_membership_for(user)
    if membership is None:
        raise CollaborationRuleError("An active team membership is required to save challenge progress.")
    team = Team.objects.select_for_update().filter(pk=membership.team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    team_challenge = TeamChallenge.objects.select_for_update().select_related("challenge", "team").filter(
        pk=team_challenge_id, team=team, status=TeamChallenge.Status.IN_PROGRESS
    ).first()
    if team_challenge is None:
        raise CollaborationRuleError("An in-progress challenge for your team is required.")
    if not team_challenge.challenge.is_joinable:
        raise CollaborationRuleError("The challenge deadline has passed or the challenge is no longer open.")
    cleaned_text = " ".join(submission_text.split())
    if len(cleaned_text) < 20:
        raise CollaborationRuleError("Add at least 20 characters to save team progress.")
    team_challenge.submission_text = cleaned_text
    team_challenge.save(update_fields=("submission_text",))
    _record_activity(
        team,
        TeamActivity.Event.CHALLENGE_PROGRESS_SAVED,
        f"{user.username} saved progress on {team_challenge.challenge.title}.",
        actor=user,
        team_challenge=team_challenge,
    )
    return team_challenge


@transaction.atomic
def complete_challenge(user, team_challenge_id, submission_text):
    membership = active_membership_for(user)
    if membership is None:
        raise CollaborationRuleError("An active team membership is required to submit this challenge.")
    team = Team.objects.select_for_update().filter(pk=membership.team_id, is_active=True).first()
    if team is None:
        raise CollaborationRuleError("This team is no longer active.")
    team_challenge = TeamChallenge.objects.select_for_update().select_related("challenge", "team").filter(
        pk=team_challenge_id, team=team
    ).first()
    if team_challenge is None:
        raise CollaborationRuleError("This challenge participation does not belong to your team.")
    if team_challenge.status == TeamChallenge.Status.COMPLETED:
        raise CollaborationRuleError("This team has already completed the challenge and received its reward.")
    if not team_challenge.challenge.is_joinable:
        raise CollaborationRuleError("The challenge deadline has passed or the challenge is no longer open.")
    if len(submission_text.strip()) < team_challenge.challenge.minimum_submission_characters:
        raise CollaborationRuleError("The submission does not meet this challenge's minimum length.")

    now = timezone.now()
    reward = team_challenge.challenge.xp_reward
    active_member_ids = list(team.memberships.filter(left_at__isnull=True).values_list("user_id", flat=True))
    updated = TeamChallenge.objects.filter(
        pk=team_challenge.pk,
        status=TeamChallenge.Status.IN_PROGRESS,
    ).update(
        status=TeamChallenge.Status.COMPLETED,
        submission_text=submission_text.strip(),
        submitted_by=user,
        completed_at=now,
        xp_awarded=reward,
    )
    if updated != 1:
        raise CollaborationRuleError("This team has already completed the challenge and received its reward.")
    team_challenge.refresh_from_db()
    Team.objects.filter(pk=team.pk).update(total_xp=F("total_xp") + reward)
    if reward and active_member_ids:
        User.objects.filter(pk__in=active_member_ids).update(total_xp=F("total_xp") + reward)
    _record_activity(
        team,
        TeamActivity.Event.CHALLENGE_COMPLETED,
        f"{team.name} completed {team_challenge.challenge.title} and earned {reward} team XP. "
        f"{len(active_member_ids)} active member(s) each earned {reward} learner XP.",
        actor=user,
        team_challenge=team_challenge,
        xp_awarded=reward,
    )
    team.refresh_from_db(fields=("total_xp",))
    return team_challenge
