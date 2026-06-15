import argparse
import sys

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from dracobot2.config import SessionLocal
from dracobot2.models import User
from dracobot2.utils.handles import normalize_telegram_handle


def add_admin(handle):
    session = SessionLocal()

    try:
        normalized_handle = normalize_telegram_handle(handle)
        if not normalized_handle:
            raise ValueError("Telegram handle cannot be empty.")

        existing_user = session.query(User).filter(func.lower(User.tele_handle) == normalized_handle).first()
        if existing_user is not None:
            handle_was_normalized = existing_user.tele_handle != normalized_handle
            if handle_was_normalized:
                existing_user.tele_handle = normalized_handle

            if not existing_user.is_admin:
                existing_user.is_admin = True
                session.commit()
                print(
                    "Promoted existing user to admin: "
                    f"id={existing_user.id}, tele_handle=@{existing_user.tele_handle}, "
                    f"registered={existing_user.registered}"
                )
                return 0

            if handle_was_normalized:
                session.commit()

            print(
                "Admin already exists: "
                f"id={existing_user.id}, tele_handle=@{existing_user.tele_handle}, "
                f"registered={existing_user.registered}"
            )
            return 0

        user = User(tele_handle=normalized_handle, is_admin=True)
        session.add(user)
        session.commit()

        print(f"Added admin: id={user.id}, tele_handle=@{user.tele_handle}")
        return 0
    except IntegrityError as exc:
        session.rollback()
        print(f"Could not add user due to a database constraint: {exc.orig}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Add an admin to the existing database using only their Telegram handle."
    )
    parser.add_argument("handle", help="Telegram handle, with or without the leading @")
    args = parser.parse_args()

    return add_admin(args.handle)


if __name__ == "__main__":
    raise SystemExit(main())
