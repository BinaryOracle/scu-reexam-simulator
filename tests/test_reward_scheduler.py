"""A failing weekly board cannot prevent independent contest settlement."""
from contextlib import nullcontext
from unittest.mock import Mock


def test_scheduler_checks_contests_even_when_weekly_settlement_fails(monkeypatch):
    from app.services import leaderboard_scheduler as scheduler
    event = Mock()
    event.is_set.return_value = False
    event.wait.return_value = True
    db = Mock()
    called = []
    def weekly(db):
        called.append('weekly')
        raise RuntimeError('weekly unavailable')
    def contest(db):
        called.append('contest')
    monkeypatch.setattr(scheduler, '_stop', event)
    monkeypatch.setattr(scheduler, 'connect', lambda: nullcontext(db))
    monkeypatch.setattr(scheduler.leaderboard, 'settle_due', weekly)
    monkeypatch.setattr(scheduler.contest_rewards, 'settle_due', contest)
    scheduler._run()
    assert called == ['weekly', 'contest']
    assert db.execute.call_count == 2
