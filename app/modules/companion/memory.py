"""用户与开发者记忆页共用的只读快照，来源仅为显式兴趣和已提交来信。"""
from dataclasses import dataclass
from .news import NewsConfig, NewsTask


@dataclass(frozen=True)
class MemorySnapshot:
    """脱离数据库的同一份记忆数据；更新时间与 revision 来自真实提交。"""
    config: NewsConfig = NewsConfig()
    tasks: tuple[NewsTask, ...] = ()
    updated_at: str = ''
    revision: int = 0
    error: str = ''

    @property
    def reports(self) -> tuple[NewsTask, ...]:
        """仅返回未删除且确有已提交报告的终态记录，内存草稿不计入保存数量。"""
        visible = (item for item in self.tasks if item.state == 'completed' and item.report is not None and not item.deleted_at)
        return tuple(sorted(visible, key=lambda item: (item.finished_at, item.created_at, item.task_id), reverse=True))
