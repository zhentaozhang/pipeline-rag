"""Upload demo documents via API — creates scopes, uploads files, triggers processing."""

import json
import logging
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8080"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123456"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class Uploader:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=60)
        self.token: str | None = None

    def login(self) -> str:
        logger.info("Logging in as %s ...", ADMIN_USERNAME)
        resp = self.client.post(
            "/admin/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        data = resp.json()
        self.token = data["data"]["token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Login OK, token: %s...", self.token[:20])
        return self.token

    def ensure_scope(self, code: str, name: str, desc: str = ""):
        resp = self.client.post(
            "/manage/knowledge/scope/save",
            json={
                "scopeCode": code,
                "scopeName": name,
                "description": desc,
            },
        )
        logger.info("Scope %s: %s", code, resp.json()["message"])
        return code

    def upload_file(self, file_path: Path, scope_code: str, document_name: str) -> dict:
        meta = json.dumps(
            {
                "knowledgeScopeCode": scope_code,
                "documentName": document_name,
            }
        )
        with open(file_path, "rb") as f:
            resp = self.client.post(
                "/manage/document/upload",
                files={
                    "file": (document_name, f, "text/markdown"),
                    "meta": ("meta.json", meta, "application/json"),
                },
            )
        result = resp.json()
        if result.get("code") == 200 and result.get("success"):
            logger.info("  ✓ %s", document_name)
        else:
            logger.warning("  ✗ %s: %s", document_name, result.get("message", result))
        return result

    def upload_scope_files(self, files: list[tuple[Path, str]], scope_code: str, batch_name: str):
        total = len(files)
        logger.info("Uploading %d files to scope '%s' ...", total, batch_name)
        ok = 0
        for i, (file_path, doc_name) in enumerate(files, 1):
            if i % 20 == 0:
                logger.info("  Progress: %d/%d", i, total)
            result = self.upload_file(file_path, scope_code, doc_name)
            if result.get("code") == 200 and result.get("success"):
                ok += 1
        logger.info("Done: %d/%d uploaded to '%s'", ok, total, batch_name)


def collect_fastmcp_files(docs_dir: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for md_file in sorted(docs_dir.rglob("*.md")):
        if md_file.name.startswith("."):
            continue
        rel = md_file.relative_to(docs_dir)
        name = str(rel)
        files.append((md_file, name))
    return files


def main():
    uploader = Uploader()
    uploader.login()

    # Create knowledge scopes
    uploader.ensure_scope("fastmcp", "FastMCP 文档", "FastMCP 框架中文文档")
    uploader.ensure_scope("fastapi", "FastAPI 笔记", "FastAPI 学习笔记")

    # Collect and upload FastMCP docs
    docs_dir = Path("demo_docs/fastmcp_docs")
    fastmcp_files = collect_fastmcp_files(docs_dir)
    uploader.upload_scope_files(fastmcp_files, "fastmcp", "FastMCP")

    # Upload FastAPI notes
    fastapi_path = Path("demo_docs/fastapi_notes.md")
    uploader.upload_file(fastapi_path, "fastapi", "FastAPI 学习笔记.md")

    logger.info("All uploads complete!")


if __name__ == "__main__":
    main()
