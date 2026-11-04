"""Publish the committed tree to a Hugging Face Docker Space.

    pip install huggingface_hub
    python scripts/deploy_space.py [space-name]        (from backend/, default name: kinesight)

Needs HF_TOKEN (write access) and META_API_KEY in the environment or the repo-root .env.
The Meta key is stored as a private Space secret. Besides the files tracked by git, the
presets' raw SAM 3.1 outputs are uploaded so editing a preset's rules on the live site
re-runs kinematics without paying for segmentation again.
"""

import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env)

REPO_ROOT = config.BACKEND_DIR.parent

SPACE_HEADER = """---
title: KineSight
emoji: 🔩
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Sensorless SOP compliance from video with SAM 3.1
---

"""


def stage(dst: Path) -> None:
    """Committed files (never .env or local-only files) plus the presets' SAM caches."""
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=REPO_ROOT,
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dst, filter="data")
    for f in config.PRESETS_DIR.glob("*/cache/sam_*"):
        out = dst / f.relative_to(REPO_ROOT)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(f.read_bytes())
    readme = dst / "README.md"
    readme.write_text(SPACE_HEADER + readme.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> None:
    token = os.getenv("HF_TOKEN", "").strip()
    if not token or not config.META_API_KEY:
        sys.exit("HF_TOKEN and META_API_KEY must both be set (repo-root .env)")
    api = HfApi(token=token)
    repo_id = f"{api.whoami()['name']}/{sys.argv[1] if len(sys.argv) > 1 else 'kinesight'}"

    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_secret(repo_id, "META_API_KEY", config.META_API_KEY)
    with tempfile.TemporaryDirectory() as tmp:
        stage(Path(tmp))
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                          commit_message="Deploy KineSight from GitHub main", delete_patterns=["*"])
    print(f"https://huggingface.co/spaces/{repo_id}")
    print(f"https://{repo_id.replace('/', '-').replace('_', '-').lower()}.hf.space")


if __name__ == "__main__":
    main()
