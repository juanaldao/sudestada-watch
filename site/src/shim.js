// Stand-in for @motherduck/react-sql-query (aliased in build.mjs). Instead of querying
// MotherDuck, it returns the rows site/export_data.py snapshotted for the same SQL.

let store = {};

export function setSnapshot(queries) {
  store = queries || {};
}

// Must match site/export_data.py::norm exactly.
const norm = (sql) => sql.split(/\s+/).filter(Boolean).join(" ");

export function useSQLQuery(sql) {
  const rows = store[norm(sql)];
  if (rows === undefined) {
    console.warn("No snapshot for query (re-run export_data.py?):", norm(sql).slice(0, 120));
    return { data: undefined, isLoading: false, error: new Error("query not in snapshot") };
  }
  return { data: rows, isLoading: false, error: undefined };
}
