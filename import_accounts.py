import csv
import os
import sys

import pymysql
from dotenv import load_dotenv

load_dotenv()

DEFAULT_FILES = ["accounts.csv", "accounts1.csv"]

CSV_COLUMNS = {
    "phone": "手机号",
    "password": "密码",
    "user_id": "UserID",
    "auth_key": "Key",
}


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", ""),
        port=int(os.getenv("DB_PORT", "3306") or "3306"),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", ""),
        charset="utf8mb4",
        autocommit=True,
    )


def ensure_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            phone VARCHAR(64) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            auth_key VARCHAR(255) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def main():
    files = sys.argv[1:] or DEFAULT_FILES
    conn = get_connection()
    total = 0
    try:
        cursor = conn.cursor()
        ensure_table(cursor)
        for path in files:
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    phone = (row.get(CSV_COLUMNS["phone"]) or "").strip()
                    password = (row.get(CSV_COLUMNS["password"]) or "").strip()
                    user_id = (row.get(CSV_COLUMNS["user_id"]) or "").strip()
                    auth_key = (row.get(CSV_COLUMNS["auth_key"]) or "").strip()
                    if not phone:
                        continue
                    cursor.execute(
                        """
                        INSERT INTO accounts
                            (phone, password, user_id, auth_key)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            password = VALUES(password),
                            user_id = VALUES(user_id),
                            auth_key = VALUES(auth_key)
                        """,
                        (phone, password, user_id, auth_key),
                    )
                    total += 1
        print(f"已处理 {total} 条账号记录")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
