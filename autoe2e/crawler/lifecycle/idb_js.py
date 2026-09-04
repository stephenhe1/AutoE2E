"""IndexedDB import snippet, used to apply a captured client-state baseline to a page.

VENDORED - do not edit here.

Copied verbatim from:
  repo    git@github.com:stephenhe1/UI-Graph-Explorer.git
  path    src/ui_graph/restoration.py  (the `_IDB_IMPORT_JS` constant)
  commit  b07e8a846e8d9ec6c34ecf2a68efb9d528eb5879
  local checkout  /Users/stephenhe/Projects/ui-graph-explorer-integration

This is the counterpart of tools/idb_export_js.py: the export snippet captures a baseline,
this one applies it. It is `async (dump) => {...}` where `dump` is the mapping of database
name -> {version, stores}, i.e. exactly the `indexed_db` key that
tools/bangle_seed_state.py writes. Every request it makes is individually bounded, because
an IndexedDB delete can fail to fire success, error AND blocked, which otherwise hangs
forever.

Vendored so ClientState (autoe2e/crawler/lifecycle/hooks.py) can seed a browser profile
without depending on another research checkout. Upstream remains authoritative: re-sync
from the commit above rather than editing this copy.
"""

_IDB_IMPORT_JS = """
async (dump) => {
    // Every IndexedDB request below is bounded. See the comment on the delete step for the
    // hang these prevent.
    const DELETE_TIMEOUT_MS = 3000;
    const OPEN_TIMEOUT_MS = 5000;

    function withTimeout(promise, ms, what) {
        let timer;
        const bound = new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error('timed out after ' + ms + 'ms: ' + what)), ms);
        });
        return Promise.race([promise, bound]).finally(() => clearTimeout(timer));
    }

    function deserialize(val) {
        if (val === null || val === undefined) return val;
        if (typeof val === 'object' && val.__type) {
            switch (val.__type) {
                case 'Date': return new Date(val.v);
                case 'ArrayBuffer': return new Uint8Array(val.v).buffer;
                case 'TypedArray': {
                    const buf = new Uint8Array(val.v).buffer;
                    const Ctor = globalThis[val.ctor] || Uint8Array;
                    return new Ctor(buf);
                }
                default: return val;
            }
        }
        if (Array.isArray(val)) return val.map(deserialize);
        if (typeof val === 'object') {
            const out = {};
            for (const [k, v] of Object.entries(val)) out[k] = deserialize(v);
            return out;
        }
        return val;
    }
    // Restore a database WITHOUT deleting it, when the live schema already is the schema the dump
    // describes. Returns true when the whole dump for this database has been written.
    //
    // This exists because deleteDatabase is the single most destructive way to reach a state that
    // does not need it. An application that keeps one long-lived connection open -- the ordinary
    // pattern, and what `idb`'s openDB encourages -- blocks the delete; and a blocked delete request
    // stays QUEUED, so every later open() in the page queues behind it and never settles. One
    // restore attempt therefore did not merely fail: it poisoned IndexedDB for the rest of that
    // page's life, and every subsequent restoration and checkpoint export failed too.
    //
    // Clearing the stores and rewriting the records through an open connection reaches the identical
    // end state -- the records ARE the state -- while transactions simply queue behind the app's
    // connection instead of deadlocking with it. The delete path below is kept verbatim for the case
    // it is actually needed: a dump whose SCHEMA differs from what is live.
    async function restoreInPlace(dbName, dbData) {
        // Never bring a database into existence here: a DB that does not exist has no schema to
        // match, and open() would create an empty one and then be deleted below anyway.
        if (!indexedDB.databases) return false;
        let known;
        try {
            known = await withTimeout(indexedDB.databases(), DELETE_TIMEOUT_MS, 'databases()');
        } catch (e) { return false; }
        if (!known.some(d => d.name === dbName)) return false;

        let db;
        try {
            db = await withTimeout(new Promise((resolve, reject) => {
                // No version: opening at the live version cannot trigger an upgrade, so this can
                // never be blocked by another connection.
                const req = indexedDB.open(dbName);
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
                req.onblocked = () => reject(new Error('blocked'));
            }), OPEN_TIMEOUT_MS, 'open(' + dbName + ') in place');
        } catch (e) { return false; }

        // Equality, not containment. An extra live store would survive a delete-and-recreate as
        // absent, so accepting a superset here would make the two paths disagree about the state
        // they produce.
        const live = Array.from(db.objectStoreNames).sort();
        const wanted = Object.keys(dbData.stores || {}).sort();
        const sameSchema =
            live.length === wanted.length &&
            live.every((n, i) => n === wanted[i]) &&
            (dbData.version === null || dbData.version === undefined ||
             db.version === dbData.version);
        if (!sameSchema || live.length === 0) { db.close(); return false; }

        try {
            const tx = db.transaction(live, 'readwrite');
            for (const storeName of live) {
                const store = tx.objectStore(storeName);
                const storeData = dbData.stores[storeName];
                // Clear first: the dump is the whole content of the store, not an addition to it.
                store.clear();
                for (let i = 0; i < storeData.records.length; i++) {
                    const record = deserialize(storeData.records[i]);
                    if (storeData.keyPath === null && !storeData.autoIncrement) {
                        let key = storeData.keys[i];
                        try { key = JSON.parse(key); } catch (e) {}
                        store.add(record, key);
                    } else {
                        store.put(record);
                    }
                }
            }
            await withTimeout(new Promise((resolve, reject) => {
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error || new Error('transaction aborted'));
            }), OPEN_TIMEOUT_MS, 'in-place restore of ' + dbName);
        } catch (e) {
            db.close();
            return false;
        }
        db.close();
        return true;
    }

    for (const [dbName, dbData] of Object.entries(dump)) {
        if (await restoreInPlace(dbName, dbData)) continue;
        // The delete must actually COMPLETE before opening. Resolving on `blocked` and
        // carrying on looks harmless and is the bug that hung exploration indefinitely: a
        // blocked delete request stays queued, and IndexedDB then queues our subsequent
        // open() behind it. If the page holds a connection the delete never completes, so the
        // open never fires — and the open had no onblocked handler and no timeout, so the
        // promise simply never settled. Measured: 20s+ with no resolution, versus 0.00s once
        // the page closes its connection.
        //
        // So a blocked or slow delete now throws. Failing closed here is correct: the caller
        // maps a raised error to RestorationFailureCategory.PERSISTENT_BROWSER_STATE_LOST,
        // which is exactly what a database we could not reset amounts to.
        const deleteOutcome = await new Promise((resolve) => {
            const req = indexedDB.deleteDatabase(dbName);
            req.onsuccess = () => resolve('deleted');
            req.onerror = () => resolve('error');
            req.onblocked = () => resolve('blocked');
            setTimeout(() => resolve('timeout'), DELETE_TIMEOUT_MS);
        });
        if (deleteOutcome === 'blocked' || deleteOutcome === 'timeout') {
            throw new Error(
                'indexeddb reset ' + deleteOutcome + ' for database "' + dbName +
                '": a page connection is still open, so the database cannot be restored'
            );
        }
        const db = await new Promise((resolve, reject) => {
            const req = indexedDB.open(dbName, dbData.version);
            // Belt and braces. Even with the delete confirmed complete, an open can be blocked
            // by a connection created in the gap, and an unbounded open is what turned a
            // recoverable failure into a hung run.
            req.onblocked = () => reject(
                new Error('indexeddb open blocked for database "' + dbName + '"')
            );
            setTimeout(
                () => reject(new Error(
                    'indexeddb open timed out for database "' + dbName + '"'
                )),
                OPEN_TIMEOUT_MS
            );
            req.onupgradeneeded = (event) => {
                const db = event.target.result;
                for (const [storeName, storeData] of Object.entries(dbData.stores)) {
                    const opts = {};
                    if (storeData.keyPath !== null && storeData.keyPath !== undefined)
                        opts.keyPath = storeData.keyPath;
                    if (storeData.autoIncrement) opts.autoIncrement = true;
                    const store = db.createObjectStore(storeName, opts);
                    for (const idx of (storeData.indexes || [])) {
                        store.createIndex(idx.name, idx.keyPath,
                            {unique: idx.unique, multiEntry: idx.multiEntry});
                    }
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
        const storeNames = Object.keys(dbData.stores).filter(
            n => db.objectStoreNames.contains(n));
        if (storeNames.length > 0) {
            const tx = db.transaction(storeNames, 'readwrite');
            for (const storeName of storeNames) {
                const store = tx.objectStore(storeName);
                const storeData = dbData.stores[storeName];
                for (let i = 0; i < storeData.records.length; i++) {
                    const record = deserialize(storeData.records[i]);
                    if (storeData.keyPath === null && !storeData.autoIncrement) {
                        let key = storeData.keys[i];
                        try { key = JSON.parse(key); } catch(e) {}
                        store.add(record, key);
                    } else {
                        store.put(record);
                    }
                }
            }
            await new Promise((resolve, reject) => {
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
            });
        }
        db.close();
    }
}
"""
