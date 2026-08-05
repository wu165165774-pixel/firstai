from datetime import datetime


DECAY_PER_DAY = 0.002


def calculate_score(memory):

    now = datetime.utcnow()

    last = memory.last_accessed_at or memory.created_at

    if last is None:
        days = 0
    else:
        days = (now - last).days

    decay = days * DECAY_PER_DAY

    score = (
        memory.importance
        + memory.hit_count * 0.1
        - decay
    )

    return max(score, 0)