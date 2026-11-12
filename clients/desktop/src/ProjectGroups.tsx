import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

type Kind = "history" | "task" | "input";
interface Source {kind: Kind; id: string; name: string; key: string; title: string; source_sha256: string; snapshot_sha256: string}
interface Group {id: string; name: string; revision: number}
interface Preview {preview_sha256: string; sources: Source[]; ambiguous: string[];
  decisions: {source_key: string; decision: string}[];
  suggestions: {evidence_kind: string; value: string; strength: string; members: string[]}[]}
const refs = (rows: Source[]) => rows.map(({kind, id, name}) => ({kind, id, name}));

export function ProjectGroups({client, active, owner}: {client: Client; active: boolean; owner: boolean}) {
  const [opened, setOpened] = useState(false), [busy, setBusy] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]), [members, setMembers] = useState<Source[]>([]);
  const [groupId, setGroupId] = useState(""), [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("history"), [sources, setSources] = useState<Source[]>([]);
  const [offset, setOffset] = useState(0), [groupOffset, setGroupOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]), [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [remove, setRemove] = useState(false);
  const epoch = useRef(0);
  const retry = useRef<{key: string; id: string} | null>(null);
  useEffect(() => {
    epoch.current++; setOpened(false); setGroups([]); setMembers([]); setSources([]);
    setSelected([]); setPreview(null); setGroupId(""); setName(""); setError(""); setNotice(""); setBusy(false);
    return () => { epoch.current++; };
  }, [active, client]);
  const chosen = groups.find(g => g.id === groupId);
  async function act(fn: (live: () => boolean) => Promise<void>) {
    if (busy) return;
    const own = ++epoch.current; setBusy(true); setError(""); setNotice("");
    try { await fn(() => own === epoch.current); }
    catch(e) { if (own === epoch.current) setError(String(e)); }
    finally { if (own === epoch.current) setBusy(false); }
  }
  async function loadGroups(at: number, live: () => boolean) {
    const rows = await client.request<Group[]>(`/v1/project-groups?offset=${at}`);
    if (live()) { setGroups(rows); setGroupOffset(at); setOpened(true); setGroupId(""); setMembers([]); setPreview(null); }
  }
  function clearReview() { setPreview(null); setRemove(false); setNotice(""); }
  const picked = sources.filter(s => selected.includes(s.key));
  return <section hidden={!active} aria-label="Related projects">
    <h2>Related projects</h2>
    <p>Groups link originals; they do not merge content, copy memories or grant access. Hidden, removed or changed sources are omitted until reviewed again.</p>
    <button disabled={busy} onClick={() => void act(live => loadGroups(0, live))}>Browse project groups</button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {opened && <>
      <label>Project group<select value={groupId} disabled={busy} onChange={e => {
        setGroupId(e.target.value); setMembers([]); clearReview();
        setName(groups.find(g => g.id === e.target.value)?.name || "");
      }}><option value="">New group / no group selected</option>{groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
      <button disabled={busy || !groupOffset} onClick={() => void act(live => loadGroups(Math.max(0, groupOffset - 50), live))}>Previous groups</button>
      <button disabled={busy || groups.length !== 50} onClick={() => void act(live => loadGroups(groupOffset + 50, live))}>Next groups</button>
      {chosen && <button disabled={busy} onClick={() => void act(async live => {
        const result = await client.request<{members: Source[]}>(`/v1/project-groups/${chosen.id}`);
        if (live()) setMembers(result.members);
      })}>Read linked sources</button>}
      <ul aria-label="Linked originals">{members.map(s => <li key={s.key}>{s.title} · {s.kind}{s.name && ` · ${s.name}`}<br/>Source fingerprint: <code>{s.source_sha256}</code><br/>Source: {s.id}</li>)}</ul>
      {owner && <>
        <label>Group name<input value={name} maxLength={120} disabled={busy} onChange={e => setName(e.target.value)}/></label>
        {chosen && <>
          <button disabled={busy || !name.trim()} onClick={() => void act(async live => {
            await client.request(`/v1/project-groups/${chosen.id}`, "PATCH", {revision: chosen.revision, name});
            if (live()) { await loadGroups(groupOffset, live); setNotice("Group renamed; originals unchanged."); }
          })}>Rename group</button>
          <button disabled={busy} onClick={() => setRemove(true)}>Remove group…</button>
          {remove && <><p>Remove only this group and its associations? Original sources and memories remain.</p>
            <button disabled={busy} onClick={() => void act(async live => {
              await client.request(`/v1/project-groups/${chosen.id}?revision=${chosen.revision}`, "DELETE");
              if (live()) { await loadGroups(groupOffset, live); setRemove(false); setNotice("Group removed; originals retained."); }
            })}>Confirm group removal</button></>}
        </>}
        <label>Sources to review<select disabled={busy} value={kind} onChange={e => {
          setKind(e.target.value as Kind); setOffset(0); setSources([]); setSelected([]); clearReview();
        }}><option value="history">Imported conversations</option><option value="task">Work tasks</option><option value="input">Original Work inputs</option></select></label>
        <button disabled={busy} onClick={() => void act(async live => {
          const rows = await client.request<Source[]>(`/v1/project-groups/sources?kind=${kind}&offset=${offset}`);
          if (live()) { setSources(rows); setSelected([]); clearReview(); }
        })}>Load source page</button>
        <button disabled={busy || !offset} onClick={() => { setOffset(Math.max(0, offset - 50)); setSources([]); setSelected([]); clearReview(); }}>Previous source page</button>
        <button disabled={busy || sources.length !== 50} onClick={() => { setOffset(offset + 50); setSources([]); setSelected([]); clearReview(); }}>Next source page</button>
        <p>Up to 50 sources per page. Select sources deliberately; suggestions never apply themselves.</p>
        {sources.map(s => <label key={s.key}><input type="checkbox" disabled={busy} checked={selected.includes(s.key)} onChange={e => {
          setSelected(e.target.checked ? [...selected, s.key] : selected.filter(k => k !== s.key)); clearReview();
        }}/>{s.title} · {s.kind} · {s.source_sha256.slice(0, 12)}</label>)}
        <button disabled={busy || !picked.length} onClick={() => void act(async live => {
          const result = await client.request<Preview>("/v1/project-groups/preview", "POST", {sources: refs(picked), group_id: groupId || null});
          if (live()) setPreview(result);
        })}>Review associations</button>
        {preview && <div aria-label="Association review">
          <p>Reviewing {preview.sources.length} sources. Bounded text hints are not complete inspection.</p>
          <ul>{preview.suggestions.map((s, i) => <li key={i}>{s.strength}: {s.value} ({s.members.length} sources)</li>)}</ul>
          {preview.ambiguous.length > 0 && <p>Multiple identifiers found. Keep mixed topics intact; choose links manually or leave ungrouped.</p>}
          {preview.decisions.map((d, i) => <p key={i}>Saved decision: {d.decision}</p>)}
          {(["accepted", "rejected", "ungrouped"] as const).map(decision => <button key={decision} disabled={busy || (decision === "accepted" && !groupId && !name.trim()) || (decision === "rejected" && !groupId)} onClick={() => void act(async live => {
            const payload = {sources: refs(preview.sources), group_id: groupId || null, preview_sha256: preview.preview_sha256, name, decision};
            const key = JSON.stringify(payload);
            if (retry.current?.key !== key) retry.current = {key, id: crypto.randomUUID()};
            await client.request("/v1/project-groups/apply", "POST", {...payload, request_id: retry.current.id});
            retry.current = null;
            if (live()) { await loadGroups(0, live); setSelected([]); setNotice(`Association decision saved: ${decision}. Originals unchanged.`); }
          })}>{decision === "accepted" ? "Link reviewed sources" : decision === "rejected" ? "Reject links to this group" : "Leave ungrouped"}</button>)}
        </div>}
      </>}
    </>}
  </section>;
}
