// ABOUTME: Tests for the order-parse request cache — coalescing, result reuse,
// ABOUTME: and failure memory so a bad project path can't be re-hammered.
import { test } from "node:test";
import assert from "node:assert/strict";

import { createOrderCache } from "../../web/js/order_cache.js";

// A fetcher that counts calls and resolves on the next microtask, so several
// callers can pile up on the same key before the first one settles.
function counting(reply = () => ({ events: [] })) {
    const calls = [];
    const fn = async (key) => {
        calls.push(key);
        await Promise.resolve();
        return reply(key, calls.length);
    };
    fn.calls = calls;
    return fn;
}

test("concurrent gets on one key make a single request", async () => {
    const fetcher = counting();
    const cache = createOrderCache({ fetcher });

    await Promise.all([
        cache.get("bakery|October"),
        cache.get("bakery|October"),
        cache.get("bakery|October"),
    ]);

    assert.equal(fetcher.calls.length, 1);
});

test("a settled key is served from cache, same object every time", async () => {
    const fetcher = counting(() => ({ events: [{ feature: "Mini 1" }] }));
    const cache = createOrderCache({ fetcher });

    const first = await cache.get("bakery|October");
    const second = await cache.get("bakery|October");

    assert.equal(fetcher.calls.length, 1);
    // Identity, not just equality: the caller compares the returned value
    // against what it already holds to decide whether anything changed, and
    // that check is what stops a render -> fetch -> render cycle.
    assert.equal(first, second);
});

// A fetcher that always fails with the given HTTP status.
function failing(status) {
    const calls = [];
    const fn = async (key) => {
        calls.push(key);
        const err = new Error(status === 400 ? "order_path required" : "boom");
        err.status = status;
        throw err;
    };
    fn.calls = calls;
    return fn;
}

test("a 4xx failure is remembered and never re-requested", async () => {
    // The Modal case: the project path does not exist on the server host, so
    // this key can never succeed without the user changing project or month.
    //
    // The clock has to move for this to mean anything. Two gets in the same
    // millisecond also land inside the first backoff window, where a cache that
    // merely defers 4xx looks exactly like one that keeps them — and a deferred
    // 4xx is re-requested every backoff interval for as long as the tab is open.
    const fetcher = failing(400);
    let clock = 1_000;
    const cache = createOrderCache(
        { fetcher, now: () => clock, baseBackoffMs: 1_000, maxBackoffMs: 30_000 });

    const first = await cache.get("bakery|October");
    for (const jump of [1_100, 30_000, 300_000, 10_000_000]) {
        clock += jump;
        await cache.get("bakery|October");
    }
    const last = await cache.get("bakery|October");

    assert.equal(fetcher.calls.length, 1, "the 4xx was re-requested later");
    assert.equal(first.ok, false);
    assert.equal(first.status, 400);
    assert.equal(first, last);
});

test("a 5xx failure backs off, then retries once the delay has passed", async () => {
    // Unlike a 4xx, a server error may well clear on its own — but retrying it
    // freely is what turns a blip into a self-inflicted flood.
    const fetcher = failing(500);
    let clock = 1_000;
    const cache = createOrderCache(
        { fetcher, now: () => clock, baseBackoffMs: 1_000 });

    await cache.get("bakery|October");
    assert.equal(fetcher.calls.length, 1);

    clock += 500; // still inside the backoff window
    await cache.get("bakery|October");
    assert.equal(fetcher.calls.length, 1, "retried before the backoff elapsed");

    clock += 600; // 1100ms since the failure, past the 1000ms backoff
    await cache.get("bakery|October");
    assert.equal(fetcher.calls.length, 2, "did not retry after the backoff");
});

test("invalidate lets a remembered failure be retried", async () => {
    // Without this the 4xx memory is a trap: if the server starts serving the
    // very same project and month, nothing short of a page reload recovers.
    // Explicit user actions invalidate; render paths never do.
    const fetcher = failing(400);
    const cache = createOrderCache({ fetcher });

    await cache.get("bakery|October");
    await cache.get("bakery|October");
    assert.equal(fetcher.calls.length, 1);

    cache.invalidate("bakery|October");
    await cache.get("bakery|October");
    assert.equal(fetcher.calls.length, 2);
});

test("a rate limit is retried, not remembered as final", async () => {
    // 429 and 408 are 4xx but explicitly temporary. Filing them next to 404
    // would leave the panel empty for the rest of the session over a burst
    // that cleared in seconds.
    for (const status of [408, 429]) {
        const fetcher = failing(status);
        let clock = 1_000;
        const cache = createOrderCache(
            { fetcher, now: () => clock, baseBackoffMs: 1_000 });

        await cache.get("bakery|October");
        clock += 1_100;
        await cache.get("bakery|October");

        assert.equal(fetcher.calls.length, 2, `${status} was cached as final`);
    }
});

test("get() resolves rather than throwing when the fetcher throws outright", async () => {
    // A fetcher that throws before returning a promise would otherwise escape
    // the cache entirely — no coalescing, no memory, and every render path
    // asking again.
    const calls = [];
    const cache = createOrderCache({
        fetcher: (key) => { calls.push(key); throw new Error("bad route"); },
    });

    const first = await cache.get("bakery|October");
    const second = await cache.get("bakery|October");

    assert.equal(first.ok, false);
    assert.equal(calls.length, 1);
    assert.equal(first, second);
});

test("invalidating mid-request discards that request's answer", async () => {
    // The user retries while a parse is still in flight. Joining the doomed
    // request would cache its failure after the invalidate, so the deliberate
    // retry is lost and a second edit is needed to recover.
    let healthy = false;
    let release;
    const gate = new Promise((r) => { release = r; });
    const calls = [];
    const fetcher = async (key) => {
        calls.push(key);
        if (!healthy) {
            await gate;
            const err = new Error("order_path required");
            err.status = 400;
            throw err;
        }
        return { events: [{ feature: "Mini 1" }] };
    };
    const cache = createOrderCache({ fetcher });

    const doomed = cache.get("bakery|October");
    healthy = true;
    cache.invalidate("bakery|October");
    const retried = cache.get("bakery|October");
    release();
    await doomed;

    assert.equal((await retried).ok, true, "the retry joined the doomed request");
    assert.equal(calls.length, 2, "the retry did not reach the fetcher");
    // The superseded failure must not land in the cache behind the retry.
    assert.equal((await cache.get("bakery|October")).ok, true,
                 "the discarded failure was cached anyway");
});

test("a different key is fetched separately", async () => {
    const fetcher = counting();
    const cache = createOrderCache({ fetcher });

    await cache.get("bakery|October");
    await cache.get("bakery|November");

    assert.deepEqual(fetcher.calls, ["bakery|October", "bakery|November"]);
});
