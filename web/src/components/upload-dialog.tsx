"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { getUploadLimits, uploadDocuments, type UploadLimits, type UploadResult } from "@/lib/api";

const MB = 1024 * 1024;

function selectionError(files: File[], limits: UploadLimits): string | null {
  if (files.length > limits.max_files) return `每批最多选择 ${limits.max_files} 个文件`;
  for (const file of files) {
    if (file.size > limits.max_file_size_mb * MB) return `${file.name} 超过单文件 ${limits.max_file_size_mb} MB 限制`;
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!limits.allowed_extensions.includes(extension)) return `${file.name} 的格式不受支持`;
  }
  if (files.reduce((sum, file) => sum + file.size, 0) > limits.max_total_size_mb * MB) return `每批文件合计不能超过 ${limits.max_total_size_mb} MB`;
  return null;
}

export function UploadDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const busyRef = useRef(false);
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [limitVersion, setLimitVersion] = useState(0);
  const [limitsError, setLimitsError] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const invalid = limits ? selectionError(files, limits) : null;
  const total = files.reduce((sum, file) => sum + file.size, 0);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  useEffect(() => {
    let cancelled = false;
    getUploadLimits().then((value) => { if (!cancelled) setLimits(value); }, (reason) => {
      if (!cancelled) setLimitsError(reason instanceof Error ? reason.message : "上传限制加载失败");
    });
    return () => { cancelled = true; };
  }, [limitVersion]);

  async function startUpload() {
    if (busyRef.current || !limits || invalid || !files.length || results) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await uploadDocuments(files);
      setResults(response.items);
    } catch (reason) {
      setError(`${reason instanceof Error ? reason.message : "上传失败"}。请先关闭窗口并刷新文档列表确认结果，再选择需要重传的文件。`);
      setFiles([]);
    } finally {
      onUploaded();
      busyRef.current = false;
      setBusy(false);
    }
  }

  return <dialog ref={dialogRef} className="settings-dialog upload-dialog" aria-labelledby="upload-title"
    onCancel={(event) => { event.preventDefault(); if (!busyRef.current) onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget && !busyRef.current) onClose(); }}>
    <div className="settings-content">
      <header className="settings-header"><div><span className="eyebrow">添加知识资料</span><h2 id="upload-title">批量上传文档</h2></div><button className="icon-button" type="button" aria-label="关闭上传窗口" disabled={busy} onClick={onClose}><Icon name="close" /></button></header>
      {!limits && !limitsError && <p className="muted upload-limits" role="status">正在获取上传限制…</p>}
      {limitsError && <div className="upload-limits"><p role="alert" className="error-message">{limitsError}</p><button type="button" className="secondary-button" onClick={() => { setLimitsError(null); setLimitVersion((value) => value + 1); }}>重试</button></div>}
      {limits && <>
        <p className="upload-limits muted">每批最多 {limits.max_files} 个 · 单文件 ≤ {limits.max_file_size_mb} MB · 合计 ≤ {limits.max_total_size_mb} MB<br /><small>1 MB = 1024 × 1024 字节</small></p>
        <label className={`upload-picker ${busy ? "is-disabled" : ""}`}><Icon name="upload" size={24} /><span>选择文件，可一次多选</span><small>{limits.allowed_extensions.join(" / ")}</small><input type="file" multiple accept={limits.allowed_extensions.join(",")} disabled={busy} aria-label="选择上传文件" onChange={(event) => { setFiles(Array.from(event.target.files ?? [])); setError(null); setResults(null); event.target.value = ""; }} /></label>
        {files.length > 0 && <p className="upload-selection">已选择 {files.length} 个文件 · {(total / MB).toFixed(2)} MB</p>}
        {(invalid || error) && <p role="alert" className="error-message upload-feedback">{invalid || error}</p>}
        {results ? <>
          <p className="upload-summary" role="status">处理完成：成功 {results.filter((result) => result.success).length} 个，失败 {results.filter((result) => !result.success).length} 个</p>
          <ul className="upload-file-list" aria-label="上传结果">{results.map((result, index) => <li key={index}><span className="upload-filename" title={result.filename}>{result.filename}</span><span className={result.success ? "success-message" : "error-message"}>{result.message}</span></li>)}</ul>
        </> : files.length > 0 && <ul className="upload-file-list" aria-label="待上传文件">{files.map((file, index) => <li key={index}><span className="upload-filename" title={file.name}>{file.name}</span><small className="muted">{(file.size / MB).toFixed(2)} MB</small></li>)}</ul>}
        {busy && <p className="upload-feedback muted" role="status">正在上传并处理 {files.length} 个文件，请保持窗口打开…</p>}
        <p className="upload-note muted">PDF、MD、TXT 会自动解析。其他支持格式可保存文件，暂不支持正文预览和问答检索。文件逐个处理，较大资料可能需要几分钟。</p>
        <div className="upload-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>{results ? "完成" : "取消"}</button><button type="button" className="primary-button" disabled={busy || !files.length || !!invalid || !!results} onClick={() => void startUpload()}>{busy ? "正在处理…" : "开始上传"}</button></div>
      </>}
    </div>
  </dialog>;
}
