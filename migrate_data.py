import sqlite3

OLD_DB = "fans_trend_backup.db"
NEW_DB = "fans_trend.db"

def migrate():
    # 连接旧数据库和新数据库
    old_conn = sqlite3.connect(OLD_DB)
    old_cursor = old_conn.cursor()
    
    new_conn = sqlite3.connect(NEW_DB)
    new_cursor = new_conn.cursor()

    try:
        # 从旧库读取所有历史粉丝数据
        old_cursor.execute("SELECT date, name, followers FROM trends")
        rows = old_cursor.fetchall()
        
        # 插入到新库中 (用 INSERT OR IGNORE 防止日期和名字重复导致报错)
        for row in rows:
            new_cursor.execute(
                "INSERT OR IGNORE INTO trends (date, name, followers) VALUES (?, ?, ?)", 
                row
            )
        new_conn.commit()
        print(f"✅ 成功迁移了 {len(rows)} 条历史粉丝数据！")
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
    finally:
        old_conn.close()
        new_conn.close()

if __name__ == "__main__":
    migrate()