"""
Create or reset a staff account (email + password).

    python -m scripts.create_user --email admin@clet.gov.gh --name "DTI Admin" --role "System Administrator"

The password is read interactively (never from argv, so it stays out of shell
history) unless `--password-env VAR` names an environment variable holding it.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.core.rbac import Role
from app.core.security import hash_password, password_problems
from app.models.users import User


async def upsert_user(email: str, name: str, role: str, password: str) -> str:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            session.add(User(email=email.lower(), name=name, role=role, password_hash=hash_password(password)))
            outcome = "created"
        else:
            user.name, user.role, user.active = name, role, True
            user.password_hash, user.failed_login_count, user.locked_until = hash_password(password), 0, None
            outcome = "updated"
        await session.commit()
    await async_engine.dispose()
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=Role.ALL)
    parser.add_argument("--password-env", help="Name of an environment variable holding the password")
    args = parser.parse_args()

    password = os.environ.get(args.password_env, "") if args.password_env else getpass.getpass("Password: ")
    problems = password_problems(password, min_length=get_settings().PASSWORD_MIN_LENGTH)
    if problems:
        print("Password rejected: " + " ".join(problems), file=sys.stderr)
        return 1
    outcome = asyncio.run(upsert_user(args.email, args.name, args.role, password))
    print(f"User {args.email} {outcome} with role {args.role}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
