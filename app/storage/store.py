"""SQLite adapter shared by module-owned repositories. No business rules or commits."""
class Store:
    def __init__(self, conn):
        self._conn = conn
