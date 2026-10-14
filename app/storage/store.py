"""SQLite adapter shared by module-owned repositories. No business rules or commits."""
class Store:
    """仅由所属应用线程使用的仓储连接基类，不承担事务提交。"""
    def __init__(self, conn):
        """保存外部装配的 SQLite 连接，连接生命周期由应用工作线程管理。"""
        self._conn = conn
