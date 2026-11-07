import { useEffect, useRef, useState, type MouseEvent } from "react";
import "./Landing.css";

export function Brand() {
  return (
    <span className="brand">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <path d="M2 17h6l3-10 5 20 5-17 3 7h6" />
      </svg>
      Sei<span>MLAI</span>
    </span>
  );
}

const repository = "https://github.com/INGV/seimlai";
const logo = "/assets/homepage/logo.webp";
const imageRoot = "/assets/homepage";

// Source inventory: 300 + 300 + 120 + 10 frames, all 1920×1080.
// Keep every part4 frame so the catalog reveal completes before the final hold.
const animation = {
  parts: [{ folder: "part1", start: 1, end: 300, skip: 2 }, { folder: "part2", start: 1, end: 300, skip: 2 }, { folder: "part3", start: 1, end: 120, skip: 2 }, { folder: "part4", start: 1, end: 10, skip: 1 }],
  mobileFrameSkip: 2,
  cacheSize: 12,
  hold: 0.12,
};
const frames = animation.parts.flatMap(({ folder, start, end, skip }) =>
  Array.from(new Set([...Array.from({ length: Math.ceil((end - start + 1) / skip) }, (_, i) => start + i * skip), end]))
    .map(n => `${imageRoot}/${folder}/${String(n).padStart(3, "0")}.webp`),
);
const stages = [
  { title: "Download data", description: "Acquire continuous seismic waveforms and station metadata for the selected region, time period, networks, and stations.", input: "Geographic bounds, dates, and station selection.", operation: "Retrieve waveform data and station information.", output: "The waveform archive and station metadata needed for processing.", tags: ["Waveform acquisition"], command: "download", range: [0, 120], theme: "light" },
  { title: "Pick seismic phases", description: "Identify P- and S-wave arrivals using the configured deep-learning model available through SeisBench.", input: "Waveform data.", operation: "Identify seismic phase arrivals using the selected model and thresholds.", output: "P- and S-wave picks.", tags: ["SeisBench", "PhaseNet / EQTransformer, depending on configuration"], command: "phase-picking", range: [120, 201], theme: "light" },
  { title: "Associate phases", description: "Associate seismic arrivals into earthquake events and build an initial catalog with GaMMA.", input: "Phase picks and station information.", operation: "Group arrivals into candidate earthquake events.", output: "The raw associated catalog.", tags: ["GaMMA"], command: "association", range: [201, 261], theme: "light" },
  { title: "Locate earthquakes", description: "Prepare the location inputs, run HypoEllipse, and filter the resulting absolute earthquake locations.", input: "Associated events and configured location inputs.", operation: "Calculate absolute locations and apply the configured filtering.", output: "The filtered absolute-location catalog.", tags: ["HypoEllipse", "Docker"], command: "absolute-location", range: [261, 301], theme: "dark" },
  { title: "Refine relative locations", description: "Prepare HypoDD inputs, generate cross-correlation differential times, and perform double-difference relative relocation.", input: "Prepared event and phase information, with waveforms used for cross-correlation.", operation: "Generate differential-time inputs and run the HypoDD relocation procedure.", output: "The final relatively relocated catalog.", tags: ["Cross-correlation", "HypoDD", "Docker"], command: "relative-relocation", range: [302, frames.length - 1], theme: "dark" },
];
const technologies = [
  ["Python", "Workflow orchestration, command-line execution, and reusable processing modules.", "/assets/technology-logos/python-icon.svg"],
  ["SeisBench", "Deep-learning models for seismic phase picking.", "/assets/technology-logos/seisbench-icon.svg"],
  ["GaMMA", "Phase association and initial catalog generation."],
  ["HypoEllipse", "Absolute earthquake location."],
  ["HypoDD", "Double-difference relative relocation.", "/assets/technology-logos/hypodd-banner.png"],
  ["PyGMT", "Scientific mapping and catalog visualization.", "/assets/technology-logos/pygmt-logo.svg"],
  ["Docker", "Containerized execution of the location procedures.", "/assets/technology-logos/docker-icon.svg"],
  ["Conda", "Management of the scientific software environment.", "/assets/technology-logos/conda-icon.svg"],
];
const authors = [
  ["Rossella Fonzetti", "Corresponding author", "rossella.fonzetti@ingv.it", "Scientific collaborations", "/assets/authors/rossella-fonzetti.jpeg"],
  ["Alessandro Crocetta", "Co-author", "alessandro.crocetta@ingv.it", "Questions and bug reports", "/assets/authors/alessandroCrocetta.png"],
  ["Daniele Bailo", "Co-author", "daniele.bailo@ingv.it", "Contact", "/assets/authors/daniele-bailo.jpeg"],
];
const number = (i: number) => String(i + 1).padStart(2, "0");

