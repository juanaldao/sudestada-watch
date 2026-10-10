import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { setSnapshot } from "./shim.js";
import Forecast from "../../dives/sudestada-forecast/sudestada-forecast.tsx";
import History from "../../dives/sudestada-history/sudestada-history.tsx";

const PAGES = { forecast: { label: "Forecast", Page: Forecast }, history: { label: "History", Page: History } };
const fromHash = () => (location.hash.slice(1) in PAGES ? location.hash.slice(1) : "forecast");

function App() {
  const [page, setPage] = useState(fromHash);
  useEffect(() => {
    const on = () => setPage(fromHash());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  const { Page } = PAGES[page];
  return (
    <>
      <nav>
        {Object.entries(PAGES).map(([key, p]) => (
          <a key={key} href={"#" + key} aria-current={key === page ? "page" : undefined}>{p.label}</a>
        ))}
      </nav>
      <Page />
      <footer>
        Data: <a href="https://www.ina.gob.ar/">INA</a>, <a href="https://www.hidro.gov.ar/">SHN</a>,{" "}
        <a href="https://open-meteo.com/">Open-Meteo</a>. Unofficial; for official warnings see SHN.{" "}
        <a href="https://github.com/juanaldao/sudestada-watch">Source</a>
      </footer>
    </>
  );
}

const root = createRoot(document.getElementById("root"));
// no-cache = revalidate: Pages serves max-age=600, but the snapshot changes hourly.
fetch("data.json", { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
  .then((snap) => { setSnapshot(snap.queries); root.render(<App />); })
  .catch((e) => { document.getElementById("root").textContent = "Could not load data: " + e.message; });
