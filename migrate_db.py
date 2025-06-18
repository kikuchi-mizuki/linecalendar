import sqlite3
import os

for db_path in ["calendar_bot.db", "instance/calendar.db"]:
    if os.path.exists(db_path):
        print(f"=== {db_path} ===")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(pending_events);")
        columns = [row[1] for row in cursor.fetchall()]
        print("columns:", columns)
        if "event_info" not in columns:
            try:
                cursor.execute("ALTER TABLE pending_events ADD COLUMN event_info TEXT;")
                print("event_infoカラムを追加しました。")
                conn.commit()
            except Exception as e:
                print("エラー:", e)
        else:
            print("event_infoカラムは既に存在します。")
        if "updated_at" not in columns:
            try:
                cursor.execute("ALTER TABLE pending_events ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
                print("updated_atカラムを追加しました。")
                conn.commit()
            except Exception as e:
                print("エラー:", e)
        else:
            print("updated_atカラムは既に存在します。")
        conn.close()
    else:
        print(f"{db_path} は存在しません。")

# pending_eventsテーブルの全データを出力
try:
    conn = sqlite3.connect("calendar_bot.db")
    cursor = conn.cursor()
    print("=== pending_events全件 ===")
    for row in cursor.execute("SELECT * FROM pending_events"):
        print(row)
    conn.close()
except Exception as e:
    print("pending_events全件出力エラー:", e) 