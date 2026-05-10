"""
回填 PG pipeline_rag_document_embedding.metadata_json 中缺失的 documentName。

从 MySQL pipeline_rag_document 读取文档名，逐条更新 PG。
用法: uv run python scripts/backfill_pg_document_name.py
"""

import asyncio
import json

import aiomysql
import asyncpg


async def main():
    from app.config import get_settings

    settings = get_settings()

    pg = await asyncpg.connect(
        host=settings.postgres.host,
        port=settings.postgres.port,
        user=settings.postgres.user,
        password=settings.postgres.password,
        database=settings.postgres.db,
    )
    mysql = await aiomysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        db=settings.mysql.db,
        charset="utf8mb4",
        autocommit=True,
    )

    try:
        # 读取 MySQL 所有文档的 id -> document_name 映射
        async with mysql.cursor() as cur:
            await cur.execute("SELECT id, document_name FROM pipeline_rag_document")
            rows = await cur.fetchall()
        doc_map = {row[0]: row[1] for row in rows}
        print(f"MySQL: 读取 {len(doc_map)} 个文档")

        # 读取 PG 中 metadata_json 缺少 documentName 的记录
        pg_rows = await pg.fetch(
            "SELECT id, document_id, metadata_json FROM pipeline_rag_document_embedding "
            "WHERE metadata_json->>'documentName' IS NULL "
            "OR metadata_json->>'documentName' = ''"
        )
        print(f"PG: 发现 {len(pg_rows)} 条缺失 documentName 的记录")

        updated = 0
        for row in pg_rows:
            doc_id_int = row["document_id"]
            doc_name = doc_map.get(doc_id_int, "")
            if not doc_name:
                continue
            meta = row["metadata_json"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            meta["documentName"] = doc_name
            await pg.execute(
                "UPDATE pipeline_rag_document_embedding SET metadata_json = $1::jsonb WHERE id = $2",
                json.dumps(meta),
                row["id"],
            )
            updated += 1
            if updated % 100 == 0:
                print(f"  已回填 {updated}/{len(pg_rows)}")

        print(f"回填完成: {updated} 条")
    finally:
        await pg.close()
        mysql.close()


if __name__ == "__main__":
    asyncio.run(main())
