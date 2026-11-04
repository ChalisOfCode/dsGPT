type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : {};
const select = (source: RecordValue, keys: string[]) =>
  Object.fromEntries(
    keys.filter((key) => key in source).map((key) => [key, source[key]]),
  );

export function DiagnosticsPanel({ value }: { value: unknown }) {
  const original = record(value);
  const files = record(original.files);
  let system = original;
  try {
    if (typeof files["desktop/system-info.json"] === "string")
      system = record(JSON.parse(files["desktop/system-info.json"]));
  } catch {
    /* Keep the full reviewed response visible if a file cannot be parsed. */
  }
  if (!system.app_version) return <pre>{JSON.stringify(value, null, 2)}</pre>;
  const categories: [string, unknown][] = [
    [
      "Overview",
      select(system, [
        "app_version",
        "captured_at",
        "platform",
        "os_release",
        "database_version",
        "limitations",
      ]),
    ],
    [
      "Application Health",
      select(system, [
        "running_replies",
        "work_capability",
        "code_execution_available",
        "saved_memories",
      ]),
    ],
    [
      "Hardware Performance",
      select(system, [
        "architecture",
        "cpu_logical",
        "cpu_physical",
        "cpu_utilization_percent",
        "cpu_temperature_celsius",
        "ram_total_bytes",
        "ram_available_bytes",
        "process_rss_bytes",
        "disk_free_bytes",
        "gpu",
        "unavailable_measurements",
      ]),
    ],
    ["AI Model and Inference", system.inference],
    ["Work Agent and Development", system.work],
    ["Network and Tailscale", system.network],
    ["Errors and Warnings", system.recent_errors],
    [
      "Diagnostic History",
      system.snapshot_history ||
        files["desktop/application-events.jsonl"] ||
        "Preview an export to review retained events.",
    ],
    ["Advanced Logging", system.logging],
  ];
  return (
    <div aria-label="Diagnostic categories">
      <p>
        Measurements reflect the collection time. Unavailable readings are shown
        explicitly.
      </p>
      {categories.map(([title, data]) => (
        <details key={title} open={title === "Overview"}>
          <summary>{title}</summary>
          <pre>
            {typeof data === "string"
              ? data
              : JSON.stringify(data ?? "Unavailable", null, 2)}
          </pre>
        </details>
      ))}
      {!!original.files && (
        <details>
          <summary>Export Diagnostics — complete preview</summary>
          {Object.entries(files).map(([name, data]) => (
            <section key={name}>
              <h3>{name}</h3>
              <pre>{String(data)}</pre>
            </section>
          ))}
        </details>
      )}
    </div>
  );
}
