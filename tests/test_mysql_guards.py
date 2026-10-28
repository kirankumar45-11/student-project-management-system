import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicAssignment, TopicStatusEnum, TopicProposedRoleEnum, AssignmentStatusEnum
)
from app.core.security import hash_password

def test_mysql_generated_column_active_student_guard(db_session: Session):
    """
    Verifies that MySQL 8.0 enforces the generated-column unique index:
    1. An ACTIVE assignment for student S1 succeeds.
    2. A second ACTIVE assignment for student S1 FAILS with IntegrityError (duplicate key).
    3. Changing the first assignment to DROPPED allows a new ACTIVE assignment for student S1 to succeed.
    """
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    session = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # 1. Setup Student with unique username
    u_stu = User(
        username=f"GSTU_{uid}",
        email=f"gstu_{uid}@test.local",
        password_hash=hash_password("Password123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED
    )
    db_session.add(u_stu)
    db_session.flush()

    stu = Student(
        user_id=u_stu.id,
        department_id=dept.id,
        session_id=session.id,
        usn=f"GSTU_{uid}",
        full_name="Guard Test Student",
        semester=8,
        academic_year=session.name,
        phone=f"+91 99999{uid[:5]}"
    )
    db_session.add(stu)
    db_session.flush()

    # 2. Setup Supervisor with unique username
    u_sup = User(
        username=f"GSUP_{uid}",
        email=f"gsup_{uid}@test.local",
        password_hash=hash_password("Password123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED
    )
    db_session.add(u_sup)
    db_session.flush()

    sup = Supervisor(
        user_id=u_sup.id,
        department_id=dept.id,
        full_name="Guard Test Supervisor",
        designation="Professor",
        max_slots=4
    )
    db_session.add(sup)
    db_session.flush()

    # 3. Setup Two Topics
    t1 = Topic(
        title=f"Guard Test Topic 1 {uid}",
        normalized_title=f"guard test topic 1 {uid}",
        description="Description 1",
        domain="AI",
        department_id=dept.id,
        session_id=session.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup.id,
        status=TopicStatusEnum.APPROVED
    )
    t2 = Topic(
        title=f"Guard Test Topic 2 {uid}",
        normalized_title=f"guard test topic 2 {uid}",
        description="Description 2",
        domain="Cloud",
        department_id=dept.id,
        session_id=session.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup.id,
        status=TopicStatusEnum.APPROVED
    )
    db_session.add_all([t1, t2])
    db_session.flush()

    # 4. Create first ACTIVE assignment for Student 1 -> MUST SUCCEED
    a1 = TopicAssignment(
        topic_id=t1.id,
        student_id=stu.id,
        supervisor_id=sup.id,
        session_id=session.id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a1)
    db_session.commit()
    assert a1.id is not None
    assert a1.active_student_guard == stu.id

    # 5. Attempt second ACTIVE assignment for Student 1 with Topic 2 -> MUST FAIL
    a2 = TopicAssignment(
        topic_id=t2.id,
        student_id=stu.id,
        supervisor_id=sup.id,
        session_id=session.id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    db_session.rollback()
    assert "uq_active_student_assignment" in str(exc_info.value) or "Duplicate entry" in str(exc_info.value)

    # 6. Drop the first assignment
    a1_reloaded = db_session.query(TopicAssignment).filter(TopicAssignment.id == a1.id).first()
    a1_reloaded.status = AssignmentStatusEnum.DROPPED
    db_session.commit()
    db_session.refresh(a1_reloaded)
    # The generated column evaluates to NULL upon status change
    assert a1_reloaded.active_student_guard is None

    # 7. Now insert a new ACTIVE assignment for Student 1 -> MUST SUCCEED
    a3 = TopicAssignment(
        topic_id=t2.id,
        student_id=stu.id,
        supervisor_id=sup.id,
        session_id=session.id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a3)
    db_session.commit()
    assert a3.id is not None
    assert a3.active_student_guard == stu.id

def test_mysql_generated_column_active_topic_guard(db_session: Session):
    """
    Verifies that MySQL 8.0 enforces the active_topic_guard generated-column unique index:
    1. An ACTIVE assignment for Topic T1 with Student S1 succeeds.
    2. A second ACTIVE assignment for Topic T1 with Student S2 FAILS with IntegrityError.
    3. Changing the first assignment to DROPPED allows a new ACTIVE assignment for Topic T1 to succeed.
    """
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    session = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # Setup Two Students
    u_stu1 = User(
        username=f"TGSTU1_{uid}", email=f"tgstu1_{uid}@test.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.STUDENT, status=AccountStatusEnum.APPROVED
    )
    u_stu2 = User(
        username=f"TGSTU2_{uid}", email=f"tgstu2_{uid}@test.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.STUDENT, status=AccountStatusEnum.APPROVED
    )
    db_session.add_all([u_stu1, u_stu2])
    db_session.flush()

    stu1 = Student(
        user_id=u_stu1.id, department_id=dept.id, session_id=session.id,
        usn=f"TGSTU1_{uid}", full_name="Topic Guard Student 1", semester=8,
        academic_year=session.name, phone=f"+91 91111{uid[:5]}"
    )
    stu2 = Student(
        user_id=u_stu2.id, department_id=dept.id, session_id=session.id,
        usn=f"TGSTU2_{uid}", full_name="Topic Guard Student 2", semester=8,
        academic_year=session.name, phone=f"+91 92222{uid[:5]}"
    )
    db_session.add_all([stu1, stu2])
    db_session.flush()

    # Setup Supervisor
    u_sup = User(
        username=f"TGSUP_{uid}", email=f"tgsup_{uid}@test.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.SUPERVISOR, status=AccountStatusEnum.APPROVED
    )
    db_session.add(u_sup)
    db_session.flush()
    sup = Supervisor(
        user_id=u_sup.id, department_id=dept.id, full_name="Topic Guard Supervisor",
        designation="Associate Professor", max_slots=5
    )
    db_session.add(sup)
    db_session.flush()

    # Setup Topic T1
    t1 = Topic(
        title=f"Shared Topic {uid}",
        normalized_title=f"shared topic {uid}",
        description="Shared Topic Description",
        domain="Systems",
        department_id=dept.id,
        session_id=session.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup.id,
        status=TopicStatusEnum.APPROVED
    )
    db_session.add(t1)
    db_session.flush()

    # 1. Create first ACTIVE assignment for Topic T1 with Student S1 -> SUCCEEDS
    a1 = TopicAssignment(
        topic_id=t1.id, student_id=stu1.id, supervisor_id=sup.id,
        session_id=session.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a1)
    db_session.commit()
    assert a1.id is not None
    assert a1.active_topic_guard == t1.id

    # 2. Attempt second ACTIVE assignment for the SAME Topic T1 with Student S2 -> FAILS
    a2 = TopicAssignment(
        topic_id=t1.id, student_id=stu2.id, supervisor_id=sup.id,
        session_id=session.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    db_session.rollback()
    assert "uq_active_topic_assignment" in str(exc_info.value) or "Duplicate entry" in str(exc_info.value)

    # 3. Change first assignment to DROPPED -> clears active_topic_guard
    a1_reloaded = db_session.query(TopicAssignment).filter(TopicAssignment.id == a1.id).first()
    a1_reloaded.status = AssignmentStatusEnum.DROPPED
    db_session.commit()
    db_session.refresh(a1_reloaded)
    assert a1_reloaded.active_topic_guard is None

    # 4. Now second ACTIVE assignment for Topic T1 with Student S2 -> SUCCEEDS
    a3 = TopicAssignment(
        topic_id=t1.id, student_id=stu2.id, supervisor_id=sup.id,
        session_id=session.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(a3)
    db_session.commit()
    assert a3.id is not None
    assert a3.active_topic_guard == t1.id
