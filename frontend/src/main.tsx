import { lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Landing } from "./Landing";
import "./styles.css";

const Workspace = lazy(() => import("./Workspace"));

function App() {
  const [workspace, setWorkspace] = useState(
    location.pathname.startsWith("/app"),
  );
  useEffect(() => {
    const changed = () => setWorkspace(location.pathname.startsWith("/app"));
    addEventListener("popstate", changed);
    return () => removeEventListener("popstate", changed);
  }, []);
  function navigate(app: boolean) {
    history.pushState(null, "", app ? "/app" : "/");
    setWorkspace(app);
    scrollTo(0, 0);
  }
  return workspace ? (
    <Suspense
      fallback={<div className="loading-screen">Opening workspace…</div>}
    >
      <Workspace onHome={() => navigate(false)} />
    </Suspense>
  ) : (
    <Landing onEnter={() => navigate(true)} />
  );
}

createRoot(document.getElementById("root")!).render(<App />);
