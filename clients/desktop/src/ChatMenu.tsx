import { useState, useEffect } from "react";
import type { Conversation } from "./types";
import { Client } from "./transport";
import { AttachmentHistory, type AttachmentRecord } from "./Attachments";

export function ChatMenu({
  chat,
  change,
  remove,
  files,
}: {
  chat: Conversation;
  change: (c: Conversation, v: Record<string, unknown>) => void;
  remove: (c: Conversation) => void;
  files: (c: Conversation) => void;
}) {
  const [renaming, setRenaming] = useState(false),
    [title, setTitle] = useState(chat.title);
  return (
    <>
      <details className="chat-menu">
        <summary aria-label={`Actions for ${chat.title}`}>⋯</summary>
        <div className="menu">
          <button
            onClick={() => {
              setTitle(chat.title);
              setRenaming(true);
            }}
          >
            Rename
          </button>
          <button onClick={() => change(chat, { pinned: !chat.pinned })}>
            {chat.pinned ? "Unpin" : "Pin"}
          </button>
          <button onClick={() => files(chat)}>Files</button>
          <button onClick={() => change(chat, { hidden: true })}>Hide</button>
          <button onClick={() => remove(chat)}>Delete chat</button>
        </div>
      </details>
      {renaming && (
        <div className="modal-backdrop">
          <form
            className="chat-files"
            role="dialog"
            aria-modal="true"
            aria-label="Rename chat"
            onSubmit={(e) => {
              e.preventDefault();
              if (title.trim()) {
                change(chat, { title: title.trim() });
                setRenaming(false);
              }
            }}
          >
            <h2>Rename chat</h2>
            <input
              autoFocus
              value={title}
              maxLength={300}
              onChange={(e) => setTitle(e.target.value)}
              aria-label="Chat name"
            />
            <div className="work-actions">
              <button type="button" onClick={() => setRenaming(false)}>
                Cancel
              </button>
              <button disabled={!title.trim()}>Save</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
export function ChatFiles({
  client,
  chat,
  onClose,
}: {
  client: Client;
  chat: Conversation;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<AttachmentRecord[]>([]),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [more, setMore] = useState(true);
  useEffect(() => {
    let live = true;
    void client
      .request<AttachmentRecord[]>(`/v1/conversations/${chat.id}/files`)
      .then((batch) => {
        if (live) {
          setFiles(batch);
          setMore(batch.length === 100);
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [client, chat.id]);
  async function load() {
    try {
      const batch = await client.request<AttachmentRecord[]>(
        `/v1/conversations/${chat.id}/files?offset=${files.length}`,
      );
      setFiles([...files, ...batch]);
      setMore(batch.length === 100);
      setLoaded(true);
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <div className="modal-backdrop">
      <section
        className="chat-files"
        role="dialog"
        aria-modal="true"
        aria-label={`Files in ${chat.title}`}
      >
        <div className="work-actions">
          <h2>Files in {chat.title}</h2>
          <button autoFocus onClick={onClose}>
            Close
          </button>
        </div>
        <AttachmentHistory client={client} chatId={chat.id} files={files} />
        {loaded && !files.length && <p>No files attached to this chat.</p>}
        {more && (
          <button onClick={() => void load()}>
            {loaded ? "Load more files" : "Show files"}
          </button>
        )}
        {error && <p role="alert">{error}</p>}
      </section>
    </div>
  );
}
