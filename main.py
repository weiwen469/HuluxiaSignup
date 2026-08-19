import os
import time
import logging
from dataclasses import dataclass
from typing import Optional, Any
import csv
from datetime import datetime

import Haozhu
import Hu_api

from dotenv import load_dotenv

load_dotenv()
# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
            "正在获取临时手机号..."
        )

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
            "开始等待短信验证码..."
        )

        logger.info(
            "超时时间: %s 秒",
            self.config.sms_timeout
        )

        logger.info(
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

                logger.info(
                    "第 %d 次查询验证码: %s",
                    attempt,
                    message
                )

                if message is not None:

                    code = str(message)

                    logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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

        logger.info(
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
                "========================================"
            )

            logger.info(
                "注册成功"
            )

            logger.info(
                "手机号: %s",
                self.phone
            )

            logger.info(
                "UserID: %s",
                data.get("userID")
            )

            logger.info(
                "密码: %s",
                self.config.account_password
            )

            logger.info(
                "========================================"
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
                "========================================"
            )

            logger.info(
                "账号已经存在"
            )

            logger.info(
                "手机号: %s",
                self.phone
            )

            logger.info(
                "UserID: %s",
                data.get("userID")
            )

            logger.info(
                "Key: %s",
                data.get("_key")
            )

            logger.info(
                "========================================"
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

        logger.info(
            "正在释放手机号: %s",
            phone
        )

        try:

            result = Haozhu.cancelRecv(
                token=self.token,
                sid=self.config.sid,
                phone=phone
            )

            logger.info(
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

        except Exception as e:

            logger.error(
                "注册流程失败: %s",
                e
            )

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

            logger.info(
                "本次任务耗时: %.2f 秒",
                elapsed
            )


# ============================================================
# 保存账号
# ============================================================

ACCOUNTS_FILE = "accounts.csv"


def save_account(result: dict) -> None:
    """注册成功后把账号信息追加到 CSV 文件。"""
    file_exists = os.path.isfile(ACCOUNTS_FILE)
    with open(ACCOUNTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["时间", "手机号", "密码", "UserID", "Key", "状态"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result.get("phone", ""),
            result.get("password", ""),
            result.get("user_id", ""),
            result.get("key", ""),
            result.get("message", ""),
        ])
    logger.info("账号已保存到 %s", ACCOUNTS_FILE)


# ============================================================
# main
# ============================================================

def main():

    try:

        config = Config()

        registrar = AccountRegistrar(
            config
        )

        result = registrar.register()

        save_account(result)

        print()
        print("========================================")
        print("最终结果")
        print("========================================")
        print(result)
        print("========================================")

    except Exception as e:

        logger.error(
            "任务执行失败: %s",
            e
        )


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    main()
