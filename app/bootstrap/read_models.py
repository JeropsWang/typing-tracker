"""Detached read models. No UI read performs SQL or blocks on a worker."""
from copy import deepcopy
from datetime import datetime
import json
import threading
from ..modules.reporting.api import QueryCache
from ..modules.english.api import review_plan

TABLES = {
 'profile': ('settings',),
 'growth': ('lifetime','rewards','checkin_log','achievements','settings'),
 'tracking': ('lifetime','daily_stats','minute_stats','settings'),
 'practice': ('challenge_history','ai_texts','keyboard_warrior_history'),
 'english': ('english_progress','english_sentences','english_review_schedule'),
}

class ReadModels:
    def __init__(self):
        self._tables={}
        self._settings={}
        self._daily={}
        self._minutes_by_day={}
        self._hours_by_day={}
        self._versions={}
        self._lock=threading.RLock()
        self._reports=QueryCache()

    def replace(self,tables):
        prepared={name:tuple(dict(row) for row in rows) for name,rows in tables.items()}
        settings={r['key']:r['value'] for r in prepared['settings']} if 'settings' in prepared else None
        daily={r['date']:r for r in prepared['daily_stats']} if 'daily_stats' in prepared else None
        minutes=None
        hours=None
        if 'minute_stats' in prepared:
            minutes={}
            hours={}
            for row in prepared['minute_stats']:
                minutes.setdefault(row['date'],[]).append(row)
                key=(row['date'],row['minute'][:2])
                bucket=hours.setdefault(key,[0,0,0])
                for i,column in enumerate(('typed_chars','deleted_chars','total_tw')):
                    bucket[i]+=row[column]
        with self._lock:
            for name,rows in prepared.items():
                self._tables[name]=rows
                self._versions[name]=self._versions.get(name,0)+1
            if settings is not None:
                self._settings=settings
            if daily is not None:
                self._daily=daily
            if minutes is not None:
                self._minutes_by_day=minutes
                self._hours_by_day=hours
            if 'daily_stats' in prepared or 'minute_stats' in prepared:
                self._reports.clear()

    def rows(self,table):
        with self._lock:
            rows=self._tables.get(table,())
        return tuple(dict(row) for row in rows)

    def get_setting(self,key,default=None):
        with self._lock:
            return self._settings.get(key,default)
    def settings(self):
        with self._lock:
            return dict(self._settings)
    def get_lifetime(self):
        return next(iter(self.rows('lifetime')),None)
    def get_exp(self):
        return (self.get_lifetime() or {}).get('total_exp',0)
    def get_daily(self,day):
        with self._lock:
            row=self._daily.get(day)
            return dict(row) if row else None
    def get_daily_range(self,start,end):
        return sorted((r for r in self.rows('daily_stats') if start<=r['date']<=end),key=lambda r:r['date'])
    def get_recent_days(self,n):
        return sorted(self.rows('daily_stats'),key=lambda r:r['date'],reverse=True)[:n]
    def get_minutes(self,day):
        with self._lock:
            rows=self._minutes_by_day.get(day,())
        return sorted((dict(r) for r in rows),key=lambda r:r['minute'])
    def _cached(self,kind,start,end,load):
        with self._lock:
            key=(kind,start,end,self._versions.get('daily_stats',0),self._versions.get('minute_stats',0))
            return self._reports.get(key,load)
    def get_summary(self,start,end):
        def load():
            days=self.get_daily_range(start,end)
            typed=sum(r['typed_chars'] for r in days)
            deleted=sum(r['deleted_chars'] for r in days)
            valid=sum(r['valid_chars'] for r in days)
            tw=sum(r['total_tw'] for r in days)
            minutes=sum(r['active_minutes'] for r in days)
            return dict(typed=typed,deleted=deleted,valid=valid,tw=tw,minutes=minutes,
                        avg_speed=tw/minutes if minutes else None,accuracy=valid/typed if typed else None)
        return self._cached('summary',start,end,load)
    def get_heatmap(self,start,end):
        return self._cached('heatmap',start,end,lambda:{r['date']:r['total_tw'] for r in self.get_daily_range(start,end)})
    def get_hourly_stats(self,start,end):
        def load():
            with self._lock:
                buckets=dict(self._hours_by_day)
            hours={}
            for (day,hour),values in buckets.items():
                if start<=day<=end:
                    target=hours.setdefault(hour,dict(hour=hour,typed=0,deleted=0,tw=0))
                    for key,value in zip(('typed','deleted','tw'),values):
                        target[key]+=value
            return [hours[h] for h in sorted(hours)]
        return self._cached('hours',start,end,load)
    def get_minute_quality(self,start,end,min_typed=30):
        return [r for r in self.rows('minute_stats') if start<=r['date']<=end and r['typed_chars']>=min_typed]
    def get_checkins(self,start,end):
        return {r['date']:r for r in self.rows('checkin_log') if start<=r['date']<=end}
    def get_streak(self,day):
        return self.get_checkins(day,day).get(day,{}).get('streak',0)
    def has_checkin(self,day):
        return day in self.get_checkins(day,day)
    def get_achievements(self):
        return list(self.rows('achievements'))
    def get_achievement(self,code):
        return next((r for r in self.rows('achievements') if r['code']==code),None)
    def has_achievement(self,code):
        return self.get_achievement(code) is not None
    def list_rewards(self,unused_only=False):
        return [r for r in self.rows('rewards') if not unused_only or r['used_at'] is None]
    def count_ai_passes(self):
        return sum(r['qty'] for r in self.list_rewards(True) if r['kind']=='ai_pass')
    def list_ai_texts(self):
        return sorted(self.rows('ai_texts'),key=lambda r:r['id'],reverse=True)
    def get_best_challenge(self,text_id):
        return next(iter(sorted((r for r in self.rows('challenge_history') if r['text_id']==text_id),key=lambda r:(r['best'],r['accuracy']),reverse=True)),None)
    def get_recent_challenges(self,n=10):
        return sorted(self.rows('challenge_history'),key=lambda r:r['id'],reverse=True)[:n]
    def get_challenge_leaderboard(self,text_id,n=10):
        return sorted((r for r in self.rows('challenge_history') if r['text_id']==text_id and r['score']>0 and r['elapsed_seconds']>0),key=lambda r:(-r['score'],-r['accuracy'],r['elapsed_seconds'],-r['id']))[:max(1,min(50,int(n)))]
    def keyboard_warrior_leaderboard(self,limit=10):
        rows=sorted(self.rows('keyboard_warrior_history'),key=lambda r:(-r['speed'],r['created_at'],r['id']))[:limit]
        return [dict(r,rank=i+1) for i,r in enumerate(rows)]
    @property
    def english(self):
        return EnglishQueries(self)

class EnglishQueries:
    def __init__(self,models):
        self.models=models
    def review_keys(self,deck):
        return {r['word'] for r in self.models.rows('english_progress') if r['deck']==deck and r['needs_review']}
    def review_plan(self,deck,day):
        return review_plan(self.models.rows('english_review_schedule'),deck,day)
    def summary(self,deck):
        rows=[r for r in self.models.rows('english_progress') if r['deck']==deck]
        attempts=sum(r['attempts'] for r in rows)
        independent=sum(r['independent_correct'] for r in rows)
        return dict(trained=len(rows),attempts=attempts,independent_correct=independent,
                    review_count=sum(r['needs_review'] for r in rows),accuracy=independent/attempts if attempts else None)
    def sentence_history(self,deck,limit=20):
        rows=sorted((r for r in self.models.rows('english_sentences') if r['deck']==deck),key=lambda r:r['id'],reverse=True)[:limit]
        for r in rows:
            r['words']=json.loads(r.pop('words_json'))
            r['sentences']=json.loads(r.pop('sentences_json'))
        return rows