function Workflow() {
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [active, setActive] = useState(0);
  const [complete, setComplete] = useState(false);
  useEffect(() => {
    const parent = root.current!;
    const node = canvas.current!;
    const ctx = node.getContext("2d");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const mobile = matchMedia("(max-width: 800px)");
    const cache = new Map<number, ImageBitmap>();
    const failed = new Set<number>();
    const articles = Array.from(parent.querySelectorAll<HTMLElement>(".home-step"));
    let desired = 0, displayed = -1, raf = 0, disposed = false, loading = false;
    let request: AbortController | undefined;
    function paint(index: number) {
      const bitmap = cache.get(index);
      if (!bitmap || !ctx) return;
      ctx.drawImage(bitmap, 0, 0, node.width, node.height);
      displayed = index;
      node.style.opacity = "1";
    }
    async function loadNearby() {
      if (loading || disposed || reduced.matches || !ctx) return;
      const candidates = [desired, desired + 1, desired - 1, desired + 2, desired - 2];
      const index = candidates.find(i => i >= 0 && i < frames.length && !cache.has(i) && !failed.has(i));
      if (index === undefined) return;
      loading = true;
      request = new AbortController();
      try {
        const response = await fetch(mobile.matches ? frames[index].replace(imageRoot, `${imageRoot}/mobile`) : frames[index], { signal: request.signal });
        if (!response.ok) throw new Error(`Frame ${response.status}`);
        const bitmap = await createImageBitmap(await response.blob());
        if (disposed || reduced.matches) { bitmap.close(); return; }
        cache.set(index, bitmap);
        if (index === desired || displayed < 0) paint(index);
        while (cache.size > animation.cacheSize) {
          const victim = [...cache.keys()].filter(i => i !== desired && i !== displayed)
            .sort((a, b) => Math.abs(b - desired) - Math.abs(a - desired))[0];
          cache.get(victim)!.close();
          cache.delete(victim);
        }
      } catch (error) {
        // Retain the last valid canvas or static image when an asset cannot load.
        if (!(error instanceof DOMException && error.name === "AbortError")) failed.add(index);
      } finally {
        loading = false;
        if (!disposed) void loadNearby();
      }
    }
    function update() {
      raf = 0;
      const anchor = innerHeight * 0.4;
      let index = 0;
      articles.forEach((article, i) => { if (article.getBoundingClientRect().top <= anchor) index = i; });
      const bounds = articles[index].getBoundingClientRect();
      const progress = Math.max(0, Math.min(1, (anchor - bounds.top) / bounds.height));
      const [start, end] = stages[index].range;
      desired = Math.round(start + (end - start) * Math.min(1, progress / (1 - animation.hold)));
      if (mobile.matches && desired < frames.length - animation.parts[3].end) {
        desired -= desired % animation.mobileFrameSkip;
      }
      setActive(index);
      setComplete(index === stages.length - 1 && progress >= 1 - animation.hold);
      if (reduced.matches) {
        node.style.opacity = "0";
        request?.abort();
        cache.forEach(bitmap => bitmap.close());
        cache.clear();
        displayed = -1;
        return;
      }
      if (parent.getBoundingClientRect().bottom < 0 || parent.getBoundingClientRect().top > innerHeight) return;
      paint(desired);
      void loadNearby();
    }
    function schedule() { if (!raf) raf = requestAnimationFrame(update); }
    addEventListener("scroll", schedule, { passive: true });
    addEventListener("resize", schedule);
    reduced.addEventListener("change", schedule);
    mobile.addEventListener("change", schedule);
    schedule();
    return () => {
      disposed = true;
      request?.abort();
      cancelAnimationFrame(raf);
      cache.forEach(bitmap => bitmap.close());
      removeEventListener("scroll", schedule);
      removeEventListener("resize", schedule);
      reduced.removeEventListener("change", schedule);
      mobile.removeEventListener("change", schedule);
    };
  }, []);
  return <div className="home-workflow" ref={root} data-theme={stages[active].theme}>
    <div className="home-workflow-controls" data-theme={stages[active].theme}>
      <nav className="home-step-nav" aria-label="Workflow stages">
        {stages.map((stage, i) => <a key={stage.command} href={`#step-${i + 1}`} aria-label={`${number(i)} — ${stage.title}`} aria-current={i === active ? "step" : undefined}>{number(i)}</a>)}
      </nav>
      <p className="home-caption">Illustrative sequence · not scientific observations.<br />Explore actual catalog data in the workspace’s Cesium map.</p>
    </div>
    <div className="home-visual-column">
      <div className="home-visual" data-theme={stages[active].theme}>
        <div className="home-visual-label"><span>FROM SIGNAL TO STRUCTURE</span><span>{number(active)} / 05</span></div>
        <div className="home-sequence">
          <img src={complete ? `${imageRoot}/catalog.webp` : `${imageRoot}/step-${active + 1}.webp`} alt="Illustrative seismic terrain progressing from waveforms to an earthquake catalog" width="768" height="432" />
          <canvas ref={canvas} width="1280" height="720" aria-hidden="true" />
        </div>

      </div>
    </div>
    <div className="home-steps" id="workflow-content">
      {stages.map((stage, i) => <article className="home-step" id={`step-${i + 1}`} key={stage.command} data-theme={stage.theme}>
        <span className="home-kicker">{number(i)} / WORKFLOW</span>
        <h3>{stage.title}</h3><p className="home-step-description">{stage.description}</p>
        <dl>{[["Input", stage.input], ["Operation", stage.operation], ["Output", stage.output]].map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}</dl>
        <div className="home-tags">{stage.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
        <code className="home-command">python main.py {stage.command}</code>
      </article>)}
      <div className="home-catalog" data-theme="dark">
        <span className="home-kicker">THE RESULT</span>
        <h3>Your earthquake catalog.</h3>
        <p>From continuous waveforms to the final relatively relocated catalog. Explore the resulting earthquake locations in the operational workspace.</p>
        <a className="home-button" href="/app">Explore your catalog ↗</a>
      </div>
    </div>
  </div>;
}

export function Landing({ onEnter }: { onEnter: () => void }) {
  function enter(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onEnter(); }
  }
  return <div className="seimlai-home">
    <a className="home-skip" href="#workflow-content">Skip to workflow content</a>
    <header className="home-nav">
      <a href="#overview" aria-label="SeiMLAI overview"><img src={logo} alt="SeiMLAI" width="132" height="48" /></a>
      <nav aria-label="Main navigation">{[["overview", "Overview"], ["workflow", "Workflow"], ["technologies", "Technologies"], ["team", "Team"], ["get-started", "Get started"]].map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}</nav>
      <a className="home-button home-nav-action" href="/app" onClick={enter}>Open workspace <span aria-hidden="true">↗</span></a>
    </header>
    <main>
      <section className="home-overview home-wrap" id="overview">
        <div className="home-hero-copy"><h1><img className="home-hero-logo" src={logo} alt="SeiMLAI" width="1746" height="901" fetchPriority="high" /></h1>
          <p className="home-headline">From continuous waveforms to high-resolution earthquake catalogs.</p>
          <p className="home-intro">A modular Python workflow that connects seismic data acquisition, machine-learning phase picking, event association, earthquake location, and relative relocation.</p>
          <div className="home-actions"><a className="home-button" href="/app" onClick={enter}>Open workspace ↗</a><a className="home-text-link" href="#workflow">Explore the workflow ↓</a></div>
          <a className="home-repository" href={repository}>View on GitHub ↗</a>
        </div>
        <div className="home-overview-footer"><span>SEIsmic catalog for Machine Learning And Imaging</span><span>Developed at INGV · Rome, Italy</span></div>
      </section>
      <section className="home-workflow-section" id="workflow">
        <div className="home-wrap"><div className="home-section-heading"><span className="home-kicker">THE WORKFLOW</span><h2>Five stages.<br /><span>One connected catalog.</span></h2><p>Follow the path from waveform acquisition to relative relocation. Run it end to end, or select the stages your study needs.</p></div></div>
        <Workflow />
        <p className="home-supporting home-wrap">Pre-processing, quality control, plotting, and diagnostics support the workflow. They are not additional numbered stages. Phase picking supports pretrained or custom models through the project configuration.</p>
      </section>
      <section className="home-technologies" id="technologies"><div className="home-wrap">
        <div className="home-section-heading"><span className="home-kicker">TECHNOLOGIES & REQUIREMENTS</span><h2>Built on established<br />scientific tools.</h2><p>Specialist methods, connected through a modular Python workflow.</p></div>
        <div className="home-tools">{technologies.map(([name, text, image]) => <article key={name}>{image ? <img className="home-tool-logo" src={image} alt={`${name} logo`} /> : <div className="home-tool-logo" aria-hidden="true">{name.slice(0, 2)}</div>}<h3>{name}</h3><p>{text}</p></article>)}</div>
        <div className="home-requirements"><div><span className="home-kicker">SCIENTIFIC WORKFLOW</span><h3>What is required to run SeiMLAI?</h3><ul><li>The Python environment defined in <code>environment.yml</code>.</li><li>The Conda environment named <code>catalog</code>.</li><li>Project settings in <code>user_configuration/config.yaml</code>.</li><li>Docker for the containerized location stages.</li><li>Access to configured data services when downloading waveforms.</li></ul><p>Use the repository’s environment and dependency files for exact versions. GPU acceleration for phase picking and HPC execution are optional; a GPU is not a universal requirement.</p></div>
          <div><span className="home-kicker">INDEPENDENT WEB INTERFACE</span><h3>A workspace in your browser.</h3><p>The React/Vite frontend connects to FastAPI over HTTP and WebSocket, with Cesium for 3D catalog exploration.</p><ul><li>Node.js 22.12+ or 24 for frontend installation, builds, and development.</li><li>FastAPI and Uvicorn provide the Python web server.</li><li>FastAPI serves the built frontend. Node.js is not needed simply to serve it.</li></ul><details><summary>Web interface setup</summary><pre><code>{"python -m pip install 'fastapi>=0.115,<1' 'uvicorn[standard]>=0.30,<1'\ncd frontend\nnpm ci\nnpm run build\ncd ..\npython -m seimlai.web.app"}</code></pre><a className="home-text-link" href={`${repository}#independent-web-interface-react--fastapi`}>Read the web interface documentation ↗</a></details></div></div>
        <h3 className="home-interface-title">Choose how you work.</h3><div className="home-interfaces">{[["Command line", "Run the full pipeline, select individual stages, or continue an existing workflow."], ["Python modules", "Reuse processing stages in scripts, notebooks, and custom applications."], ["NiceGUI", "Use the original graphical interface launched with python main.py --gui."], ["Independent web interface", "Use the React/Vite frontend with the FastAPI backend and the Cesium map in the operational workspace."]].map(([name, text]) => <article key={name}><h4>{name}</h4><p>{text}</p></article>)}</div>
      </div></section>
      <section className="home-wrap home-team" id="team"><div className="home-section-heading"><span className="home-kicker">THE TEAM</span><h2>The people behind SeiMLAI.</h2></div><div className="home-authors">{authors.map(([name, role, email, purpose, image]) => <article key={email}><img className="home-author-photo" src={image} alt={`${name} portrait`} /><span className="home-kicker">{role}</span><h3>{name}</h3><p>Istituto Nazionale di Geofisica e Vulcanologia (INGV), Rome, Italy</p><div><span>{purpose}</span><a href={`mailto:${email}`}>{email} ↗</a></div></article>)}</div></section>
      <section className="home-start" id="get-started"><div className="home-wrap home-start-grid"><div><span className="home-kicker">GET STARTED</span><h2>Run your first workflow.</h2><p>Create the scientific environment, choose your configuration, and launch the pipeline.</p><div className="home-actions"><a className="home-button" href="/app" onClick={enter}>Open workspace ↗</a><a className="home-text-link" href={`${repository}#installation--quickstart`}>Installation documentation ↗</a></div></div><div><pre><code>{"conda env update -f environment.yml\nconda activate catalog\npython main.py --help\npython main.py --config user_configuration/config.yaml"}</code></pre><p>Run the complete workflow or select individual processing stages.</p><a className="home-text-link" href={repository}>SeiMLAI repository ↗</a></div></div></section>
    </main>
    <footer className="home-wrap home-footer"><img src={logo} alt="SeiMLAI" width="132" height="48" /><p>Licensed under the <a href={`${repository}/blob/HEAD/LICENSE`}>GNU Affero General Public License v3.0</a>.<br />Third-party software, data services, waveform data, station metadata, and external images retain their respective licenses and terms.</p><a href="#overview">Back to top ↑</a></footer>
  </div>;
}
