import sqlite3
for db_path in ['local_aviation.db', 'backend/aviation_mro.db']:
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(engines)').fetchall()]
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f'DB: {db_path}')
    print(f'  Tables: {tables}')
    print(f'  Engine cols: {cols}')
    conn.close()
