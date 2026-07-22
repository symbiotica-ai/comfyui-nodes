// ABOUTME: Request cache for order parses — coalesces concurrent gets for one
// ABOUTME: key, serves settled keys from memory, and remembers failures, so a
// ABOUTME: render path can ask as often as it likes without re-hammering.

// get() resolves to a stable result object per key and never rejects:
//   { ok: true,  data }
//   { ok: false, status, error }
// Callers compare the returned object by identity to tell "this is the same
// answer I already have" from "something changed" — that check is what keeps a
// render -> fetch -> render cycle from running forever.
//
// A 4xx is treated as final: the server is saying this request can't be
// satisfied, so nothing but new inputs will change the answer. Anything else —
// a 5xx, or a network error with no status at all — may clear on its own, so it
// is retried on an exponential backoff instead of being cached forever.
export function createOrderCache({
    fetcher,
    now = () => Date.now(),
    baseBackoffMs = 1_000,
    maxBackoffMs = 30_000,
}) {
    const inflight = new Map();
    const final = new Map();    // key -> result (success or 4xx)
    const waiting = new Map();  // key -> { result, retryAt, attempts }

    const isFinal = (result) =>
        result.ok || (result.status >= 400 && result.status < 500);

    function remember(key, result) {
        if (isFinal(result)) {
            final.set(key, result);
            waiting.delete(key);
            return;
        }
        const attempts = (waiting.get(key)?.attempts ?? 0) + 1;
        const delay = Math.min(baseBackoffMs * 2 ** (attempts - 1), maxBackoffMs);
        waiting.set(key, { result, retryAt: now() + delay, attempts });
    }

    async function get(key) {
        if (final.has(key)) return final.get(key);

        const held = waiting.get(key);
        if (held && now() < held.retryAt) return held.result;

        const pending = inflight.get(key);
        if (pending) return pending;

        const p = fetcher(key)
            .then((data) => ({ ok: true, data }))
            .catch((err) => ({ ok: false, status: err?.status ?? 0,
                               error: err?.message ?? String(err) }))
            .then((result) => { remember(key, result); return result; })
            .finally(() => inflight.delete(key));

        inflight.set(key, p);
        return p;
    }

    // Drop what we remember about a key so the next get() asks the server
    // again. For deliberate user actions only — a render path that invalidates
    // is a render path that re-fetches every frame.
    function invalidate(key) {
        final.delete(key);
        waiting.delete(key);
    }

    return { get, invalidate };
}
