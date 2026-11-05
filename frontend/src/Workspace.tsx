import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  api,
  type Case,
  type ConfigEnvelope,
  type Configuration,
  type LiveState,
  type Value,
} from "./api";
import { Brand } from "./Landing";

const SeismicMap = lazy(() => import("./SeismicMap"));
const tabs = [
  ["runner", "▷", "Pipeline runner"],
  ["cases", "▱", "Case studies"],
  ["config", "⚙", "Configuration"],
  ["map", "◎", "Live map"],
  ["logs", "≡", "Full logs"],
] as const;
type Tab = (typeof tabs)[number][0];
const titles: Record<string, string> = {
  case_study: "Case study",
  geography: "Geographic bounds",
  dates: "Time window",
  stations: "Stations & providers",
  model: "Deep learning model",
  phase_picking: "Phase picking",
  gamma: "GaMMA association",
  hypoellipse: "HypoEllipse",
  hypoellipse_check: "HypoEllipse runtime",
  dd: "Location filtering",
  hypodd: "HypoDD",
  cc_dd: "Cross-correlation",
  analysis: "Analysis",
  plotting: "Plotting",
  threshold_analysis: "Threshold analysis",
};
const pretty = (value: string) => value.replaceAll("_", " ");

function Console({ logs, full = false }: { logs: string[]; full?: boolean }) {
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const output = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (follow && output.current)
      output.current.scrollTop = output.current.scrollHeight;
  }, [logs, follow]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([logs.join("\n")], { type: "text/plain" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "seimlai.log";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className={`console-panel ${full ? "full-console" : ""}`}>
      <div className="console-heading">
        <span>
          <i className="status-dot" /> LIVE CONSOLE
        </span>
        <button className="plain-button" onClick={download}>
          Download logs ↓
        </button>
      </div>
      <div className="console-tools">
        <input
          aria-label="Search logs"
          placeholder="Search output…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          <input
            type="checkbox"
            checked={follow}
            onChange={(e) => setFollow(e.target.checked)}
          />{" "}
          Follow
        </label>
      </div>
      <pre ref={output} tabIndex={0} aria-label="Pipeline output">
        {logs.length
          ? logs
              .filter((line) =>
                line.toLowerCase().includes(query.toLowerCase()),
              )
              .join("\n")
          : "Waiting for pipeline output…\n\nStart a workflow to follow execution here."}
      </pre>
      <div className="console-bottom">
        <span>{logs.length} lines retained</span>
        <span>PYTHON / WORKFLOW OUTPUT</span>
      </div>
    </section>
  );
}

function Field({
  name,
  value,
  onChange,
  onValidity,
}: {
  name: string;
  value: Value;
  onChange: (value: Value) => void;
  onValidity: (name: string, valid: boolean) => void;
}) {
  const complex = Array.isArray(value);
  const nullable = [
    "case_study.personal_folder",
    "model.custom_model_path",
    "cc_dd.worker_count",
    "cc_dd.chunk_size",
  ].includes(name);
  const numeric =
    typeof value === "number" ||
    ["cc_dd.worker_count", "cc_dd.chunk_size"].includes(name);
  const [text, setText] = useState(
    complex ? JSON.stringify(value) : value === null ? "" : String(value),
  );
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setText(
      complex ? JSON.stringify(value) : value === null ? "" : String(value),
    );
  }, [value, complex]);
  useEffect(() => () => onValidity(name, true), [name, onValidity]);
  const label = pretty(name.split(".").at(-1)!);
  if (typeof value === "boolean")
    return (
      <label className="field boolean-field">
        <span>{label}</span>
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
        />
      </label>
    );
  function edit(raw: string) {
    setText(raw);
    try {
      const parsed = complex
        ? JSON.parse(raw)
        : nullable && raw === ""
          ? null
          : numeric
            ? raw.trim() === ""
              ? NaN
              : Number(raw)
            : raw;
      if (
        (complex && !Array.isArray(parsed)) ||
        (typeof parsed === "number" && !Number.isFinite(parsed))
      )
        throw new Error();
      setInvalid(false);
      onValidity(name, true);
      onChange(parsed);
    } catch {
      setInvalid(true);
      onValidity(name, false);
    }
  }
  return (
    <label className={`field ${complex ? "wide-field" : ""}`}>
      <span>
        {label}
        {complex && <small> · list</small>}
      </span>
      <input
        aria-invalid={invalid}
        value={text}
        onChange={(e) => edit(e.target.value)}
        placeholder={value === null ? "Not set" : undefined}
      />
      {invalid && (
        <small className="field-error">
          {complex
            ? "Enter a valid list, for example [1, 2, 3]."
            : "Enter a valid number."}
        </small>
      )}
    </label>
  );
}

