"""Create local development configuration without printing or replacing secrets."""
from pathlib import Path
import secrets


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    contents = (root / ".env.example").read_text(encoding="utf-8")
    contents = contents.replace("replace_with_generated_local_password", secrets.token_hex(32))
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as output:
            output.write(contents)
    except FileExistsError:
        print(".env already exists; preserved without changes.")
    else:
        print("Created ignored .env with a random development password.")


if __name__ == "__main__":
    main()
