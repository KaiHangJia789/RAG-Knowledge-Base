"use client";

import { createContext, useContext } from "react";

export type PreviewSelection = { id: string; filename: string; chunkId?: string; chunkIds?: string[] };
export type PreviewContent = {
  document_id: string;
  filename: string;
  items: { chunk_id: string; chunk_index: number; text: string; page_number: number | null; is_target: boolean }[];
};

export const WorkspaceContext = createContext<{
  openDocument: (selection: PreviewSelection) => void;
  closeDocument: (id: string) => void;
}>({ openDocument: () => {}, closeDocument: () => {} });

export const useWorkspace = () => useContext(WorkspaceContext);
