"""Pure, application-day based review rules; callers own clock and transaction."""
from datetime import date, timedelta

INTERVALS = (1, 3, 7, 14, 30)


def next_schedule(previous, *, day, independent, due_review=False, retest=False):
    today = date.fromisoformat(day)
    previous = previous or {}
    stage = int(previous.get('stage', 0))
    last = previous.get('last_success_day')
    if not independent:
        return dict(stage=0, due_day=day, last_success_day=last)
    if retest or not previous or stage == 0:
        stage, interval = 1, 1
    elif due_review and previous['due_day'] <= day and last != day:
        interval = INTERVALS[min(stage, len(INTERVALS) - 1)]
        stage = min(stage + 1, len(INTERVALS))
    else:
        # Extra practice cannot shorten a future interval or promote it twice.
        return dict(stage=stage, due_day=previous['due_day'], last_success_day=last)
    return dict(stage=stage, due_day=(today + timedelta(days=interval)).isoformat(),
                last_success_day=day)


def review_plan(rows, deck, day):
    relevant = sorted((dict(r) for r in rows if r['deck'] == deck),
                      key=lambda r: (r['due_day'], r['word']))
    due = [r['word'] for r in relevant if r['due_day'] <= day]
    future = [r['due_day'] for r in relevant if r['due_day'] > day]
    return dict(due_words=due, due_count=len(due), next_day=min(future, default=None))
