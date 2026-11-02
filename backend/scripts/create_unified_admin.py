"""Create a GEO Monitor administrator from the server console."""
import getpass
import sys

import bcrypt
from sqlalchemy import select

from geo.database import SessionLocal
from geo.models.user import UserORM


def main() -> None:
    email = input("管理员邮箱: ").strip().lower()
    password = getpass.getpass("管理员密码（至少 12 个字符）: ")
    confirmation = getpass.getpass("再次输入密码: ")
    if not email or "@" not in email or len(password) < 12 or password != confirmation:
        sys.exit("邮箱或密码无效，或两次密码不一致。")
    if len(password.encode("utf-8")) > 72:
        sys.exit("密码的 UTF-8 编码不能超过 72 字节。")
    with SessionLocal() as db:
        if db.scalar(select(UserORM).where(UserORM.email == email)):
            sys.exit("该邮箱已存在，未更改现有账号。")
        db.add(UserORM(email=email, name="GEO Administrator", password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), is_active=True, is_admin=True))
        db.commit()
    print("管理员账号已创建。")


if __name__ == "__main__":
    main()
