"""
SessionRepository — 会话数据访问层

安全约定：每条查询都带 user_id 条件。别人的会话查不到，
和不存在的会话走同一条「未找到」分支，不泄露会话是否存在。
"""
import json

import asyncpg

from app.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    table_name = "sessions"

    async def list_by_user(
        self,
        conn: asyncpg.Connection,
        user_id: str,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[asyncpg.Record], int]:
        """按更新时间倒序分页列出会话（不返回 messages，只返回消息数）"""
        rows = await conn.fetch(
            """
            SELECT id, title, jsonb_array_length(messages) AS message_count,
                   created_at, updated_at
            FROM "sessions"
            WHERE user_id = $1
            ORDER BY updated_at DESC, id DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, page_size, (page - 1) * page_size,
        )
        total = await self.count(conn, "user_id = $1", user_id)
        return list(rows), total

    async def get_for_user(
        self, conn: asyncpg.Connection, session_id: str, user_id: str
    ) -> asyncpg.Record | None:
        return await conn.fetchrow(
            'SELECT * FROM "sessions" WHERE id = $1 AND user_id = $2',
            session_id, user_id,
        )

    async def exists_for_user(
        self, conn: asyncpg.Connection, session_id: str, user_id: str
    ) -> bool:
        """只判断存在性，不读 messages（问答前校验用，避免加载长历史）"""
        row = await conn.fetchrow(
            'SELECT 1 FROM "sessions" WHERE id = $1 AND user_id = $2',
            session_id, user_id,
        )
        return row is not None

    async def create(
        self, conn: asyncpg.Connection, user_id: str, title: str
    ) -> asyncpg.Record:
        return await conn.fetchrow(
            'INSERT INTO "sessions" (user_id, title) VALUES ($1, $2) RETURNING *',
            user_id, title,
        )

    async def append_turn(
        self,
        conn: asyncpg.Connection,
        session_id: str,
        user_id: str,
        messages: list[dict],
        title: str,
        default_title: str,
    ) -> asyncpg.Record | None:
        """
        追加消息。单条 UPDATE 完成「读-改-写」，避免并发问答时互相覆盖。

        仅当标题仍是默认值时，才用 title（问题前 30 字）替换；
        用户手动设置过的标题保持不变。
        """
        return await conn.fetchrow(
            """
            UPDATE "sessions"
            SET messages = messages || $1::jsonb,
                title = CASE WHEN title = $2::varchar THEN $3::varchar ELSE title END,
                updated_at = NOW()
            WHERE id = $4 AND user_id = $5
            RETURNING id, title, jsonb_array_length(messages) AS message_count,
                      created_at, updated_at
            """,
            json.dumps(messages, ensure_ascii=False), default_title, title,
            session_id, user_id,
        )

    async def delete_for_user(
        self, conn: asyncpg.Connection, session_id: str, user_id: str
    ) -> bool:
        row = await conn.fetchrow(
            'DELETE FROM "sessions" WHERE id = $1 AND user_id = $2 RETURNING id',
            session_id, user_id,
        )
        return row is not None
