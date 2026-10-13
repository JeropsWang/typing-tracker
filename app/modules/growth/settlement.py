"""Reward settlement is owned by growth and joins the caller's transaction."""
from datetime import datetime

class RewardLedger:
    def __init__(self, repo, balance):
        self.repo, self.balance = repo, balance

    def _state(self, day):
        conn = self.repo._conn
        conn.execute('INSERT OR IGNORE INTO growth_daily(date) VALUES(?)', (day,))
        return dict(conn.execute('SELECT * FROM growth_daily WHERE date=?', (day,)).fetchone())

    def typing(self, day, valid_chars, now):
        state = self._state(day)
        cfg = self.balance.get('typing_exp', {})
        blocks = valid_chars // 1000
        # A legacy database introduced after migration may still have settings baselines.
        if self.repo.get_setting('typing_exp_date') == day:
            state['typing_blocks'] = max(state['typing_blocks'], int(self.repo.get_setting('typing_exp_blocks', '0') or 0))
            state['typing_exp'] = max(state['typing_exp'], int(self.repo.get_setting('typing_exp_today', '0') or 0))
        gained = max(0, blocks - state['typing_blocks']) * cfg.get('per_1000_valid', 0)
        raw = self.repo.get_setting('exp_boost_until', '')
        try:
            boost = bool(raw and datetime.fromisoformat(raw) > now)
        except ValueError:
            boost = False
        if boost:
            gained *= 2
        grant = min(gained, max(0, cfg.get('daily_cap', 0) - state['typing_exp']))
        highest = max(blocks, state['typing_blocks'])
        if highest == state['typing_blocks'] and not grant:
            return 0
        self.repo._conn.execute('UPDATE growth_daily SET typing_blocks=?,typing_exp=? WHERE date=?',
                                (highest, state['typing_exp'] + grant, day))
        if grant:
            self.repo.add_exp(grant)
            self.repo.add_exp_to_daily(day, grant)
        self.repo.set_settings({'typing_exp_date': day, 'typing_exp_blocks': highest,
                                'typing_exp_today': state['typing_exp'] + grant})
        return grant

    def challenge(self, day, base):
        state = self._state(day)
        cfg = self.balance.get('challenge_exp', {})
        if self.repo.get_setting('challenge_exp_date') == day:
            state['challenge_exp'] = max(state['challenge_exp'], int(self.repo.get_setting('challenge_exp_today', '0') or 0))
        grant = max(0, min(int(base * cfg.get('per_base_point', 1)), int(cfg.get('daily_cap', 200)) - state['challenge_exp']))
        self.repo._conn.execute('UPDATE growth_daily SET challenge_exp=? WHERE date=?', (state['challenge_exp'] + grant, day))
        if grant:
            self.repo.add_exp(grant)
            self.repo.add_exp_to_daily(day, grant)
        self.repo.set_settings({'challenge_exp_date': day, 'challenge_exp_today': state['challenge_exp'] + grant})
        return grant
