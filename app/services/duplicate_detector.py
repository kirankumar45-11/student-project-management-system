import string
from typing import Set, Tuple, Optional
from sqlalchemy.orm import Session
from app.models.topic import Topic, TopicStatusEnum
from app.config import settings

# Strict minimal stop words (15 functional particles only)
MINIMAL_STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "in", "on", "at",
    "to", "for", "of", "with", "by", "from", "is", "are"
}

def normalize_text(text: str) -> Tuple[str, Set[str]]:
    """
    Normalizes a topic title:
    1. Lowercases string
    2. Strips punctuation
    3. Filters out only minimal functional stop words
    Returns: (cleaned_joined_string, token_set)
    """
    text = text.lower().strip()
    # Replace punctuation with spaces
    table = str.maketrans(string.punctuation, " " * len(string.punctuation))
    cleaned = text.translate(table)
    tokens = [w for w in cleaned.split() if w and w not in MINIMAL_STOP_WORDS]
    
    joined_clean = " ".join(tokens)
    token_set = set(tokens)
    return joined_clean, token_set

def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Computes Jaccard index between two token sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / len(union)

def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes exact edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

def levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein ratio: 1.0 - (distance / max_len)."""
    if not s1 and not s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(s1, s2)
    return 1.0 - (dist / max_len)

def calculate_similarity_score(title_a: str, title_b: str) -> float:
    """
    Calculates combined similarity score:
    Score = 0.6 * Jaccard + 0.4 * Levenshtein
    """
    clean_a, tokens_a = normalize_text(title_a)
    clean_b, tokens_b = normalize_text(title_b)

    jaccard = jaccard_similarity(tokens_a, tokens_b)
    lev = levenshtein_similarity(clean_a, clean_b)

    score = 0.6 * jaccard + 0.4 * lev
    return round(score, 4)

def check_topic_duplicate(
    db: Session,
    new_title: str,
    threshold: Optional[float] = None,
    exclude_topic_id: Optional[int] = None
) -> Tuple[bool, float, Optional[str]]:
    """
    Checks proposed topic title against all existing topics in statuses:
    AVAILABLE, PROPOSED, APPROVED, ASSIGNED, ARCHIVED (ignores REJECTED).
    
    Returns:
    (is_duplicate, max_score, conflicting_title)
    """
    if threshold is None:
        threshold = settings.DUPLICATE_THRESHOLD

    # Query all active/candidate/archived topics
    target_statuses = [
        TopicStatusEnum.AVAILABLE,
        TopicStatusEnum.PROPOSED,
        TopicStatusEnum.APPROVED,
        TopicStatusEnum.ASSIGNED,
        TopicStatusEnum.ARCHIVED,
    ]

    query = db.query(Topic).filter(Topic.status.in_(target_statuses))
    if exclude_topic_id:
        query = query.filter(Topic.id != exclude_topic_id)

    existing_topics = query.all()

    max_score = 0.0
    conflicting_title: Optional[str] = None

    for topic in existing_topics:
        score = calculate_similarity_score(new_title, topic.title)
        if score > max_score:
            max_score = score
            conflicting_title = topic.title

    if max_score >= threshold:
        return True, max_score, conflicting_title

    return False, max_score, None
