import { useEffect, useMemo, useRef, useState } from "react";
import { accountId } from "./account-frame";
import { Client } from "./transport";

export type BrowserAccount = {
  id: string;
  label: string;
  origin: string;
  read_path: string;
  browser_profile?: number;
};

export function BrowserSetup({
  client,
  enabled,
  changed,
}: {
  client: Client;
  enabled: boolean;
  changed: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const locked = useRef(false);
  return (
    <form
      autoComplete="off"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!enabled || locked.current) return;
        const form = event.currentTarget,
          data = new FormData(form);
        locked.current = true;
        setBusy(true);
        setNotice("");
        try {
          await client.request("/v1/account-sessions/browser", "POST", {
            label: data.get("label"),
            origin: data.get("origin"),
            read_path: data.get("path"),
          });
          form.reset();
          setNotice(
            "Account created. Select it below to open its private browser.",
          );
        } catch {
          setNotice(
            "Account setup was interrupted or rejected. Refresh the list before trying again; no automatic retry was sent.",
          );
        } finally {
          locked.current = false;
          setBusy(false);
          changed();
        }
      }}
    >
      <h3>Set up a private browser account</h3>
      <p>
        Choose an exact HTTPS website and starting page. Do not put passwords,
        tokens or sign-in links in these fields.
      </p>
      <fieldset disabled={!enabled || busy}>
        <label>
          Account label
          <input name="label" required maxLength={80} />
        </label>
        <label>
          Website origin
          <input
            name="origin"
            type="url"
            placeholder="https://example.org"
            required
            maxLength={2048}
          />
        </label>
        <label>
          Starting page
          <input name="path" defaultValue="/" required maxLength={1001} />
        </label>
        <button type="submit">Create browser account</button>
      </fieldset>
      {notice && <p role="status">{notice}</p>}
    </form>
  );
}

