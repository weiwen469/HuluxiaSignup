import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


if __name__ == "__main__":
    try:
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", ""),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", ""),
            port=int(os.getenv("DB_PORT", "3306") or "3306"),
            charset="utf8mb4",
            use_unicode=True,
        )
        print("数据库连接成功！")
        conn.close()
    except Exception as e:
        print(f"数据库连接失败：{e}")
