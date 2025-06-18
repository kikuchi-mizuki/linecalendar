import sqlite3
import os

# デフォルトのDBパス
DB_PATH = os.environ.get("DB_PATH", "calendar_bot.db")

print(f"[migrate_db.py] DBファイル: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
try:
    # event_infoカラムがなければ追加
    cursor.execute("PRAGMA table_info(pending_events);")
    columns = [row[1] for row in cursor.fetchall()]
    if "event_info" not in columns:
        cursor.execute("ALTER TABLE pending_events ADD COLUMN event_info TEXT;")
        print("event_infoカラムを追加しました。")
    else:
        print("event_infoカラムは既に存在します。")
    conn.commit()
except Exception as e:
    print("エラー:", e)
finally:
    conn.close() 