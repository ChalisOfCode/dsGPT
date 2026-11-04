export interface ResearchCapabilities {
  public_page_reading: boolean;
  search_configured: boolean;
}
export interface ResearchSource {
  id: string;
  url: string;
  final_url?: string;
  title?: string;
  status: string;
  retrieved_at?: string;
  published_at?: string | null;
  content_sha256?: string;
}
export interface ResearchSources {
  sources: ResearchSource[];
  retrieval_complete: boolean;
  warnings: string[];
}

// External navigation is deliberately narrower than the backend reader. Native
// code rechecks this boundary before opening the system browser, without tokens.
export function publicSourceURL(raw: string): string {
  if (raw.length > 4096 || /[\u0000-\u0020\\]/.test(raw))
    throw new Error("Use a public HTTPS source URL.");
  const url = new URL(raw);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.port ||
    !url.hostname.includes(".") ||
    url.hostname.endsWith(".") ||
    /[\[\]:]/.test(url.hostname) ||
    /^\d+\.\d+\.\d+\.\d+$/.test(url.hostname) ||
    /\.(localhost|local|internal|invalid)$/.test(url.hostname)
  )
    throw new Error(
      "Use a public HTTPS domain without credentials or a custom port.",
    );
  return url.href;
}

export function researchOptions(search: boolean, text: string) {
  const urls = [
    ...new Set(
      text
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
  if (urls.length > 6)
    throw new Error("Use up to six source URLs, one per line.");
  urls.forEach(publicSourceURL);
  if (!search && urls.length === 0)
    throw new Error("Add a source URL or enable configured web search.");
  return { search, urls };
}

export function citationParts(text: string, sources: ResearchSource[]) {
  const retrieved = sources.filter((s) => s.status === "retrieved");
  const pattern = /\[S(\d+)\]\(<(https:\/\/[^>\s]+)>\)/g;
  const parts: { text: string; source?: ResearchSource }[] = [];
  let position = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push({ text: text.slice(position, match.index) });
    const source = retrieved[Number(match[1]) - 1];
    parts.push(
      source?.final_url === match[2]
        ? { text: `S${match[1]}`, source }
        : { text: match[0] },
    );
    position = match.index! + match[0].length;
  }
  parts.push({ text: text.slice(position) });
  return parts;
}
