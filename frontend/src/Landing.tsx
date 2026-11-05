import { useEffect, useRef } from "react";

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

function EarthSection() {
  const section = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const node = canvas.current!;
    const parent = section.current!;
    const context = node.getContext("2d");
    if (!context) return;
    let frame = 0;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    // Deterministic, illustrative seismicity. The live map never uses these points.
    const points = Array.from({ length: 130 }, (_, i) => ({
      x: Math.sin(i * 127.1) * 0.62,
      y: Math.cos(i * 311.7) * 0.28,
      z: 0.06 + ((i * 37) % 101) / 125,
      r: 1.2 + (i % 5) * 0.45,
    }));
    function draw() {
      frame = 0;
      const bounds = parent.getBoundingClientRect();
      const width = node.clientWidth,
        height = node.clientHeight;
      const ratio = Math.min(devicePixelRatio, 2);
      node.width = width * ratio;
      node.height = height * ratio;
      const ctx = context!;
      ctx.scale(ratio, ratio);
      const progress = reduced.matches
        ? 0.65
        : Math.max(0, Math.min(1, -bounds.top / (bounds.height - height)));
      parent.style.setProperty("--reveal", String(progress));
      const scale = Math.min(width * 0.67, height * 0.85);
      const cx = width * (width > 800 ? 0.63 : 0.5),
        cy = height * 0.48;
      const project = (x: number, y: number, z: number) => [
        cx + (x - y) * scale * 0.75,
        cy + (x + y) * scale * 0.26 + z * scale * 0.63,
      ];
      ctx.clearRect(0, 0, width, height);
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, scale);
      glow.addColorStop(0, "#154e6a38");
      glow.addColorStop(1, "#070b1200");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, width, height);
      for (let layer = 4; layer >= 0; layer--) {
        const z = layer * (0.045 + progress * 0.07);
        const corners = [
          [-0.7, -0.5],
          [0.7, -0.5],
          [0.7, 0.5],
          [-0.7, 0.5],
        ].map(([x, y]) => project(x, y, z));
        ctx.beginPath();
        corners.forEach(([x, y], i) =>
          i ? ctx.lineTo(x, y) : ctx.moveTo(x, y),
        );
        ctx.closePath();
        ctx.fillStyle =
          layer === 0 ? "#102d38" : `rgba(18,42,58,${0.3 - layer * 0.035})`;
        ctx.strokeStyle = layer === 0 ? "#5cafaab0" : "#3c647d55";
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
        if (layer === 0) {
          for (let line = 0; line <= 24; line++) {
            ctx.beginPath();
            for (let j = 0; j <= 50; j++) {
              const x = -0.7 + (j / 50) * 1.4,
                y = -0.5 + line / 24;
              const relief = Math.sin(x * 9 + y * 4) * Math.cos(y * 10) * 0.025;
              const [px, py] = project(x, y, relief);
              if (j === 0) ctx.moveTo(px, py);
              else ctx.lineTo(px, py);
            }
            ctx.strokeStyle = "#75c8b638";
            ctx.stroke();
          }
        }
      }
      points.forEach((p, i) => {
        const [x, y] = project(p.x, p.y, p.z * (0.08 + progress * 0.62));
        ctx.globalAlpha = 0.35 + progress * 0.65;
        ctx.fillStyle = ["#f2b46d", "#ec8571", "#ac9bff", "#6bd8c3"][i % 4];
        ctx.shadowColor = ctx.fillStyle;
        ctx.shadowBlur = 9;
        ctx.beginPath();
        ctx.arc(x, y, p.r, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;
      for (const [x, y] of [
        [-0.5, -0.2],
        [0.4, -0.3],
        [0.15, 0.35],
      ]) {
        const [px, py] = project(x, y, -0.025);
        ctx.fillStyle = "#b8ece2";
        ctx.beginPath();
        ctx.moveTo(px, py - 7);
        ctx.lineTo(px - 5, py + 3);
        ctx.lineTo(px + 5, py + 3);
        ctx.closePath();
        ctx.fill();
      }
    }
    function schedule() {
      if (!frame) frame = requestAnimationFrame(draw);
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(node);
    addEventListener("scroll", schedule, { passive: true });
    reduced.addEventListener("change", schedule);
    schedule();
    return () => {
      observer.disconnect();
      removeEventListener("scroll", schedule);
      reduced.removeEventListener("change", schedule);
      cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <div ref={section} className="earth-story" id="explore">
      <div className="earth-sticky">
        <canvas
          ref={canvas}
          aria-label="Illustrative Earth cross-section revealing earthquake hypocenters during scroll"
          role="img"
        />
        <div className="earth-caption">
          <span className="eyebrow">02 / A DIFFERENT PERSPECTIVE</span>
          <h2>
            Go beneath
            <br />
            the surface.
          </h2>
          <p>
            A map tells you where.
            <br />
            Depth reveals the structure.
          </p>
          <span className="technical">SURFACE → HYPOCENTERS → STRUCTURE</span>
        </div>
        <span className="illustration-label">
          CONCEPTUAL VISUALIZATION · NOT OBSERVATIONAL DATA
        </span>
        <span className="depth-label">
          Z / DEPTH
          <br />
          <b>↓</b>
        </span>
      </div>
    </div>
  );
}

export function Landing({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <a href="#" aria-label="SeiMLAI home">
          <Brand />
        </a>
        <nav aria-label="Overview">
          <a href="#workflow">Workflow</a>
          <a href="#explore">Explore in depth</a>
        </nav>
        <button className="button small" onClick={onEnter}>
          Open workspace <span>↗</span>
        </button>
      </header>
      <main>
        <section className="hero">
          <div className="hero-grid" aria-hidden="true" />
          <div className="hero-topline">
            <span className="eyebrow">
              <i className="status-dot" /> SEISMIC MACHINE LEARNING WORKFLOW
            </span>
            <span className="technical">SIGNAL / LOCATION / STRUCTURE</span>
          </div>
          <div className="hero-copy">
            <p className="overline">Listen deeper.</p>
            <h1>
              Every signal.
              <br />A deeper <em>story.</em>
            </h1>
            <p className="hero-description">
              From the first arrival to the final hypocenter.
              <br />
              One workspace for your seismic catalog.
            </p>
            <div className="hero-actions">
              <button className="button" onClick={onEnter}>
                Launch SeiMLAI <span>↗</span>
              </button>
              <a className="text-link" href="#workflow">
                Discover the workflow <span>↓</span>
              </a>
            </div>
          </div>
          <div className="signal-art" aria-hidden="true">
            <svg viewBox="0 0 1000 220" preserveAspectRatio="none">
              <defs>
                <linearGradient id="signal">
                  <stop stopColor="#65d9c2" stopOpacity="0" />
                  <stop offset=".4" stopColor="#65d9c2" />
                  <stop offset="1" stopColor="#65d9c2" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[0, 1, 2].map((row) => (
                <path
                  key={row}
                  transform={`translate(0 ${row * 25})`}
                  d={`M0 85 ${Array.from({ length: 500 }, (_, i) => {
                    const x = i * 2;
                    const envelope = Math.exp(-Math.pow((x - 580) / 120, 2));
                    return `L${x} ${85 + Math.sin(i * 2.1 + row) * Math.cos(i * 0.31) * envelope * 66}`;
                  }).join(" ")}`}
                />
              ))}
            </svg>
            <div className="signal-scale">
              <span>CONTINUOUS WAVEFORM</span>
              <span>TIME →</span>
            </div>
          </div>
          <div className="hero-footer">
            <span>BUILT FOR SEISMOLOGY</span>
            <span>SCROLL TO EXPLORE ↓</span>
            <span>SeiMLAI / RESEARCH WORKSPACE</span>
          </div>
        </section>
        <section className="workflow-section" id="workflow">
          <div className="section-heading">
            <span className="eyebrow">01 / FROM WAVEFORMS TO CATALOGS</span>
            <h2>
              Complex science.
              <br />
              <span>A connected workflow.</span>
            </h2>
            <p>
              Configure your study, follow each processing stage, and inspect
              the resulting seismicity in three dimensions.
            </p>
          </div>
          <div className="workflow-line">
            {[
              [
                "01",
                "Acquire",
                "Download waveforms and station metadata from FDSN services.",
              ],
              [
                "02",
                "Detect",
                "Identify phase arrivals with PhaseNet or EQTransformer.",
              ],
              [
                "03",
                "Associate",
                "Connect arrivals into earthquake events with GaMMA.",
              ],
              [
                "04",
                "Locate",
                "Estimate absolute hypocenters with HypoEllipse.",
              ],
              [
                "05",
                "Refine",
                "Resolve relative locations with cross-correlation and HypoDD.",
              ],
            ].map(([n, title, text]) => (
              <article key={n}>
                <span className="stage-number">{n}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>
        <EarthSection />
        <section className="closing">
          <span className="eyebrow">03 / YOUR NEXT CASE STUDY</span>
          <h2>
            Bring your data.
            <br />
            <em>Find the structure.</em>
          </h2>
          <p>
            Configuration, processing, live logs, and 3D exploration.
            <br />
            Your research, in one place.
          </p>
          <button className="button" onClick={onEnter}>
            Enter the workspace <span>↗</span>
          </button>
        </section>
      </main>
      <footer className="landing-footer">
        <Brand />
        <span>High-resolution seismic catalog workflow</span>
        <span>SEISMOLOGY × MACHINE LEARNING</span>
      </footer>
    </div>
  );
}
