// Bundles the Dive .tsx files into site/dist/app.js for GitHub Pages. The only change from
// how MotherDuck runs them: @motherduck/react-sql-query resolves to src/shim.js, which serves
// the rows export_data.py snapshotted.
import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

mkdirSync("dist", { recursive: true });
copyFileSync("index.html", "dist/index.html");

await build({
  entryPoints: ["src/main.jsx"],
  outfile: "dist/app.js",
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2020",
  jsx: "automatic",
  alias: { "@motherduck/react-sql-query": "./src/shim.js" },
  // The Dives live outside site/, so point module resolution back at site/node_modules.
  nodePaths: [resolve("node_modules")],
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "info",
});
