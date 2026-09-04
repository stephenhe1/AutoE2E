"""IndexedDB export snippet used to capture a browser-local state baseline.

VENDORED - do not edit here.

Copied verbatim from:
  repo    git@github.com:stephenhe1/UI-Graph-Explorer.git
  path    src/ui_graph/restoration.py  (the `_IDB_EXPORT_JS` constant, lines 51-153)
  commit  b07e8a846e8d9ec6c34ecf2a68efb9d528eb5879
  local checkout  /Users/stephenhe/Projects/ui-graph-explorer-integration

Why this file exists
--------------------
tools/bangle_seed_state.py originally did:

    from ui_graph.restoration import _IDB_EXPORT_JS

resolving it through `sys.path.insert(<script dir>/../src)`. That path exists in the
upstream repo but not in AutoE2E, so the seed script could not run here at all - and
importing the real `ui_graph.restoration` would also drag in structlog and the rest of
that package. Only this one constant is actually needed, and it is a self-contained
JavaScript source string with no Python dependencies, so it is vendored on its own.

This is the MINIMAL generic dependency required to make bangle-io's seeding step
self-contained. Upstream remains authoritative: re-sync from the commit above rather
than editing this copy.
"""

_IDB_EXPORT_JS = """
async () => {
    // Every request below is bounded. An IndexedDB request that is queued behind a blocked
    // delete never fires success, error OR blocked (see _IDB_IMPORT_JS), so an unbounded
    // request here does not fail slowly -- it never settles, and page.evaluate has no timeout.
    const DATABASES_TIMEOUT_MS = 3000;
    const OPEN_TIMEOUT_MS = 5000;
    const REQUEST_TIMEOUT_MS = 5000;

    function withTimeout(promise, ms, what) {
        let timer;
        const bound = new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error('timed out after ' + ms + 'ms: ' + what)), ms);
        });
        return Promise.race([promise, bound]).finally(() => clearTimeout(timer));
    }

    function request(req, what) {
        return withTimeout(new Promise((resolve, reject) => {
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        }), REQUEST_TIMEOUT_MS, what);
    }

    function serialize(val) {
        if (val === null || val === undefined) return val;
        if (val instanceof Date) return {__type: 'Date', v: val.toISOString()};
        if (val instanceof ArrayBuffer) {
            return {__type: 'ArrayBuffer', v: Array.from(new Uint8Array(val))};
        }
        if (ArrayBuffer.isView(val)) {
            return {__type: 'TypedArray', ctor: val.constructor.name,
                    v: Array.from(new Uint8Array(val.buffer, val.byteOffset, val.byteLength))};
        }
        if (val instanceof Blob) return {__type: 'Blob', size: val.size};
        if (Array.isArray(val)) return val.map(serialize);
        if (typeof val === 'object') {
            const out = {};
            for (const [k, v] of Object.entries(val)) out[k] = serialize(v);
            return out;
        }
        return val;
    }

    const result = {};
    // "Cannot enumerate" is NOT "has no IndexedDB state". Reported as its own status so the
    // caller can refuse EXACT restoration rather than assume an empty database set.
    if (!indexedDB.databases) return {status: 'unsupported', databases: result};

    const dbs = await withTimeout(indexedDB.databases(), DATABASES_TIMEOUT_MS,
                                  'indexedDB.databases()');
    for (const {name, version} of dbs) {
        if (!name) continue;
        let db = null;
        try {
            db = await withTimeout(new Promise((resolve, reject) => {
                const req = indexedDB.open(name, version);
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
                // onblocked alone is not enough: a request queued behind a blocked delete
                // fires nothing at all, which is why this also needs the timeout below.
                req.onblocked = () => reject(new Error('blocked'));
            }), OPEN_TIMEOUT_MS, 'indexedDB.open(' + name + ')');

            const dbData = {version: db.version, stores: {}};
            const storeNames = Array.from(db.objectStoreNames);
            for (const storeName of storeNames) {
                // One transaction per store: IndexedDB deactivates a transaction once control
                // returns to the event loop, so a single transaction spanning an await per
                // store throws TransactionInactiveError on the second store onward.
                const tx = db.transaction([storeName], 'readonly');
                const store = tx.objectStore(storeName);
                const keyPath = store.keyPath;
                const autoIncrement = store.autoIncrement;
                const indexes = [];
                for (let i = 0; i < store.indexNames.length; i++) {
                    const idx = store.index(store.indexNames[i]);
                    indexes.push({name: idx.name, keyPath: idx.keyPath,
                                  unique: idx.unique, multiEntry: idx.multiEntry});
                }
                const records = await request(store.getAll(), storeName + '.getAll()');
                const keys = await request(store.getAllKeys(), storeName + '.getAllKeys()');
                dbData.stores[storeName] = {
                    keyPath, autoIncrement, indexes,
                    records: records.map(serialize),
                    keys: keys.map(k => typeof k === 'object' ? JSON.stringify(k) : k)
                };
            }
            result[name] = dbData;
        } catch(e) {
            // A database we could not read is a failed export, not an app without that data.
            // Reporting it as a partial success is what let a wiped checkpoint look complete.
            throw new Error('indexeddb export failed for database "' + name + '": ' +
                            (e && e.message ? e.message : e));
        } finally {
            // The old code closed only on the success path, so every error path leaked a
            // connection -- and a leaked connection is precisely what blocks a later delete.
            if (db) { try { db.close(); } catch(e) {} }
        }
    }
    return {status: 'ok', databases: result};
}
"""
