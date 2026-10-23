"""Detached read models. No UI read performs SQL or blocks on a worker."""
from copy import deepcopy
from datetime import datetime
import json
import threading
from ..modules.reporting.api import QueryCache
from ..modules.english.api import review_plan
from ..modules.companion.api import NewsConfig, MemorySnapshot, task_from_row

TABLES = {
 'profile': ('settings',),
 'growth': ('lifetime','rewards','checkin_log','achievements','settings'),
 'tracking': ('lifetime','daily_stats','minute_stats','settings'),
 'practice': ('challenge_history','ai_texts','keyboard_warrior_history'),
 'english': ('english_progress','english_sentences','english_review_schedule'),
 'companion': ('companion_news_tasks',),
}

class ReadModels:
    """跨线程可读的数据库脱离快照，带索引、表版本和有界报表缓存；不执行 SQL。"""
    def __init__(self):
        """初始化表/设置/日分钟索引、版本、锁和报表缓存。"""
        self._tables={}
        self._settings={}
        self._daily={}
        self._minutes_by_day={}
        self._hours_by_day={}
        self._versions={}
        self._lock=threading.RLock()
        self._reports=QueryCache()

    def news_snapshot(self):
        """原子捕获设置与来信表副本，返回两个记忆视角共用的无连接不可变模型。"""
        with self._lock:
            values = dict(self._settings)
            rows = tuple(dict(row) for row in self._tables.get('companion_news_tasks', ()))
        error = ''
        try:
            config = NewsConfig.from_values(values)
        except (TypeError, ValueError):
            config, error = NewsConfig(), '来信配置格式不正确，请重新保存兴趣与时间。'
        try:
            revision = max(0, int(values.get('companion_news_revision', '0')))
        except (TypeError, ValueError):
            revision = 0
        return MemorySnapshot(config, tuple(task_from_row(row) for row in rows),
                               values.get('companion_news_updated_at', ''), revision, error)

    def replace(self,tables):
        """先构建独立行及聚合索引，再持锁替换变化表并失效相关报表缓存。"""
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
        """在锁内捕获表版本并返回行字典副本，调用方修改不污染模型。"""
        with self._lock:
            rows=self._tables.get(table,())
        return tuple(dict(row) for row in rows)

    def get_setting(self,key,default=None):
        """从设置索引读取单键值，不存在时返回默认值。"""
        with self._lock:
            return self._settings.get(key,default)
    def settings(self):
        """返回同一已发布版本的完整设置字典副本。"""
        with self._lock:
            return dict(self._settings)
    def get_lifetime(self):
        """取得已发布终身统计副本，无记录返回 None。"""
        return next(iter(self.rows('lifetime')),None)
    def get_exp(self):
        """从终身快照取得经验，尚无数据时为零。"""
        return (self.get_lifetime() or {}).get('total_exp',0)
    def get_daily(self,day):
        """从日期索引取得当日统计副本。"""
        with self._lock:
            row=self._daily.get(day)
            return dict(row) if row else None
    def get_daily_range(self,start,end):
        """筛选包含起止日期的日统计副本并按日期排序。"""
        return sorted((r for r in self.rows('daily_stats') if start<=r['date']<=end),key=lambda r:r['date'])
    def get_recent_days(self,n):
        """从已发布行按日期倒序取得最近 n 天。"""
        return sorted(self.rows('daily_stats'),key=lambda r:r['date'],reverse=True)[:n]
    def get_minutes(self,day):
        """从应用日索引取得独立分钟行并按分钟排序。"""
        with self._lock:
            rows=self._minutes_by_day.get(day,())
        return sorted((dict(r) for r in rows),key=lambda r:r['minute'])
    def _cached(self,kind,start,end,load):
        """把统计表版本加入缓存键，避免旧范围汇总在更新后继续命中。"""
        with self._lock:
            key=(kind,start,end,self._versions.get('daily_stats',0),self._versions.get('minute_stats',0))
            return self._reports.get(key,load)
    def get_summary(self,start,end):
        """按日期范围取得计数/tw/速度/准确率汇总，命中时返回独立缓存结果。"""
        def load():
            """从日行累加区间数值，按总有效字数/总输入及总 tw/总分钟计算比例。"""
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
        """取得范围内日期到 tw 的映射，缓存随统计版本失效。"""
        return self._cached('heatmap',start,end,lambda:{r['date']:r['total_tw'] for r in self.get_daily_range(start,end)})
    def get_hourly_stats(self,start,end):
        """取得范围内按小时累计的字数/删除/tw，复用预聚合索引。"""
        def load():
            """捕获小时桶快照并按日期范围累加同小时数值，不访问 SQL。"""
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
        """筛选输入达到阈值的分钟样本，供质量成就规则使用。"""
        return [r for r in self.rows('minute_stats') if start<=r['date']<=end and r['typed_chars']>=min_typed]
    def get_checkins(self,start,end):
        """返回指定日期区间的打卡字典。"""
        return {r['date']:r for r in self.rows('checkin_log') if start<=r['date']<=end}
    def get_streak(self,day):
        """从指定日已发布打卡记录取得连签数，缺失时为零。"""
        return self.get_checkins(day,day).get(day,{}).get('streak',0)
    def has_checkin(self,day):
        """判断指定应用日是否存在已发布的打卡记录。"""
        return day in self.get_checkins(day,day)
    def get_achievements(self):
        """取得成就状态列表副本，供定义合并与展示。"""
        return list(self.rows('achievements'))
    def get_achievement(self,code):
        """按成就代码找到状态副本，无记录为 None。"""
        return next((r for r in self.rows('achievements') if r['code']==code),None)
    def has_achievement(self,code):
        """判断指定成就是否有解锁记录。"""
        return self.get_achievement(code) is not None
    def list_rewards(self,unused_only=False):
        """取得库存副本，可筛选未使用记录。"""
        return [r for r in self.rows('rewards') if not unused_only or r['used_at'] is None]
    def count_ai_passes(self):
        """按库存数量合计未使用训练券，不把每行当成一张。"""
        return sum(r['qty'] for r in self.list_rewards(True) if r['kind']=='ai_pass')
    def list_ai_texts(self):
        """按材料 ID 倒序返回主动生成材料的展示副本。"""
        return sorted(self.rows('ai_texts'),key=lambda r:r['id'],reverse=True)
    def get_best_challenge(self,text_id):
        """从已发布训练记录找到同范文最佳比较基线。"""
        return next(iter(sorted((r for r in self.rows('challenge_history') if r['text_id']==text_id),key=lambda r:(r['best'],r['accuracy']),reverse=True)),None)
    def get_recent_challenges(self,n=10):
        """按 ID 倒序取得最近训练行，不访问数据库。"""
        return sorted(self.rows('challenge_history'),key=lambda r:r['id'],reverse=True)[:n]
    def get_challenge_leaderboard(self,text_id,n=10):
        """筛选有完整单次评分的记录，按分数/准确率/用时排序并限制数量。"""
        return sorted((r for r in self.rows('challenge_history') if r['text_id']==text_id and r['score']>0 and r['elapsed_seconds']>0),key=lambda r:(-r['score'],-r['accuracy'],r['elapsed_seconds'],-r['id']))[:max(1,min(50,int(n)))]
    def keyboard_warrior_leaderboard(self,limit=10):
        """按键盘侠速度及稳定并列规则排序，并附一开始的名次。"""
        rows=sorted(self.rows('keyboard_warrior_history'),key=lambda r:(-r['speed'],r['created_at'],r['id']))[:limit]
        return [dict(r,rank=i+1) for i,r in enumerate(rows)]
    @property
    def english(self):
        """建立针对本模型的只读英语查询适配器。"""
        return EnglishQueries(self)

