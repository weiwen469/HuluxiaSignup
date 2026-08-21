import os
import time
import sqlite3
import logging
from dataclasses import dataclass
from typing import Optional, Any

import Haozhu
import Hu_api

from dotenv import load_dotenv

load_dotenv()
# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================

@dataclass(frozen=True)
class Config:

    # ========================================================
    # 好主 SID
    # ========================================================

    sid: int = int(
        os.getenv("HAOZHU_SID", "21272")
    )

    # ========================================================
    # 好主 Token
    #
    # 本地：
    #   set HAOZHU_TOKEN=xxx
    #
    # GitHub Actions：
    #   secrets.HAOZHU_TOKEN
    # ========================================================

    haozhu_token: str = os.getenv(
        "HAOZHU_TOKEN",
        ""
    )

    # ========================================================
    # 注册账号默认密码
    # ========================================================

    account_password: str = os.getenv(
        "ACCOUNT_PASSWORD",
        "qweqwe123"
    )

    # ========================================================
    # 短信最大等待时间
    # ========================================================

    sms_timeout: int = int(
        os.getenv("SMS_TIMEOUT", "30")
    )

    # ========================================================
    # 短信查询间隔
    # ========================================================

    poll_interval: float = float(
        os.getenv("POLL_INTERVAL", "1")
    )

    # ========================================================
    # 最低余额
    # ========================================================

    min_balance: float = float(
        os.getenv("MIN_BALANCE", "0")
    )

    # ========================================================
    # 每次运行注册几个账号
    # ========================================================

    register_count: int = int(
        os.getenv("REGISTER_COUNT", "1")
    )

    # ========================================================
    # 账号数据库文件
    # ========================================================

    accounts_db: str = os.getenv(
        "ACCOUNTS_DB",
        "accounts.db"
    )

    # ========================================================
    # MySQL 数据库
    # ========================================================

    db_host: str = os.getenv("DB_HOST", "")
    db_port: int = int(os.getenv("DB_PORT", "3306") or "3306")
    db_name: str = os.getenv("DB_NAME", "")
    db_user: str = os.getenv("DB_USER", "")
    db_password: str = os.getenv("DB_PASSWORD", "")


# ============================================================
# 账号注册器
# ============================================================

