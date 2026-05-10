"""Migrate: delete old demos → create scopes → upload employee handbook."""

import json
import logging
import shutil
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8080"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123456"
PAGE_SIZE = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class Migrator:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=60)
        self.token: str | None = None

    def login(self):
        logger.info("Logging in as %s ...", ADMIN_USERNAME)
        resp = self.client.post(
            "/admin/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        data = resp.json()
        self.token = data["data"]["token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Login OK, token: %s...", self.token[:20])

    def get_all_documents(self) -> list[dict]:
        logger.info("Fetching all documents ...")
        all_docs = []
        page_no = 1
        while True:
            resp = self.client.post(
                "/manage/document/page/query",
                json={"pageNo": page_no, "pageSize": PAGE_SIZE},
            )
            data = resp.json()["data"]
            records = data.get("records", [])
            all_docs.extend(records)
            total = data.get("total", 0)
            if len(all_docs) >= total:
                break
            page_no += 1
        logger.info("Total documents: %d", len(all_docs))
        return all_docs

    def delete_document(self, document_id: str) -> bool:
        resp = self.client.post(
            "/manage/document/delete",
            json={"documentId": document_id},
        )
        result = resp.json()
        ok = result.get("code") == 200
        if not ok:
            logger.warning("  ✗ delete %s: %s", document_id, result.get("message"))
        return ok

    def delete_scope(self, scope_code: str) -> bool:
        resp = self.client.post(
            "/manage/knowledge/scope/delete",
            json={"scopeCode": scope_code},
        )
        result = resp.json()
        ok = result.get("code") == 200
        if ok:
            logger.info("  ✓ scope '%s' deleted", scope_code)
        else:
            logger.warning("  ✗ scope '%s': %s", scope_code, result.get("message"))
        return ok

    def create_scope(self, code: str, name: str, desc: str = ""):
        resp = self.client.post(
            "/manage/knowledge/scope/save",
            json={"scopeCode": code, "scopeName": name, "description": desc},
        )
        result = resp.json()
        logger.info("  ✓ scope '%s' created: %s", code, result.get("message"))
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
            logger.info("  ✓ %s → scope=%s", document_name, scope_code)
        else:
            logger.warning("  ✗ %s: %s", document_name, result.get("message", result))
        return result


def main():
    migrator = Migrator()
    migrator.login()

    # ── Step 2: Delete all old documents ──
    logger.info("=" * 50)
    logger.info("STEP 2: Deleting old documents & scopes")
    docs = migrator.get_all_documents()
    doc_ids = [d["documentId"] for d in docs]
    logger.info("Deleting %d documents ...", len(doc_ids))
    ok = 0
    for did in doc_ids:
        if migrator.delete_document(did):
            ok += 1
    logger.info("Deleted %d/%d documents", ok, len(doc_ids))

    # Delete old scopes
    migrator.delete_scope("fastmcp")
    migrator.delete_scope("fastapi")

    # Clean up filesystem
    demo_dir = Path("demo_docs")
    for p in demo_dir.glob("*.md"):
        if p.name != ".gitkeep":
            p.unlink()
            logger.info("  rm %s", p)
    fastmcp_dir = demo_dir / "fastmcp_docs"
    if fastmcp_dir.exists():
        shutil.rmtree(fastmcp_dir)
        logger.info("  rm -rf %s", fastmcp_dir)

    # Wait a bit for async deletions
    import time

    logger.info("Waiting 3s for async cleanup ...")
    time.sleep(3)

    # ── Step 3: Create new scopes ──
    logger.info("=" * 50)
    logger.info("STEP 3: Creating new scopes")
    migrator.create_scope("hr_policies", "人力资源制度", "员工手册、入职离职等人事制度")
    migrator.create_scope("finance_policies", "财务管理制度", "差旅报销、商务招待等财务制度")
    migrator.create_scope("it_security", "信息安全规范", "信息安全、数据保密管理规范")

    # ── Step 4: Upload documents ──
    logger.info("=" * 50)
    logger.info("STEP 4: Uploading employee handbook documents")

    handbook_dir = demo_dir / "employee_handbook"
    uploads = [
        (handbook_dir / "01_华远科技集团员工手册.md", "hr_policies", "01_华远科技集团员工手册.md"),
        (handbook_dir / "02_差旅与报销管理制度.md", "finance_policies", "02_差旅与报销管理制度.md"),
        (
            handbook_dir / "03_信息安全与数据保密管理规范.md",
            "it_security",
            "03_信息安全与数据保密管理规范.md",
        ),
        (
            handbook_dir / "04_商务招待与礼品管理制度.md",
            "finance_policies",
            "04_商务招待与礼品管理制度.md",
        ),
    ]
    for file_path, scope, doc_name in uploads:
        migrator.upload_file(file_path, scope, doc_name)

    logger.info("=" * 50)
    logger.info("ALL DONE! Documents are being processed by Celery pipeline.")
    logger.info("Run verification in ~60s to check parse/index status.")


if __name__ == "__main__":
    main()
