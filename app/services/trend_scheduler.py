"""Run current-period AI trend refreshes on startup and every morning."""
from datetime import datetime, time, timedelta
import logging
import threading

from app.config import load_config
from app.db import connect
from app.services import trends

logger = logging.getLogger(__name__)
PERIODS = ('week', 'month', 'year')
_stop = threading.Event()
_thread = None


def next_refresh(now, refresh_time):
    """Return the next configured refresh instant in the local trend timezone."""
    hour, minute = map(int, refresh_time.split(':'))
    candidate = datetime.combine(now.date(), time(hour, minute), tzinfo=trends.SHANGHAI)
    return candidate if now < candidate else candidate + timedelta(days=1)


def refresh_periods(periods):
    """Regenerate requested periods independently and return those that failed."""
    with connect() as db:
        actor = db.execute('SELECT id FROM users WHERE is_admin=1 AND is_active=1 ORDER BY is_superadmin DESC,id LIMIT 1').fetchone()
    if actor is None:
        logger.error('AI trends were not refreshed: no active administrator exists')
        return list(periods)
    failed = []
    for period in periods:
        try:
            with connect() as db:
                report = trends.generate(db, actor['id'], period=period)
            logger.info('Refreshed %s AI trend report (%s)', period, report['period_key'])
        except Exception:
            logger.exception('Failed to refresh %s AI trend report', period)
            failed.append(period)
    return failed


def refresh_all():
    """Regenerate each current period independently and retain successful results."""
    return refresh_periods(PERIODS)


def _run(refresh_time, retry_interval_minutes):
    failed = refresh_all()
    while not _stop.is_set():
        if failed:
            delay = retry_interval_minutes * 60
        else:
            now = datetime.now(trends.SHANGHAI)
            delay = max(1, (next_refresh(now, refresh_time) - now).total_seconds())
        if _stop.wait(delay):
            return
        failed = refresh_periods(failed) if failed else refresh_all()


def start():
    """Start a single background worker when automatic refresh is enabled."""
    global _thread
    cfg = load_config()['trends']
    if not cfg['auto_refresh']:
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, args=(cfg['refresh_time'], cfg['retry_interval_minutes']),
                               name='ai-trend-refresh', daemon=True)
    _thread.start()


def stop():
    """Stop the refresh worker when the application shuts down."""
    _stop.set()
