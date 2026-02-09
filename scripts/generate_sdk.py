from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdk"
OPENAPI_PATH = SDK_DIR / "openapi.json"


def _write_openapi() -> None:
    SDK_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        (
            "from nexusrag.apps.api.main import create_app;"
            "import json;"
            "from pathlib import Path;"
            "Path('/app/sdk/openapi.json').write_text(json.dumps(create_app().openapi(), indent=2))"
        ),
    ]
    subprocess.run(cmd, check=True)


def _run_generator(generator: str, output: Path, additional: str) -> None:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{ROOT}:/local",
        "openapitools/openapi-generator-cli",
        "generate",
        "-i",
        f"/local/{OPENAPI_PATH.relative_to(ROOT)}",
        "-g",
        generator,
        "-o",
        f"/local/{output.relative_to(ROOT)}",
        "--additional-properties",
        additional,
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    _write_openapi()
    _run_generator(
        "typescript-fetch",
        SDK_DIR / "typescript" / "generated",
        "npmName=nexusrag-sdk,supportsES6=true",
    )
    _run_generator(
        "python",
        SDK_DIR / "python" / "generated",
        "packageName=nexusrag_sdk,projectName=nexusrag-sdk,packageVersion=1.3.0",
    )


if __name__ == "__main__":
    main()
