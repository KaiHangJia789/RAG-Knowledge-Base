"use client";

import { useEffect, useRef } from "react";
import type { ChunkContext } from "@/lib/api";

/** 展示被引用的块及其前后文，目标块加亮边框并滚动到可见区域（黑底白字，便于阅读） */
export function ChunkContextView({ ctx }: { ctx: ChunkContext }) {
  const targetRef = useRef<HTMLLIElement | null>(null);
  const target = ctx.items.find((x) => x.is_target);

  useEffect(() => {
    targetRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [ctx]);

  return (
    <div
      style={{
        marginTop: 12,
        padding: 12,
        borderRadius: 6,
        background: "#000",
        color: "#fff",
        maxWidth: "80%",
      }}
    >
      <p style={{ marginBottom: 8 }}>
        <strong>原文定位：</strong>
        {ctx.filename}（块 {target?.chunk_index ?? "?"}，策略 {ctx.chunk_strategy}）
      </p>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {ctx.items.map((item) => (
          <li
            key={item.chunk_id}
            ref={item.is_target ? targetRef : undefined}
            style={{
              padding: "8px 10px",
              marginBottom: 6,
              borderRadius: 4,
              background: item.is_target ? "#1c1c1c" : "transparent",
              borderLeft: item.is_target ? "3px solid #fff" : "3px solid transparent",
              color: item.is_target ? "#fff" : "#9a9a9a",
            }}
          >
            <small style={{ color: item.is_target ? "#fff" : "#9a9a9a" }}>
              第 {item.chunk_index} 块
              {item.page_number != null && `，第 ${item.page_number} 页`}
              {item.is_target && "（被引用）"}
            </small>
            <p style={{ margin: "4px 0 0", whiteSpace: "pre-wrap" }}>{item.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