function ConfigFields({
  object,
  path,
  update,
  validity,
}: {
  object: Record<string, Value>;
  path: string[];
  update: (path: string[], value: Value) => void;
  validity: (name: string, valid: boolean) => void;
}) {
  return (
    <div className="form-grid">
      {Object.entries(object).map(([key, value]) =>
        value !== null && typeof value === "object" && !Array.isArray(value) ? (
          <fieldset key={key}>
            <legend>{pretty(key)}</legend>
            <ConfigFields
              object={value}
              path={[...path, key]}
              update={update}
              validity={validity}
            />
          </fieldset>
        ) : (
          <Field
            key={key}
            name={[...path, key].join(".")}
            value={value}
            onChange={(v) => update([...path, key], v)}
            onValidity={validity}
          />
        ),
      )}
    </div>
  );
}

function FileEditor({
  group,
  disabled,
  report,
  onDirty,
}: {
  group: string;
  disabled: boolean;
  report: (error: unknown) => void;
  onDirty: (group: string, dirty: boolean) => void;
}) {
  const [names, setNames] = useState<string[]>([]),
    [name, setName] = useState("");
  const [file, setFile] = useState({ content: "", version: "" });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = text !== file.content;
  useEffect(() => {
    onDirty(group, dirty);
    return () => onDirty(group, false);
  }, [group, dirty, onDirty]);
  useEffect(() => {
    let active = true;
    api<string[]>(`/files/${group}`)
      .then((result) => {
        if (active) {
          setNames(result);
          setName(result[0]);
        }
      })
      .catch(report);
    return () => {
      active = false;
    };
  }, [group, report]);
  useEffect(() => {
    if (!name) return;
    let active = true;
    setBusy(true);
    api<typeof file>(`/files/${group}/${encodeURIComponent(name)}`)
      .then((result) => {
        if (active) {
          setFile(result);
          setText(result.content);
          setSaved(false);
        }
      })
      .catch(report)
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [group, name, report]);
  async function save() {
    setBusy(true);
    try {
      const result = await api<typeof file>(
        `/files/${group}/${encodeURIComponent(name)}`,
        "PUT",
        { content: text, version: file.version },
      );
      setFile(result);
      setSaved(true);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  async function upload(upload: File) {
    if (dirty && !confirm("Discard unsaved file edits?")) return;
    setBusy(true);
    try {
      const current = await api<typeof file>(
        `/files/${group}/${encodeURIComponent(upload.name)}`,
      );
      const result = await api<typeof file>(
        `/files/${group}/${encodeURIComponent(upload.name)}`,
        "PUT",
        { content: await upload.text(), version: current.version },
      );
      setNames(await api<string[]>(`/files/${group}`));
      setName(upload.name);
      setFile(result);
      setText(result.content);
      setSaved(true);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty]);
  return (
    <section className="panel file-editor">
      <div className="panel-heading">
        <h3>
          {group === "hypoellipse"
            ? "Stage 04 · HypoEllipse files"
            : "Stage 05 · HypoDD files"}
        </h3>
        <span>
          {saved
            ? "Saved"
            : dirty
              ? "Unsaved edits"
              : "Model & runtime templates"}
        </span>
      </div>
      <div className="toolbar">
        <select
          aria-label={`${group} file`}
          value={name}
          disabled={busy}
          onChange={(e) => {
            if (!dirty || confirm("Discard unsaved file edits?"))
              setName(e.target.value);
          }}
        >
          {names.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
        <button disabled={disabled || busy || !dirty} onClick={save}>
          Save file
        </button>
        <label className="upload-button">
          Upload / replace
          <input
            type="file"
            disabled={disabled || busy}
            onChange={(e) => {
              if (e.target.files?.[0]) void upload(e.target.files[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>
      <textarea
        aria-label={`${group} file contents`}
        spellCheck={false}
        value={text}
        disabled={disabled || busy}
        onChange={(e) => {
          setText(e.target.value);
          setSaved(false);
        }}
      />
    </section>
  );
}

export default function Workspace({ onHome }: { onHome: () => void }) {
  const [tab, setTab] = useState<Tab>("runner");
  const [state, setState] = useState<LiveState | null>(null),
    [connected, setConnected] = useState(false);
  const [config, setConfig] = useState<ConfigEnvelope | null>(null),
    [draft, setDraft] = useState<Configuration | null>(null);
  const [cases, setCases] = useState<Case[]>([]),
    [section, setSection] = useState("case_study");
  const [step, setStep] = useState("01"),
    [utility, setUtility] = useState("plot-catalog");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [dark, setDark] = useState(
    () => localStorage.getItem("seimlai-theme") === "dark",
  );
  const invalid = useRef(new Set<string>());
  const [hasInvalid, setHasInvalid] = useState(false);
  const dirtyFiles = useRef(new Set<string>());
  const fileDirty = useRef((group: string, dirty: boolean) => {
    if (dirty) dirtyFiles.current.add(group);
    else dirtyFiles.current.delete(group);
  }).current;
  const [mapVisited, setMapVisited] = useState(false);
  function changeTab(next: Tab) {
    if (next === tab) return;
    if (
      (dirtyFiles.current.size > 0 || hasInvalid) &&
      !confirm(
        "Discard unsaved file edits or invalid field values before changing views?",
      )
    )
      return;
    if (next === "map") setMapVisited(true);
    setTab(next);
  }
  function changeSection(next: string) {
    if (next === section) return;
    if (
      (dirtyFiles.current.size > 0 || hasInvalid) &&
      !confirm(
        "Discard unsaved file edits or invalid field values before changing sections?",
      )
    )
      return;
    setSection(next);
  }
  const report = useRef((problem: unknown) =>
    setError(problem instanceof Error ? problem.message : String(problem)),
  ).current;
  const validity = useRef((name: string, valid: boolean) => {
    if (valid) invalid.current.delete(name);
    else invalid.current.add(name);
    setHasInvalid(invalid.current.size > 0);
  }).current;
  const dirty =
    !!config && JSON.stringify(config.data) !== JSON.stringify(draft);
  const running = state?.running ?? false;
  const blocked = busy || running || !connected || !config;
  async function loadConfig() {
    const result = await api<ConfigEnvelope>("/config");
    setConfig(result);
    setDraft(structuredClone(result.data));
    invalid.current.clear();
    setHasInvalid(false);
  }
  useEffect(() => {
    void loadConfig().catch(report);
  }, [report]);
  useEffect(() => {
    let socket: WebSocket | null = null,
      timer: ReturnType<typeof setTimeout>,
      disposed = false;
    function connect() {
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/live`,
      );
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => setState(JSON.parse(event.data));
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setConnected(false);
        if (!disposed) timer = setTimeout(connect, 2000);
      };
    }
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);
  useEffect(() => {
    if (tab === "cases") api<Case[]>("/cases").then(setCases).catch(report);
  }, [tab, config, report]);
  useEffect(() => {
    localStorage.setItem("seimlai-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    if (!dirty && !hasInvalid) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty, hasInvalid]);
  async function action(work: () => Promise<unknown>, message?: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
      if (message) setNotice(message);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  function update(path: string[], value: Value) {
    setDraft((previous) => {
      const next = structuredClone(previous!);
      let target: Record<string, Value> = next;
      for (const key of path.slice(0, -1))
        target = target[key] as Record<string, Value>;
      target[path.at(-1)!] = value;
      return next;
    });
  }
  function run(mode: string) {
    if (dirty || hasInvalid || dirtyFiles.current.size > 0) {
      setError("Save or discard configuration changes before starting a job.");
      return;
    }
    void action(async () => {
      await api("/pipeline/run", "POST", { mode, step, command: utility, version: config!.version });
      setState(await api<LiveState>("/state"));
    });
  }
  function leave() {
    if (
      (!dirty && !hasInvalid && dirtyFiles.current.size === 0) ||
      confirm("Leave the workspace and discard unsaved configuration changes?")
    )
      onHome();
  }
  const changedElsewhere =
    config && state && config.version !== state.config_version;
  return (
    <div className={`workspace ${dark ? "dark" : ""}`}>
      <header className="app-header">
        <div className="app-brand-row">
          <button
            className="brand-button"
            onClick={leave}
            aria-label="Return to home"
          >
            <Brand />
          </button>
          <span className="app-subtitle">
            High-resolution seismic catalog workflow
          </span>
          <div className="header-right">
            <span className={`connection ${connected ? "online" : ""}`}>
              <i />
              {connected ? "Connected" : "Reconnecting…"}
            </span>
            <label className="theme-toggle">
              <input
                type="checkbox"
                checked={dark}
                onChange={(e) => setDark(e.target.checked)}
              />{" "}
              Dark mode
            </label>
          </div>
        </div>
        <nav className="app-tabs" aria-label="Workspace">
          {tabs.map(([id, icon, label]) => (
            <button
              key={id}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => changeTab(id)}
            >
              <span>{icon}</span>
              {label}
              {id === "config" && (dirty || hasInvalid) && (
                <i className="dirty-dot" />
              )}
            </button>
          ))}
        </nav>
      </header>
      <main className={`app-main ${tab === "map" ? "map-main" : ""}`}>
        {error && (
          <div className="message error" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
        {notice && (
          <div className="message success" role="status">
            {notice}
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              ×
            </button>
          </div>
        )}
        {changedElsewhere && (
          <div className="message warning">
            Settings changed in another session. Reload to use the saved
            configuration.
            <button
              onClick={() => {
                if (
                  (!dirty && !hasInvalid) ||
                  confirm("Discard your local edits and reload saved settings?")
                )
                  void action(loadConfig);
              }}
            >
              Reload settings
            </button>
          </div>
        )}
        {!config && (
          <div className="panel loading-panel">
            <h2>Connecting to the workspace</h2>
            <p>The Python API must be running on port 8000.</p>
            <button onClick={() => void action(loadConfig)}>
              Retry connection
            </button>
          </div>
        )}
        {tab === "runner" && (
          <>
            <section className="panel runner-controls">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">PROCESSING WORKSPACE</span>
                  <h1>Pipeline runner</h1>
                  <p>
                    {running
                      ? `Processing ${state?.current_step ? `stage ${state.current_step}` : "utility"}…`
                      : "Ready to run stages 01–05"}
                  </p>
                </div>
                <div className="toolbar">
                  {running ? (
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() =>
                        void action(
                          () => api("/pipeline/stop", "POST"),
                          "Stop requested.",
                        )
                      }
                    >
                      ■ Stop
                    </button>
                  ) : (
                    <>
                      <button
                        className="primary"
                        disabled={blocked}
                        onClick={() => run("all")}
                      >
                        ▷ Run full workflow
                      </button>
                      <button
                        disabled={blocked}
                        onClick={() => run("continue")}
                      >
                        Continue (04–05)
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="runner-toolbar">
                <div className="toolbar">
                  <label htmlFor="step">Step</label>
                  <select
                    id="step"
                    value={step}
                    onChange={(e) => setStep(e.target.value)}
                  >
                    {(state?.steps ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id} · {s.description}
                      </option>
                    ))}
                  </select>
                  <button disabled={blocked} onClick={() => run("single")}>
                    Run selected
                  </button>
                  <button disabled={blocked} onClick={() => run("from")}>
                    Run from here →
                  </button>
                </div>
                <div className="toolbar">
                  <select
                    aria-label="Utility"
                    value={utility}
                    onChange={(e) => setUtility(e.target.value)}
                  >
                    {Object.entries({
                      "plot-catalog": "Plot catalog",
                      "gamma-analysis": "GaMMA analysis",
                      "plot-hypoellipse": "Plot HypoEllipse",
                      "threshold-analysis": "Threshold analysis",
                    }).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <button disabled={blocked} onClick={() => run("utility")}>
                    Execute utility
                  </button>
                </div>
              </div>
            </section>
            <div className="runner-grid">
              <section>
                <div className="section-label">
                  PIPELINE STAGES <span>01 — 05</span>
                </div>
                <div className="info-banner">
                  Stages 04 & 05 require velocity models and runtime templates.
                  <button
                    onClick={() => {
                      setTab("config");
                      setSection("files");
                    }}
                  >
                    Edit files ↗
                  </button>
                </div>
                <div className="stages">
                  {state?.steps.map((s) => (
                    <article className={`stage-card ${s.status}`} key={s.id}>
                      <div className="stage-index">{s.id}</div>
                      <div className="stage-info">
                        <div>
                          <h3>{s.description}</h3>
                          <span className="status-label">{s.status}</span>
                        </div>
                        <progress
                          max="1"
                          value={s.progress}
                          aria-label={`Stage ${s.id} progress`}
                        />
                        <div className="stage-meta">
                          <span>{Math.round(s.progress * 100)}%</span>
                          <span>{s.elapsed.toFixed(1)} s</span>
                        </div>
                        {s.error_message && (
                          <p className="field-error">{s.error_message}</p>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
              <Console logs={state?.logs ?? []} />
            </div>
          </>
        )}
        {tab === "cases" && (
          <>
            <div className="page-heading">
              <div>
                <span className="eyebrow">RESEARCH WORKSPACES</span>
                <h1>Case studies</h1>
                <p>
                  Folders in case_studies and the currently configured folder.
                </p>
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => setCases(await api<Case[]>("/cases")))
                }
              >
                Refresh ↻
              </button>
            </div>
            <div className="case-list">
              {cases.map((item) => (
                <article className="panel case-card" key={item.path}>
                  <span className="case-icon">▱</span>
                  <div>
                    <h3>{item.name}</h3>
                    <p>{item.path}</p>
                    {!item.exists && (
                      <span className="field-error">
                        Folder not found · created when processing starts
                      </span>
                    )}
                  </div>
                  {item.active ? (
                    <span className="pill">Active</span>
                  ) : (
                    <button
                      disabled={blocked || dirty || hasInvalid || !item.exists}
                      onClick={() =>
                        void action(async () => {
                          const result = await api<ConfigEnvelope>(
                            "/cases/select",
                            "POST",
                            { path: item.path, version: config!.version },
                          );
                          setConfig(result);
                          setDraft(structuredClone(result.data));
                        }, `Loaded ${item.name}`)
                      }
                    >
                      Load case study →
                    </button>
                  )}
                </article>
              ))}
            </div>
            {(dirty || hasInvalid) && (
              <p className="muted">
                Save or discard configuration edits before switching studies.
              </p>
            )}
          </>
        )}
        {tab === "config" && config && draft && (
          <>
            <div className="page-heading">
              <div>
                <span className="eyebrow">STUDY PARAMETERS</span>
                <h1>Configuration</h1>
                <p>
                  {dirty || hasInvalid
                    ? "You have unsaved changes."
                    : "All settings match the saved configuration."}
                </p>
              </div>
              <div className="toolbar">
                <button
                  disabled={busy || running}
                  onClick={() => {
                    setDraft(structuredClone(config.data));
                    invalid.current.clear();
                    setHasInvalid(false);
                    setNotice("Local configuration edits discarded.");
                  }}
                >
                  Discard changes
                </button>
                <button
                  className="primary"
                  disabled={blocked || hasInvalid || !dirty}
                  onClick={() =>
                    void action(async () => {
                      const result = await api<ConfigEnvelope>(
                        "/config",
                        "PUT",
                        { data: draft, version: config.version },
                      );
                      setConfig(result);
                      setDraft(structuredClone(result.data));
                    }, "Configuration saved.")
                  }
                >
                  Save configuration
                </button>
              </div>
            </div>
            <div className="configuration-layout">
              <aside className="config-nav" aria-label="Configuration sections">
                {Object.keys(draft).map((key) => (
                  <button
                    className={section === key ? "active" : ""}
                    key={key}
                    onClick={() => changeSection(key)}
                  >
                    {titles[key] ?? pretty(key)}
                  </button>
                ))}
                <button
                  className={section === "files" ? "active" : ""}
                  onClick={() => changeSection("files")}
                >
                  Model & runtime files
                </button>
              </aside>
              <div className="config-content">
                {section === "files" ? (
                  <>
                    <FileEditor
                      group="hypoellipse"
                      disabled={blocked}
                      report={report}
                      onDirty={fileDirty}
                    />
                    <FileEditor
                      group="hypodd"
                      disabled={blocked}
                      report={report}
                      onDirty={fileDirty}
                    />
                  </>
                ) : (
                  <section className="panel">
                    <div className="panel-heading">
                      <h2>{titles[section] ?? pretty(section)}</h2>
                      <span>Saved with YAML comments preserved</span>
                    </div>
                    <fieldset disabled={blocked} className="config-fieldset">
                      <ConfigFields
                        key={`${config.version}-${section}`}
                        object={draft[section]}
                        path={[section]}
                        update={update}
                        validity={validity}
                      />
                    </fieldset>
                    {section === "geography" && (
                      <Suspense
                        fallback={
                          <div className="loading-panel">
                            Loading geographic preview…
                          </div>
                        }
                      >
                        <SeismicMap
                          geography={draft.geography}
                          preview
                          onBounds={(bounds) => {
                            for (const [key, value] of Object.entries(bounds))
                              update(["geography", key], value);
                          }}
                        />
                      </Suspense>
                    )}
                  </section>
                )}
              </div>
            </div>
          </>
        )}
        {mapVisited && config && (
          <div hidden={tab !== "map"}>
            <Suspense
              fallback={<div className="loading-screen">Loading 3D map…</div>}
            >
              <SeismicMap
                geography={config.data.geography}
                revision={state?.catalog_revision}
              />
            </Suspense>
          </div>
        )}
        {tab === "logs" && (
          <>
            <div className="page-heading">
              <div>
                <span className="eyebrow">EXECUTION OUTPUT</span>
                <h1>Full logs</h1>
                <p>Search and follow live pipeline output.</p>
              </div>
            </div>
            <Console full logs={state?.logs ?? []} />
          </>
        )}
      </main>
      <footer className="app-footer">
        <span>SeiMLAI · Shared machine workspace</span>
        <span>{running ? "● Pipeline running" : "○ Pipeline idle"}</span>
      </footer>
    </div>
  );
}
