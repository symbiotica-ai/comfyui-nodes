// ABOUTME: Request cache for order parses — coalesces concurrent gets for one
// ABOUTME: key, serves settled keys from memory, and remembers failures, so a
// ABOUTME: render path can ask as often as it likes without re-hammering.

// A 4xx the server will keep giving for the same request. 408 and 429 are the
// exceptions: both say "not now" rather than "not ever", so they go through the
// backoff instead of being kept.
const TRANSIENT_STATUSES = new Set([408, 429]);

// get() resolves to a stable result object per key and never rejects:
//   { ok: true,  data }
//   { ok: false, status, error }
// Callers compare the returned object by identity to tell "this is the same
// answer I already have" from "something changed" — that check is what keeps a
// render -> fetch -> render cycle from running forever.
//
// A final answer is kept until the key is invalidated, since nothing but new
// inputs would change it. Anything else — a 5xx, a rate limit, or a network
// error with no status at all — is retried on an exponential backoff.
export function createOrderCache({
    fetcher,
    now = () => Date.now(),
    baseBackoffMs = 1_000,
    maxBackoffMs = 30_000,
}) {
    const inflight = new Map();
    const final = new Map();      // key -> result nothing but new inputs changes
    const waiting = new Map();    // key -> { result, retryAt, attempts }
    const supersededAt = new Map(); // key -> invalidate count, to date requests

    const isFinal = (result) =>
        result.ok || (result.status >= 400 && result.status < 500
                      && !TRANSIENT_STATUSES.has(result.status));

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

        // Anything invalidated after this point supersedes the request we are
        // about to make, so its answer must not be recorded when it lands.
        const issued = supersededAt.get(key) ?? 0;
        // Promise.resolve first: a fetcher that throws outright would otherwise
        // escape the cache entirely, leaving the callers unguarded.
        const p = Promise.resolve()
            .then(() => fetcher(key))
            .then((data) => ({ ok: true, data }))
            .catch((err) => ({ ok: false, status: err?.status ?? 0,
                               error: err?.message ?? String(err) }))
            .then((result) => {
                if ((supersededAt.get(key) ?? 0) === issued) remember(key, result);
                return result;
            })
            .finally(() => { if (inflight.get(key) === p) inflight.delete(key); });

        inflight.set(key, p);
        return p;
    }

    // Drop what we know about a key, including any request already on the wire,
    // so the next get() asks the server again. For deliberate user actions only
    // — a render path that invalidates is a render path that re-fetches every
    // frame.
    function invalidate(key) {
        final.delete(key);
        waiting.delete(key);
        inflight.delete(key);
        supersededAt.set(key, (supersededAt.get(key) ?? 0) + 1);
    }

    return { get, invalidate };
}
