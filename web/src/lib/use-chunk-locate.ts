"use client";

import { useRef, useState } from "react";
import { getChunkContext, type ChunkContext } from "@/lib/api";

/**
 * 引用定位状态。
 * 快速连续点击多条引用时，只采用最后一次点击的结果；
 * clear() 会作废还在进行中的请求（例如切换了问题或会话）。
 */
export function useChunkLocate() {
  const [activeChunk, setActiveChunk] = useState<ChunkContext | null>(null);
  const [chunkError, setChunkError] = useState<string | null>(null);
  const reqId = useRef(0);

  async function locate(chunkId: string) {
    const current = ++reqId.current;
    setChunkError(null);
    try {
      const ctx = await getChunkContext(chunkId);
      if (current === reqId.current) setActiveChunk(ctx);
    } catch (e) {
      if (current === reqId.current) {
        setActiveChunk(null);
        setChunkError(e instanceof Error ? e.message : "定位失败");
      }
    }
  }

  function clear() {
    reqId.current++;
    setActiveChunk(null);
    setChunkError(null);
  }

  return { activeChunk, chunkError, locate, clear };
}
