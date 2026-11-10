"""
设置/重置登录密码（交互式，密码不经过命令行参数和 shell 历史）。

用法（在服务器上，容器内执行，需要 -it 以便输入密码）:
    docker compose -f docker-compose.prod.yml run --rm -it \
      -v "$PWD/scripts:/app/scripts:ro" backend python scripts/set_password.py

默认更新 settings.DEFAULT_USERNAME（单用户系统唯一的登录账号）。
"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.passwords import hash_password  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.connection import Database  # noqa: E402

MIN_LENGTH = 12


async def main() -> None:
    username = settings.DEFAULT_USERNAME
    pw1 = getpass.getpass(f"为 {username} 设置新密码（至少 {MIN_LENGTH} 位）: ")
    pw2 = getpass.getpass("再输入一次: ")
    if pw1 != pw2:
        sys.exit("两次输入不一致，未修改")
    if len(pw1) < MIN_LENGTH:
        sys.exit(f"密码至少 {MIN_LENGTH} 位，未修改")

    db = Database()
    await db.connect(settings.DATABASE_DSN)
    try:
        row = await db.fetch_one(
            "UPDATE users SET password_hash = $1, updated_at = NOW() "
            "WHERE username = $2 RETURNING id",
            hash_password(pw1), username,
        )
    finally:
        await db.disconnect()

    if row is None:
        sys.exit(f"用户 {username} 不存在，未修改")
    print(f"已更新 {username} 的密码")


if __name__ == "__main__":
    asyncio.run(main())
