"""
Reindex all parsed documents in the Celery pipeline.
Triggered by the fix for: DocumentStrategyService ImportError + hardcoded document_id=0.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import select

from app.common.enums import (
    DocumentParseStatusEnum,
)
from app.db.models.document import Document
from app.document.tasks import trigger_document_pipeline


async def main():
    import app.db.session as db_session

    await db_session.init_db()

    async with db_session._session_factory() as db:
        stmt = (
            select(Document)
            .where(Document.parse_status == DocumentParseStatusEnum.PARSE_SUCCESS.value)
            .order_by(Document.id)
        )
        docs = (await db.execute(stmt)).scalars().all()

    if not docs:
        print("No parsed documents found.")
        return

    print(f"Found {len(docs)} parsed documents. Triggering pipeline for each...")

    for i, doc in enumerate(docs):
        doc_id = doc.doc_id
        object_name = doc.object_name
        if not object_name:
            print(f"  [{i + 1}/{len(docs)}] SKIP {doc_id} ({doc.document_name}) — no object_name")
            continue

        try:
            task_id = trigger_document_pipeline(doc_id, object_name)
            print(
                f"  [{i + 1}/{len(docs)}] {doc.document_name} → pipeline triggered (task={task_id})"
            )
        except Exception as e:
            print(f"  [{i + 1}/{len(docs)}] FAIL {doc.document_name}: {e}")

    print(f"\nAll {len(docs)} pipelines submitted. Check Celery worker logs for progress.")


if __name__ == "__main__":
    asyncio.run(main())
