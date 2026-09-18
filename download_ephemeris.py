#!/usr/bin/env python3
"""
Descarga reproducible de las efemérides Swiss que Areté necesita.

Los ficheros se obtienen del repositorio público oficial de Swiss Ephemeris,
fijados a un commit concreto y verificados contra el Git blob SHA esperado.
Nunca se acepta un fichero distinto silenciosamente.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.request import Request, urlopen

UPSTREAM_COMMIT = "9083a12d59e98034fb2337061481ac8800c16e64"
UPSTREAM_BASE = (
    "https://raw.githubusercontent.com/aloistr/swisseph/"
    f"{UPSTREAM_COMMIT}/ephe"
)

FILES = {
    "sepl_18.se1": "786702cd04506371ee6223af1ebac02d54c848b8",
    "semo_18.se1": "5427d9f885fd6cb9489584ade37e52c6abb4d407",
    "seas_18.se1": "8f900cab7e557e4c41f758a6bf3a3c3967e7e3db",
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def download_file(name: str, expected_blob_sha: str, destination: Path) -> None:
    url = f"{UPSTREAM_BASE}/{name}"
    request = Request(
        url,
        headers={"User-Agent": "arete-ephemeris-build/1.0"},
    )
    with urlopen(request, timeout=60) as response:
        data = response.read()

    actual_blob_sha = git_blob_sha(data)
    if actual_blob_sha != expected_blob_sha:
        raise RuntimeError(
            f"{name}: Git blob SHA inesperado: "
            f"esperado={expected_blob_sha} obtenido={actual_blob_sha}"
        )

    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, destination)
    print(
        f"[ephe-download] {name}: {len(data)} bytes, "
        f"blob={actual_blob_sha}"
    )


def main() -> None:
    default_path = Path(__file__).resolve().parent / "ephe"
    ephe_path = Path(os.environ.get("EPHE_PATH", str(default_path)))
    ephe_path.mkdir(parents=True, exist_ok=True)

    for name, blob_sha in FILES.items():
        download_file(name, blob_sha, ephe_path / name)

    print(
        f"[ephe-download] OK: {len(FILES)} ficheros descargados "
        f"desde Swiss Ephemeris commit {UPSTREAM_COMMIT}"
    )


if __name__ == "__main__":
    main()
