"""Initialize local Docker configuration without storing a password in source control."""
import secrets
from pathlib import Path


def main():
    path = Path(".env")
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write("DEMO_DB_PASSWORD=" + secrets.token_hex(24) + "\n")
    except FileExistsError:
        print("Existing .env preserved.")
    else:
        print("Created ignored local .env configuration.")


if __name__ == "__main__":
    main()
