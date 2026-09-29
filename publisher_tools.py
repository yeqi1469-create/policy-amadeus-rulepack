from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
from pathlib import Path


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Policy Amadeus"
PRIVATE_KEY_PATH = APP_DIR / "publisher_ed25519_private.key"
RELEASE_DIR = Path(__file__).resolve().parent / "rulepack_release"


def canonical_manifest_fields(version: str, download_url: str, sha256: str) -> bytes:
    return json.dumps(
        {"download_url": download_url, "rulepack_version": version, "sha256": sha256},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def init_key() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    secret = os.environ.get("POLICY_AMADEUS_PUBLISHER_KEY_B64", "")
    if secret:
        private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret, validate=True))
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        raise RuntimeError("Repository signing secret is missing; refusing to create an untrusted replacement key")
    elif PRIVATE_KEY_PATH.exists():
        private_key = Ed25519PrivateKey.from_private_bytes(PRIVATE_KEY_PATH.read_bytes())
    else:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        private_key = Ed25519PrivateKey.generate()
        PRIVATE_KEY_PATH.write_bytes(private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_key).decode("ascii")


def publish(base_url: str) -> dict[str, str]:
    if not base_url.startswith("https://"):
        raise ValueError("base_url 必须使用 HTTPS")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    public_key = init_key()
    secret = os.environ.get("POLICY_AMADEUS_PUBLISHER_KEY_B64", "")
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret, validate=True) if secret else PRIVATE_KEY_PATH.read_bytes())
    source = Path(__file__).resolve().parent / "legal_rulepack.json"
    payload = source.read_bytes()
    data = json.loads(payload.decode("utf-8"))
    version = str(data["rulepack_version"])
    digest = hashlib.sha256(payload).hexdigest()
    download_url = base_url.rstrip("/") + "/legal_rulepack.json"
    signed = canonical_manifest_fields(version, download_url, digest)
    manifest = {
        "rulepack_version": version,
        "download_url": download_url,
        "sha256": digest,
        "signature": base64.b64encode(private_key.sign(signed)).decode("ascii"),
    }
    RELEASE_DIR.mkdir(exist_ok=True)
    (RELEASE_DIR / "legal_rulepack.json").write_bytes(payload)
    (RELEASE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"public_key": public_key, "manifest_url": base_url.rstrip("/") + "/manifest.json"}


def publish_app(base_url: str, executable: Path, version: str) -> dict[str, str]:
    """Publish a separately signed Windows binary for unattended installation."""
    if not base_url.startswith("https://") or not version:
        raise ValueError("程序更新基础地址必须使用 HTTPS，且版本不能为空")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not executable.is_file() or executable.stat().st_size < 1024 * 1024:
        raise ValueError("待发布的程序文件不存在或过小")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("待发布的程序不是 Windows EXE")
    init_key()
    secret = os.environ.get("POLICY_AMADEUS_PUBLISHER_KEY_B64", "")
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret, validate=True) if secret else PRIVATE_KEY_PATH.read_bytes())
    RELEASE_DIR.mkdir(exist_ok=True)
    output = RELEASE_DIR / "PolicyAmadeus.exe"
    shutil.copyfile(executable, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    download_url = base_url.rstrip("/") + "/PolicyAmadeus.exe"
    signed = json.dumps(
        {"download_url": download_url, "sha256": digest, "version": version},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    manifest = {
        "version": version, "download_url": download_url, "sha256": digest,
        "signature": base64.b64encode(private_key.sign(signed)).decode("ascii"),
    }
    (RELEASE_DIR / "app_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"app_manifest_url": base_url.rstrip("/") + "/app_manifest.json", "sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy Amadeus signed rulepack publisher")
    parser.add_argument("base_url", nargs="?", help="公开仓库的 HTTPS Raw 基础地址")
    parser.add_argument("--app-exe", type=Path, help="已完成测试的 Windows EXE")
    args = parser.parse_args()
    if args.base_url:
        result = publish(args.base_url)
        if args.app_exe:
            version = str(json.loads((Path(__file__).resolve().parent / "app_version.json").read_text(encoding="utf-8"))["version"])
            result.update(publish_app(args.base_url, args.app_exe, version))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(init_key())


if __name__ == "__main__":
    main()