export function AccountBrowser({
  client,
  account,
  enabled,
}: {
  client: Client;
  account: BrowserAccount;
  enabled: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const lock = useRef(false);
  const context = useMemo(
    () => ({ disposed: false, ended: false, path: "", timer: 0 }),
    [client, account.id],
  );
  const [busy, setBusy] = useState(false),
    [opened, setOpened] = useState(false);
  const [frame, setFrame] = useState(""),
    [usable, setUsable] = useState(false);
  const [text, setText] = useState(""),
    [notice, setNotice] = useState("");
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    context.disposed = false;
    return () => {
      context.disposed = true;
      clearTimeout(context.timer);
      if (context.path)
        void client.request(context.path, "DELETE").catch(() => {});
    };
  }, [client, context]);

  async function refresh(path: string) {
    setUsable(false);
    setFrame("");
    const value = await client.accountFrame(
      account.id,
      path.split("/").at(-1)!,
    );
    if (!context.disposed && !context.ended && context.path === path)
      setFrame(value);
  }
  async function start() {
    if (!enabled || lock.current || context.disposed || context.path) return;
    context.ended = false;
    lock.current = true;
    setBusy(true);
    setNotice("");
    setExpired(false);
    setFrame("");
    setText("");
    setUsable(false);
    dialog.current?.showModal();
    const started = Date.now();
    try {
      const value = await client.request<{
        handoff_id: string;
        lifetime_seconds: number;
      }>(`/v1/account-sessions/${account.id}/browser`, "POST");
      if (!accountId.test(value?.handoff_id) || value.lifetime_seconds !== 300)
        throw new Error("Invalid handoff");
      const path = `/v1/account-sessions/${account.id}/browser/${value.handoff_id}`;
      context.path = path;
      if (context.disposed) {
        await client.request(path, "DELETE");
        context.path = "";
        return;
      }
      setOpened(true);
      context.timer = window.setTimeout(
        () => {
          context.ended = true;
          setExpired(true);
          setFrame("");
          setText("");
          setUsable(false);
          setNotice(
            "This five-minute handoff has ended. Discard and reopen to continue.",
          );
        },
        Math.max(0, 300000 - (Date.now() - started)),
      );
      await refresh(path);
    } catch {
      if (!context.disposed)
        setNotice(
          "The private browser could not load. No automatic retry was sent. Discard before reopening; an unacknowledged start expires within five minutes.",
        );
    } finally {
      lock.current = false;
      if (!context.disposed) setBusy(false);
    }
  }
  async function operate(
    operation: "input" | "refresh" | "save" | "discard",
    body?: unknown,
  ) {
    if (lock.current || context.disposed || !context.path) return;
    if (context.ended && operation !== "discard") return;
    lock.current = true;
    setBusy(true);
    setUsable(false);
    setFrame("");
    setNotice("");
    const path = context.path;
    try {
      if (operation === "input")
        await client.request(path + "/input", "POST", body);
      if (operation === "input" || operation === "refresh") await refresh(path);
      else {
        await client.request(
          path + (operation === "save" ? "/save" : ""),
          operation === "save" ? "POST" : "DELETE",
        );
        context.path = "";
        clearTimeout(context.timer);
        setOpened(false);
        setText("");
        dialog.current?.close();
        trigger.current?.focus();
      }
    } catch {
      if (!context.disposed)
        setNotice(
          "The operation was interrupted or rejected. Input was not retried. Refresh to review the page, or discard. A lost save response does not establish that the profile was saved.",
        );
    } finally {
      lock.current = false;
      if (!context.disposed) setBusy(false);
    }
  }
  return (
    <>
      <button
        ref={trigger}
        disabled={!enabled || busy}
        onClick={() => void start()}
      >
        Open private browser
      </button>
      <dialog
        ref={dialog}
        className="account-browser-dialog"
        aria-label="Private account browser"
        onCancel={(event) => {
          event.preventDefault();
          if (!busy) {
            if (context.path) void operate("discard");
            else dialog.current?.close();
          }
        }}
      >
        <h2>{account.label}</h2>
        <p>
          {account.origin}
          {account.read_path}
        </p>
        <p>
          Private owner view. Page images and typed input are not sent to Work
          or the model. Form submissions, including login, are currently
          blocked. The browser closes after five minutes.
        </p>
        {notice && <p role="alert">{notice}</p>}
        {busy && <p role="status">Updating private browser…</p>}
        {frame && (
          <button
            className="account-browser-image"
            type="button"
            disabled={!usable || busy || expired}
            aria-label="Click private page"
            onClick={(event) => {
              if (!usable || busy || expired || event.detail === 0) return;
              const box = event.currentTarget
                .querySelector("img")!
                .getBoundingClientRect();
              const x = Math.floor(
                ((event.clientX - box.left) * 1024) / box.width,
              );
              const y = Math.floor(
                ((event.clientY - box.top) * 768) / box.height,
              );
              if (x >= 0 && x < 1024 && y >= 0 && y < 768)
                void operate("input", { op: "click", x, y });
            }}
          >
            <img
              src={frame}
              alt="Private website page"
              draggable={false}
              onLoad={(event) => {
                if (
                  !context.ended &&
                  !context.disposed &&
                  event.currentTarget.naturalWidth === 1024 &&
                  event.currentTarget.naturalHeight === 768
                )
                  setUsable(true);
                else {
                  setFrame("");
                  setNotice("Invalid private page dimensions.");
                }
              }}
              onError={() => {
                setFrame("");
                setUsable(false);
                setNotice("The private page image could not be decoded.");
              }}
            />
          </button>
        )}
        <form
          autoComplete="off"
          onSubmit={(event) => {
            event.preventDefault();
            if (!usable || busy || expired || !text) return;
            const value = text;
            setText("");
            void operate("input", { op: "text", text: value });
          }}
        >
          <label>
            Text for focused website field
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              maxLength={2048}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={!usable || busy || expired}
            />
          </label>
          <button disabled={!usable || busy || expired || !text}>
            Send text once
          </button>
        </form>
        <div className="account-browser-controls">
          {["Tab", "Enter", "Backspace", "Escape", "ArrowUp", "ArrowDown"].map(
            (key) => (
              <button
                key={key}
                disabled={!usable || busy || expired}
                onClick={() => void operate("input", { op: "key", key })}
              >
                Send {key}
              </button>
            ),
          )}
          <button
            disabled={!opened || busy || expired}
            onClick={() => void operate("refresh")}
          >
            Refresh private page
          </button>
          <button
            disabled={!opened || busy || expired || !usable}
            onClick={() => void operate("save")}
          >
            Save profile and close
          </button>
          <button
            disabled={busy}
            onClick={() => {
              setText("");
              if (context.path) void operate("discard");
              else dialog.current?.close();
            }}
          >
            Discard and close
          </button>
        </div>
        <p>
          Saving keeps an encrypted local profile. Discarding abandons unsaved
          local changes; it cannot undo website requests or log you out
          remotely.
        </p>
      </dialog>
    </>
  );
}
