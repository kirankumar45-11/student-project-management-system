import uuid
import threading
from app.database import SessionLocal
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, TopicStatusEnum, TopicProposedRoleEnum, AssignmentStatusEnum
from app.services.slot_guard import verify_and_lock_supervisor_slots
from app.core.security import hash_password

def test_slot_guard_concurrency():
    """
    Simulates two concurrent transactions attempting to claim the single remaining slot
    on a supervisor with max_slots=1 using verify_and_lock_supervisor_slots (SELECT ... FOR UPDATE).
    Verifies that only 1 succeeds, while the other is rejected with quota full error.
    """
    uid = uuid.uuid4().hex[:6]
    setup_db = SessionLocal()
    try:
        dept = setup_db.query(Department).first()
        sess = setup_db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
        sess_id = sess.id

        # Create supervisor with strictly max_slots = 1
        u_sup = User(
            username=f"CSUP_{uid}",
            email=f"csup_{uid}@test.local",
            password_hash=hash_password("Pass123!"),
            role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED
        )
        setup_db.add(u_sup)
        setup_db.flush()

        sup = Supervisor(
            user_id=u_sup.id,
            department_id=dept.id,
            full_name=f"Dr. Concurrency Tester {uid}",
            designation="Professor",
            max_slots=1
        )
        setup_db.add(sup)

        # Create two students and topics
        students = []
        topics = []
        for i in [1, 2]:
            u = User(
                username=f"CSTU_{i}_{uid}",
                email=f"cstu_{i}_{uid}@test.local",
                password_hash=hash_password("Pass123!"),
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.APPROVED
            )
            setup_db.add(u)
            setup_db.flush()

            s = Student(
                user_id=u.id,
                department_id=dept.id,
                session_id=sess_id,
                usn=f"CSTU_{i}_{uid}",
                full_name=f"Student {i} {uid}",
                semester=8,
                academic_year=sess.name,
                phone=f"+91 999900000{i}"
            )
            setup_db.add(s)
            setup_db.flush()
            students.append(s)

            t = Topic(
                title=f"Concurrent Topic {i} {uid}",
                normalized_title=f"concurrent topic {i} {uid}",
                description="Desc",
                domain="AI",
                department_id=dept.id,
                session_id=sess_id,
                proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
                proposed_by_user_id=u_sup.id,
                status=TopicStatusEnum.APPROVED
            )
            setup_db.add(t)
            setup_db.flush()
            topics.append(t)

        setup_db.commit()
        sup_id = sup.id
        s1_id, s2_id = students[0].id, students[1].id
        t1_id, t2_id = topics[0].id, topics[1].id
    finally:
        setup_db.close()

    results = []
    errors = []

    def assign_worker(student_id, topic_id):
        worker_db = SessionLocal()
        try:
            # 1. Acquire row lock and check slots
            verified_sup = verify_and_lock_supervisor_slots(worker_db, sup_id)
            # 2. Insert assignment
            assignment = TopicAssignment(
                topic_id=topic_id,
                student_id=student_id,
                supervisor_id=verified_sup.id,
                session_id=sess_id,
                status=AssignmentStatusEnum.ACTIVE
            )
            worker_db.add(assignment)
            worker_db.commit()
            results.append(assignment.id)
        except Exception as e:
            worker_db.rollback()
            errors.append(str(e))
        finally:
            worker_db.close()

    t1 = threading.Thread(target=assign_worker, args=(s1_id, t1_id))
    t2 = threading.Thread(target=assign_worker, args=(s2_id, t2_id))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one must succeed, and exactly one must fail with quota full
    assert len(results) == 1, f"Expected exactly 1 assignment, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}"
    assert "maximum quota" in errors[0]
