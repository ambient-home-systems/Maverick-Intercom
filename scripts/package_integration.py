#!/usr/bin/env python3
"""Package the integration source and installation guide, never local fixtures."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components/maverick_intercom"
    output = root / ".local/dist/maverick-intercom-demo.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".yaml"}:
                archive.write(path, path.relative_to(root))
        archive.write(root / "docs/integration-demo.md", "INSTALL.md")
    print(f"Created {output.relative_to(root)} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
