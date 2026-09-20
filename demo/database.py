"""Small connection boundary for SQLite tests and a PostgreSQL-backed demo."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        # Queries are static application SQL; values remain driver-bound parameters.
        return self.connection.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql, rows):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), rows)


@contextmanager
def connect(database):
    if str(database).startswith(("postgresql://", "postgres://")):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(str(database), row_factory=dict_row, connect_timeout=5) as connection:
            yield PostgresConnection(connection)
    else:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()
