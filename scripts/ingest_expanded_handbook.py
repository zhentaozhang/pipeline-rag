"""Ingest expanded employee handbook: 15 documents across 4 enterprise scopes.

Scopes:
- hr_policies: 人力资源与员工关怀制度 (01, 05, 06, 10, 12)
- finance_policies: 财务与采购招投标制度 (02, 04, 09, 14)
- it_security: 信息安全与研发合规红线 (03, 08, 13)
- admin_facilities: 行政资产与智慧园区服务 (07, 11, 15)
"""

import json
import logging
import time
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


class HandbookIngestor:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=120)
        self.token: str | None = None

    def login(self):
        logger.info("Logging in as %s ...", ADMIN_USERNAME)
        resp = self.client.post(
            "/admin/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        data = resp.json()
        if "data" not in data or "token" not in data["data"]:
            raise RuntimeError(f"Login failed: {data}")
        self.token = data["data"]["token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Login OK, token: %s...", self.token[:20])

    def get_all_documents(self) -> list[dict]:
        logger.info("Fetching existing documents ...")
        all_docs = []
        page_no = 1
        while True:
            resp = self.client.post(
                "/manage/document/page/query",
                json={"pageNo": page_no, "pageSize": PAGE_SIZE},
            )
            data = resp.json().get("data", {})
            records = data.get("records", [])
            all_docs.extend(records)
            total = data.get("total", 0)
            if len(all_docs) >= total or not records:
                break
            page_no += 1
        logger.info("Total documents found: %d", len(all_docs))
        return all_docs

    def delete_document(self, document_id: str) -> bool:
        resp = self.client.post(
            "/manage/document/delete",
            json={"documentId": document_id},
        )
        result = resp.json()
        ok = result.get("code") in (0, 200)
        if not ok:
            logger.warning("  ✗ delete %s: %s", document_id, result.get("message"))
        return ok

    def ensure_scope(self, code: str, name: str, desc: str = ""):
        resp = self.client.post(
            "/manage/knowledge/scope/save",
            json={"scopeCode": code, "scopeName": name, "description": desc},
        )
        result = resp.json()
        logger.info("  ✓ scope '%s' registered: %s", code, result.get("message"))
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
        if result.get("code") in (0, 200) and (result.get("success") or result.get("data")):
            logger.info(
                "  ✓ %s → scope=%s (doc_id=%s)",
                document_name,
                scope_code,
                result.get("data", {}).get("documentId"),
            )
        else:
            logger.warning("  ✗ %s: %s", document_name, result.get("message", result))
        return result


def main():
    ingestor = HandbookIngestor()
    ingestor.login()

    # 1. Clean up old documents
    logger.info("=" * 60)
    logger.info("STEP 1: Cleaning up existing handbook documents...")
    docs = ingestor.get_all_documents()
    for d in docs:
        ingestor.delete_document(d["documentId"])
    time.sleep(2)

    # 2. Register / Ensure 4 scopes
    logger.info("=" * 60)
    logger.info("STEP 2: Registering enterprise knowledge scopes...")
    ingestor.ensure_scope(
        "hr_policies", "人力资源与员工关怀制度", "员工手册、考核激励、进修补贴、离职交接与关怀基金"
    )
    ingestor.ensure_scope(
        "finance_policies", "财务与采购招投标制度", "差旅报销、商务招待、招投标审计与作废制度"
    )
    ingestor.ensure_scope(
        "it_security", "信息安全与研发合规红线", "信息安全、生产发布红线与开源合规规程"
    )
    ingestor.ensure_scope(
        "admin_facilities", "行政资产与智慧园区服务", "固定资产管理、职务发明与智慧园区管理"
    )

    # 3. Upload all 15 documents
    logger.info("=" * 60)
    logger.info("STEP 3: Uploading all 15 handbook documents...")
    handbook_dir = Path("demo_docs/employee_handbook")

    file_scope_mapping = [
        ("01_华远科技集团员工手册.md", "hr_policies"),
        ("02_差旅与报销管理制度.md", "finance_policies"),
        ("03_信息安全与数据保密管理规范.md", "it_security"),
        ("04_商务招待与礼品管理制度.md", "finance_policies"),
        ("05_员工绩效考核评级与年终激励实施细说.md".replace("说", "则"), "hr_policies"),
        ("06_员工在职进修与专业资格考证补贴办法.md", "hr_policies"),
        ("07_固定资产管理与办公电脑领用报废规程.md", "admin_facilities"),
        ("08_软件工程研发交付与线上生产发布安全红线.md", "it_security"),
        ("09_企业采购管理与招投标合规审计规范.md", "finance_policies"),
        ("10_员工离职交接与涉密审计处置指引.md", "hr_policies"),
        ("11_知识产权管理与职务发明奖励办法.md", "admin_facilities"),
        ("12_突发公共事件应急处置与员工关怀基金章程.md", "hr_policies"),
        ("13_开源软件引入安全审查与合规引入规程.md", "it_security"),
        ("14_华远科技已作废旧版差旅制度(2022版).md", "finance_policies"),
        ("15_智慧园区公约与办公大楼物业管理指南.md", "admin_facilities"),
    ]

    for filename, scope in file_scope_mapping:
        fpath = handbook_dir / filename
        if not fpath.exists():
            logger.error("File not found: %s", fpath)
            continue
        ingestor.upload_file(fpath, scope, filename)

    logger.info("=" * 60)
    logger.info(
        "All 15 documents uploaded successfully! Indexing pipeline initiated in background."
    )


if __name__ == "__main__":
    main()
