"""Cross-module material saving: growth spends, practice owns content."""
from ..modules.growth.api import level_and_progress

def save_passage(repo,balance,lang,topic,text,*,operation_id,test_mode=False):
    """跨成长/训练模块原子保存主动生成材料并消费训练券，重试沿用稳定操作 ID。"""
    if not text.strip():
        raise ValueError('生成内容为空，未使用训练券。')
    def save():
        """在事务内重新核对等级/券资格，再写材料，失败会一起回滚消费。"""
        level,_,_=level_and_progress(repo.get_exp(),balance)
        if level<balance.get('ai',{}).get('unlock_level',45) and not test_mode:
            if not repo.use_reward('ai_pass'):
                raise ValueError('AI 训练券不足，生成内容未保存。')
        return repo.add_ai_text(lang,topic,text)
    return repo.operation('practice.material',operation_id,save)