class AccountRegistrar:

    def __init__(self, config: Config):

        self.config = config

        # 好主 Token
        self.token = config.haozhu_token

        # 当前手机号
        self.phone: Optional[str] = None

        if not self.token:
            raise RuntimeError(
                "HAOZHU_TOKEN 未配置"
            )

    # ========================================================
    # 工具方法
    # ========================================================

    @staticmethod
    def is_dict(data: Any) -> bool:
        return isinstance(data, dict)

    # ========================================================
    # 获取 Ticket
    # ========================================================

    def get_ticket(self) -> dict:

        logger.debug(
            "正在获取验证码 Ticket..."
        )

        try:

            result = Hu_api.getticket()

        except Exception as e:

            raise RuntimeError(
                f"获取 Ticket 请求异常: {e}"
            ) from e

        if not self.is_dict(result):

            raise RuntimeError(
                f"getticket 返回格式错误: {result}"
            )

        ticket = result.get("ticket")
        randstr = result.get("randstr")

        if not ticket:

            raise RuntimeError(
                f"Ticket 不存在: {result}"
            )

        if not randstr:

            raise RuntimeError(
                f"randstr 不存在: {result}"
            )

        logger.debug(
            "Ticket 获取成功"
        )

        return {
            "ticket": ticket,
            "randstr": randstr
        }

    # ========================================================
    # 查询余额
    # ========================================================

    def check_balance(self) -> float:

        logger.debug(
            "正在查询接码平台余额..."
        )

        try:

            money = Haozhu.Getmoney(
                token=self.token
            )

            balance = float(money)

        except (ValueError, TypeError) as e:

            raise RuntimeError(
                f"获取余额失败: {e}"
            ) from e

        except Exception as e:

            raise RuntimeError(
                f"查询余额请求异常: {e}"
            ) from e

        logger.debug(
            "当前接码平台余额: %.4f",
            balance
        )

        if balance <= self.config.min_balance:

            raise RuntimeError(
                f"余额不足，当前余额: {balance}"
            )

        return balance

    # ========================================================
    # 获取手机号
    # ========================================================

    def get_phone(self) -> str:

        logger.debug(
            "正在获取临时手机号..."
        )

        logger.debug(
            "SID: %s",
            self.config.sid
        )

        try:

            phone = Haozhu.getPhone(
                token=self.token,
                sid=self.config.sid
            )

        except Exception as e:

            raise RuntimeError(
                f"获取手机号请求异常: {e}"
            ) from e

        if not phone:

            raise RuntimeError(
                "获取手机号失败"
            )

        self.phone = str(phone)

        logger.debug(
            "获取手机号成功: %s",
            self.phone
        )

        return self.phone

    # ========================================================
    # 发送短信
    # ========================================================

    def send_sms(self, ticket: dict):

        if not self.phone:

            raise RuntimeError(
                "手机号不存在"
            )

        logger.debug(
            "正在发送短信验证码..."
        )

        try:

            result = Hu_api.sendSMSmessage(
                ticket=ticket["ticket"],
                rand=ticket["randstr"],
                phone=self.phone
            )

        except Exception as e:

            raise RuntimeError(
                f"发送短信请求异常: {e}"
            ) from e

        if not self.is_dict(result):

            raise RuntimeError(
                f"发送短信返回格式错误: {result}"
            )

        if result.get("status") != 1:

            raise RuntimeError(
                f"发送短信失败: {result}"
            )

        logger.debug(
            "短信发送成功"
        )

        return result

    # ========================================================
    # 等待验证码
    # ========================================================

    def wait_sms_code(self) -> str:

        if not self.phone:

            raise RuntimeError(
                "手机号不存在"
            )

        logger.debug(
            "开始等待短信验证码..."
        )

        logger.debug(
            "超时时间: %s 秒",
            self.config.sms_timeout
        )

        logger.debug(
            "查询间隔: %.1f 秒",
            self.config.poll_interval
        )

        start_time = time.monotonic()

        attempt = 0

        while True:

            attempt += 1

            elapsed = (
                time.monotonic() - start_time
            )

            # ------------------------------------------------
            # 超时
            # ------------------------------------------------

            if elapsed >= self.config.sms_timeout:

                raise TimeoutError(
                    f"等待验证码超时 "
                    f"({self.config.sms_timeout} 秒)"
                )

            try:

                message = Haozhu.getMessage(
                    token=self.token,
                    sid=self.config.sid,
                    phone=self.phone
                )

                logger.debug(
                    "第 %d 次查询验证码: %s",
                    attempt,
                    message
                )

                if message is not None:

                    code = str(message)

                    logger.debug(
                        "获取验证码成功"
                    )

                    return code

            except Exception as e:

                logger.warning(
                    "第 %d 次查询短信异常: %s",
                    attempt,
                    e
                )

            # ------------------------------------------------
            # 等待下一次查询
            # ------------------------------------------------

            remaining = (
                self.config.sms_timeout
                - (time.monotonic() - start_time)
            )

            if remaining <= 0:
                break

            time.sleep(
                min(
                    self.config.poll_interval,
                    remaining
                )
            )

        raise TimeoutError(
            f"等待验证码超时 "
            f"({self.config.sms_timeout} 秒)"
        )

    # ========================================================
    # 验证验证码
    # ========================================================

    def verify_code(self, code: str):

        if not self.phone:

            raise RuntimeError(
                "手机号不存在"
            )

        logger.debug(
            "正在提交验证码..."
        )

        try:

            result = Hu_api.postverify(
                vcode=code,
                phone=self.phone
            )

        except Exception as e:

            raise RuntimeError(
                f"验证码校验请求异常: {e}"
            ) from e

        logger.debug(
            "验证码校验完成"
        )

        # 这里暂时不判断 status，
        # 因为你原来的 Hu_api.postverify 返回格式
        # 目前没有提供具体结构。
        if result is None:

            raise RuntimeError(
                "验证码校验返回为空"
            )

        return result

    # ========================================================
    # 获取账号数据
    # ========================================================

    def get_account_data(
        self,
        code: str
    ) -> dict:

        if not self.phone:

            raise RuntimeError(
                "手机号不存在"
            )

        logger.debug(
            "正在提交账号数据..."
        )

        try:

            data = Hu_api.post_account_data(
                phone=self.phone,
                code=code
            )

        except Exception as e:

            raise RuntimeError(
                f"提交账号数据异常: {e}"
            ) from e

        if not self.is_dict(data):

            raise RuntimeError(
                f"账号数据返回格式错误: {data}"
            )

        logger.debug(
            "账号数据获取成功"
        )

        return data

    # ========================================================
    # 设置密码
    # ========================================================

    def set_password(
        self,
        data: dict
    ) -> dict:

        key = data.get("_key")

        if not key:

            raise RuntimeError(
                f"设置密码失败，缺少 _key: {data}"
            )

        logger.debug(
            "账号需要设置密码"
        )

        try:

            result = Hu_api.setVerify(
                key,
                self.config.account_password
            )

        except Exception as e:

            raise RuntimeError(
                f"设置密码请求异常: {e}"
            ) from e

        if not self.is_dict(result):

            raise RuntimeError(
                f"设置密码返回格式错误: {result}"
            )

        if result.get("status") != 1:

            raise RuntimeError(
                "设置密码失败: "
                f"{result.get('msg', result)}"
            )

        logger.debug(
            "账号密码设置成功"
        )

        return result

    # ========================================================
    # 处理账号
    # ========================================================

    def process_account(
        self,
        data: dict
    ) -> dict:

        need_password = data.get(
            "needSetPassword"
        )

        # ----------------------------------------------------
        # 新账号
        # ----------------------------------------------------

        if need_password == 1:

            self.set_password(data)

            result = {
                "status": "success",
                "message": "注册成功",
                "phone": self.phone,
                "password": self.config.account_password,
                "user_id": data.get("userID"),
                "key": data.get("_key")
            }

            logger.info(
                "注册成功 | 手机号: %s | UserID: %s | 密码: %s",
                self.phone,
                data.get("userID"),
                self.config.account_password,
            )

            return result

        # ----------------------------------------------------
        # 已存在账号
        # ----------------------------------------------------

        if need_password == 0:

            result = {
                "status": "success",
                "message": "登录成功",
                "phone": self.phone,
                "user_id": data.get("userID"),
                "key": data.get("_key")
            }

            logger.info(
                "账号已存在 | 手机号: %s | UserID: %s | Key: %s",
                self.phone,
                data.get("userID"),
                data.get("_key"),
            )

            return result

        # ----------------------------------------------------
        # 未知状态
        # ----------------------------------------------------

        raise RuntimeError(
            data.get(
                "msg",
                f"未知账号状态: {data}"
            )
        )

    # ========================================================
    # 释放手机号
    # ========================================================

    def release_phone(self):

        if not self.phone:
            return

        phone = self.phone

        logger.debug(
            "正在释放手机号: %s",
            phone
        )

        try:

            result = Haozhu.cancelRecv(
                token=self.token,
                sid=self.config.sid,
                phone=phone
            )

            logger.debug(
                "释放手机号结果: %s",
                result
            )

        except Exception as e:

            # 释放手机号失败不能覆盖原来的异常
            logger.error(
                "释放手机号失败: %s",
                e
            )

        finally:

            self.phone = None

    # ========================================================
    # 注册主流程
    # ========================================================

    def register(self) -> dict:

        start_time = time.monotonic()

        try:

            # ------------------------------------------------
            # 1. 获取 Ticket
            # ------------------------------------------------

            ticket = self.get_ticket()

            # ------------------------------------------------
            # 2. 检查余额
            # ------------------------------------------------

            self.check_balance()

            # ------------------------------------------------
            # 3. 获取手机号
            # ------------------------------------------------

            self.get_phone()

            # ------------------------------------------------
            # 4. 发送短信
            # ------------------------------------------------

            self.send_sms(ticket)

            # ------------------------------------------------
            # 5. 等待验证码
            # ------------------------------------------------

            code = self.wait_sms_code()

            # ------------------------------------------------
            # 6. 验证验证码
            # ------------------------------------------------

            self.verify_code(code)

            # ------------------------------------------------
            # 7. 获取账号数据
            # ------------------------------------------------

            data = self.get_account_data(code)

            # ------------------------------------------------
            # 8. 注册 / 登录
            # ------------------------------------------------

            result = self.process_account(data)

            return result

        except Exception:
            raise

        finally:

            # ------------------------------------------------
            # 无论成功还是失败
            # 都释放手机号
            # ------------------------------------------------

            self.release_phone()

            elapsed = (
                time.monotonic() - start_time
            )

            logger.debug(
                "本次任务耗时: %.2f 秒",
                elapsed
            )


