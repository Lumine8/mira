import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import {
  createDocument,
  createPdfDocument,
  deleteDocument,
  fetchDocuments,
  type DocumentSummary,
} from "../../lib/api";

function authorLabel(author: "founder" | "mira"): string {
  return author === "mira" ? "by Mira" : "given to Mira";
}

function dateLabel(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return "";
  }
}

const MAX_UPLOAD_BYTES = 200 * 1024;
// PDFs are compressed, so the raw file can be much bigger than the text it
// becomes; the server extracts and stores the text.
const MAX_PDF_UPLOAD_BYTES = 20 * 1024 * 1024;

export default function DocumentsScreen({
  onHome,
  onOpenDocument,
}: {
  onHome: () => void;
  onOpenDocument: (name: string) => void;
}) {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const attempt = (delayMs: number) => {
      window.setTimeout(() => {
        if (cancelled) return;
        fetchDocuments()
          .then((list) => { if (!cancelled) setDocs(list); })
          .catch((err) => {
            if (cancelled) return;
            if (delayMs === 0) {
              // The backend may still be settling (a reload during deploy can
              // hit a half-awake proxy); try once more before giving up.
              attempt(1200);
              return;
            }
            setError(`documents did not load: ${err}`);
          });
      }, delayMs);
    };
    attempt(0);
    return () => { cancelled = true; };
  }, []);

  const refresh = () => {
    setDocs(null);
    fetchDocuments()
      .then(setDocs)
      .catch((err) => setError(`documents did not load: ${err}`));
  };

  const pickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const isPdf = file.name.toLowerCase().endsWith(".pdf");
    if (file.size > (isPdf ? MAX_PDF_UPLOAD_BYTES : MAX_UPLOAD_BYTES)) {
      setError(
        isPdf
          ? "That PDF is over 20 MB. Split it into smaller files."
          : "That file is over 200 KB — paste its text instead, or split it.",
      );
      return;
    }
    setFileName(file.name);
    setTitle(file.name.replace(/\.[^.]+$/, ""));
    setError(null);
    if (isPdf) {
      // The server extracts the text; Mira reads the extracted paper.
      setPdfFile(file);
      setContent("");
      return;
    }
    setPdfFile(null);
    const reader = new FileReader();
    reader.onload = () => {
      setContent(String(reader.result ?? "").trim());
      setError(null);
    };
    reader.onerror = () => setError("Could not read that file as text.");
    reader.readAsText(file);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !title.trim()) return;
    if (!pdfFile && !content.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const doc = pdfFile
        ? await createPdfDocument(pdfFile, title.trim())
        : await createDocument(title.trim(), content.trim());
      onOpenDocument(doc.name);
      setAdding(false);
      setTitle("");
      setContent("");
      setFileName("");
      setPdfFile(null);
      refresh();
    } catch (err) {
      setError(
        pdfFile
          ? `could not read that PDF: ${err}`
          : `could not add the document: ${err}`,
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (d: DocumentSummary) => {
    if (!window.confirm(`Delete "${d.name}" from the shared folder?`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteDocument(d.name);
      setNotice(`Deleted "${d.name}".`);
      refresh();
    } catch (err) {
      setError(`could not delete "${d.name}": ${err}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="documents">
      <header className="documents__header">
        <button className="documents__back" type="button" onClick={onHome}>
          ← home
        </button>
        <h1 className="documents__title">Her papers</h1>
        <p className="documents__subtitle">
          Documents you hand her, and the papers she writes — one shared folder.
        </p>
        <div className="documents__header-actions">
          <button
            className="documents__cta"
            type="button"
            onClick={() => {
              setAdding((v) => {
                if (v) {
                  setTitle("");
                  setContent("");
                  setFileName("");
                  setPdfFile(null);
                }
                return !v;
              });
              setError(null);
            }}
            disabled={busy}
          >
            {adding ? "Close" : "+ Add a document"}
          </button>
        </div>
      </header>

      {error && <div className="documents__error">{error}</div>}
      {notice && <div className="documents__notice">{notice}</div>}

      {adding && (
        <form className="documents__add" onSubmit={submit}>
          <h2>Hand Mira a document</h2>
          <p className="documents__muted">
            Pasting text, or picking a file, stores a copy in the shared folder.
            PDFs are read on the server and turned into a paper Mira can read.
          </p>
          <input
            className="documents__input"
            type="file"
            accept=".txt,.md,.csv,.json,.log,.py,.js,.ts,.html,.css,.pdf,.doc,.docx"
            onChange={pickFile}
            aria-label="Pick a document file"
          />
          {fileName && (
            <p className="documents__muted">
              Picked: {fileName}
              {pdfFile ? " — a PDF; its text will be extracted." : ""}
            </p>
          )}
          <input
            className="documents__input"
            type="text"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Document title"
          />
          {!pdfFile && (
            <textarea
              className="documents__textarea"
              placeholder="The document itself…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              aria-label="Document content"
            />
          )}
          <button
            className="documents__cta"
            type="submit"
            disabled={busy || !title.trim() || (!pdfFile && !content.trim())}
          >
            {busy ? "Adding…" : pdfFile ? "Extract & add it" : "Add it"}
          </button>
        </form>
      )}

      <div className="documents__grid">
        {docs === null && !error && <div className="documents__loading" aria-label="loading" />}
        {(docs ?? []).map((d) => (
          <button
            key={`${d.author}/${d.name}`}
            className="documents__card"
            type="button"
            onClick={() => onOpenDocument(d.name)}
          >
            <div className="documents__card-head">
              <span className={`documents__author documents__author--${d.author}`}>
                {authorLabel(d.author)}
              </span>
              <span className="documents__date">{dateLabel(d.modified_at)}</span>
            </div>
            <div className="documents__card-title">{d.name}</div>
            {d.preview && <p className="documents__card-preview">{d.preview}</p>}
            <div className="documents__card-foot">
              <span>{d.size} B</span>
              <button
                className="documents__delete"
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void remove(d);
                }}
                disabled={busy}
                aria-label={`Delete ${d.name}`}
              >
                delete
              </button>
            </div>
          </button>
        ))}
        {docs !== null && docs.length === 0 && (
          <p className="documents__empty">
            The folder is empty. Add a document, or ask Mira to write one.
          </p>
        )}
      </div>
    </div>
  );
}