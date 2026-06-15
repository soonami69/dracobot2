import argparse
import sys

from sqlalchemy.exc import IntegrityError

from dracobot2.config import SessionLocal
from dracobot2.models import User


def normalize_handle(handle):
    return handle.strip().lstrip("@")


def add_admin(handle):
    session = SessionLocal()

    try:
        normalized_handle = normalize_handle(handle)
        if not normalized_handle:
            raise ValueError("Telegram handle cannot be empty.")

        existing_user = session.query(User).filter(User.tele_handle == normalized_handle).first()
        if existing_user is not None:
            if not existing_user.is_admin:
                existing_user.is_admin = True
                session.commit()
                print(
                    "Promoted existing user to admin: "
                    f"id={existing_user.id}, tele_handle=@{existing_user.tele_handle}, "
                    f"registered={existing_user.registered}"
                )
                return 0

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