# ============================================================
# 保存账号
# ============================================================

ACCOUNTS_DB = "accounts.db"


def get_db_connection(
    db_path: str = ACCOUNTS_DB,
    config: Optional[Config] = None,
) -> Any:
    """返回 MySQL 或 SQLite 数据库连接。"""
    cfg = config or Config()

    if cfg.db_host:
        import pymysql
        return pymysql.connect(
            host=cfg.db_host,
            port=cfg.db_port,
            user=cfg.db_user,
            password=cfg.db_password,
            database=cfg.db_name,
            charset="utf8mb4",
            autocommit=True,
        )

    return sqlite3.connect(db_path)


def init_accounts_db(db_path: str = ACCOUNTS_DB) -> None:
    """创建账号数据库表。"""
    cfg = Config()
    conn = get_db_connection(db_path, cfg)
    try:
        cursor = conn.cursor()
        if cfg.db_host:
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
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    auth_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def save_account(
    result: dict,
    db_path: str = ACCOUNTS_DB
) -> None:
    """注册成功后把账号信息保存到数据库。"""
    cfg = Config()
    init_accounts_db(db_path)

    row = (
        result.get("phone", ""),
        result.get("password", ""),
        result.get("user_id", ""),
        result.get("key", ""),
    )

    conn = get_db_connection(db_path, cfg)
    try:
        cursor = conn.cursor()
        if cfg.db_host:
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
                row,
            )
        else:
            cursor.execute(
                """
                INSERT INTO accounts
                    (phone, password, user_id, auth_key)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    password = excluded.password,
                    user_id = excluded.user_id,
                    auth_key = excluded.auth_key
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()

    logger.debug("账号已保存到数据库 %s", db_path)


# ============================================================
# main
# ============================================================

def main():

    config = Config()
    init_accounts_db(config.accounts_db)

    total = config.register_count
    success = 0
    failed = 0

    logger.info(
        "开始注册 %d 个账号",
        total
    )

    for i in range(1, total + 1):

        logger.info(
            "第 %d/%d 个账号",
            i, total
        )

        try:

            registrar = AccountRegistrar(
                config
            )

            result = registrar.register()

            save_account(result, config.accounts_db)

            success += 1

        except Exception as e:

            failed += 1

            logger.error(
                "第 %d 个账号注册失败: %s",
                i, e
            )

        # 账号之间停顿一下，避免接码平台限流
        if i < total:
            wait = 3
            logger.debug(
                "等待 %d 秒后继续下一个...",
                wait
            )
            time.sleep(wait)

    logger.info(
        "全部完成: 成功 %d/%d, 失败 %d",
        success, total, failed
    )


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    main()
