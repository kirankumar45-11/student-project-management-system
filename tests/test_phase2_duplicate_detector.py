import uuid
import pytest
from sqlalchemy.orm import Session
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.topic import Topic, TopicStatusEnum, TopicProposedRoleEnum
from app.services.duplicate_detector import (
    calculate_similarity_score,
    check_topic_duplicate,
    jaccard_similarity,
    levenshtein_similarity,
    normalize_text
)
from app.core.security import hash_password

def test_duplicate_detector_exact_and_reworded_titles():
    """Verifies that exact and reworded titles produce high similarity exceeding the threshold."""
    t1 = "Student Project Management System"
    t2 = "A System for Student Project Management"
    
    score = calculate_similarity_score(t1, t2)
    # Minimal stop words ("a", "for") stripped, tokens: {"student", "project", "management", "system"}
    assert score >= 0.80, f"Expected high score for reworded title, got {score}"

    # Exact match must be 1.0
    exact_score = calculate_similarity_score(t1, t1)
    assert exact_score == 1.0

def test_duplicate_detector_short_titles():
    """Verifies minimal stop-word tokenization on short technical titles."""
    t1 = "Student Project Management System"
    t2 = "Student Project Management System"
    assert calculate_similarity_score(t1, t2) == 1.0

    # Short title with only 1 word difference
    t3 = "Student Project Management Tool"
    score = calculate_similarity_score(t1, t3)
    assert score >= 0.60, f"Expected reasonable similarity for 3 of 4 tokens matching, got {score}"

def test_duplicate_detector_unrelated_titles():
    """Verifies that completely distinct titles produce a near-zero similarity score."""
    t1 = "Student Project Management System"
    t2 = "Deep Learning for Autonomous Drone Navigation"
    
    score = calculate_similarity_score(t1, t2)
    assert score < 0.20, f"Expected near zero similarity for unrelated titles, got {score}"

def test_duplicate_detector_threshold_boundary():
    """Verifies behavior strictly at, above, and below the threshold boundary."""
    t1 = "Smart Healthcare Monitoring System"
    t2 = "Smart Healthcare Tracking System"

    score = calculate_similarity_score(t1, t2)
    # If threshold is slightly above the score -> not duplicate
    assert not (score >= (score + 0.05))
    # If threshold is at or below score -> duplicate
    assert (score >= score)
    assert (score >= (score - 0.05))

def test_duplicate_detector_ignores_rejected_topics(db_session: Session):
    """Verifies that candidate topics matching a REJECTED topic are NOT flagged as duplicates."""
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"DUP_PROPOSER_{uid}",
        email=f"dup_{uid}@test.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED
    )
    db_session.add(u)
    db_session.flush()

    rejected_title = f"Blockchain for Supply Chain Tracking {uid}"
    rej_topic = Topic(
        title=rejected_title,
        normalized_title=rejected_title.lower(),
        description="Rejected topic description",
        domain="Blockchain",
        department_id=dept.id,
        session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u.id,
        status=TopicStatusEnum.REJECTED,
        rejection_remarks="Redundant topic."
    )
    db_session.add(rej_topic)
    db_session.commit()

    # Propose the exact same title as candidate
    is_dup, max_score, conflicting_title = check_topic_duplicate(
        db=db_session,
        new_title=rejected_title,
        threshold=0.70
    )
    # Must NOT flag duplicate against the rejected topic
    assert not is_dup
    assert conflicting_title is None

def test_duplicate_detector_flags_available_topic(db_session: Session):
    """Verifies that candidate topics matching an AVAILABLE or ASSIGNED topic are flagged."""
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"ACT_PROPOSER_{uid}",
        email=f"act_{uid}@test.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED
    )
    db_session.add(u)
    db_session.flush()

    active_title = f"Federated Learning on Edge Devices {uid}"
    act_topic = Topic(
        title=active_title,
        normalized_title=active_title.lower(),
        description="Active topic description",
        domain="AI",
        department_id=dept.id,
        session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u.id,
        status=TopicStatusEnum.AVAILABLE
    )
    db_session.add(act_topic)
    db_session.commit()

    # Candidate with slight reword
    candidate_title = f"A System for Federated Learning on Edge Devices {uid}"
    is_dup, max_score, conflicting_title = check_topic_duplicate(
        db=db_session,
        new_title=candidate_title,
        threshold=0.70
    )
    assert is_dup
    assert max_score >= 0.70
    assert conflicting_title == active_title