class EnglishQueries:
    """只使用已发布学习数据的英语查询适配器，不持有数据库连接。"""
    def __init__(self,models):
        """持有只读展示模型，用于词库进度、复习与材料历史查询。"""
        self.models=models
    def review_keys(self,deck):
        """返回指定词库仍需复习的单词键集合。"""
        return {r['word'] for r in self.models.rows('english_progress') if r['deck']==deck and r['needs_review']}
    def review_plan(self,deck,day):
        """使用已发布排期和显式应用日计算到期复习计划。"""
        return review_plan(self.models.rows('english_review_schedule'),deck,day)
    def summary(self,deck):
        """汇总指定词库训练次数、独立正确、错词数量和独立作答准确率。"""
        rows=[r for r in self.models.rows('english_progress') if r['deck']==deck]
        attempts=sum(r['attempts'] for r in rows)
        independent=sum(r['independent_correct'] for r in rows)
        return dict(trained=len(rows),attempts=attempts,independent_correct=independent,
                    review_count=sum(r['needs_review'] for r in rows),accuracy=independent/attempts if attempts else None)
    def sentence_history(self,deck,limit=20):
        """取指定词库最近造句材料并解码 JSON 到独立展示字段。"""
        rows=sorted((r for r in self.models.rows('english_sentences') if r['deck']==deck),key=lambda r:r['id'],reverse=True)[:limit]
        for r in rows:
            r['words']=json.loads(r.pop('words_json'))
            r['sentences']=json.loads(r.pop('sentences_json'))
        return rows
