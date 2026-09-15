"use strict";

async function bounded(operation) {
  let timer;
  try {
    return await Promise.race([
      operation,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("pointer court operation timed out")), 1500); }),
    ]);
  } finally { clearTimeout(timer); }
}

async function measurePointerPan(page, box) {
  const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  let evidence, failure, collector = false, pointer = false, space = false;
  const cleanupErrors = [];
  const stop = () => bounded(page.evaluate(() => {
    const probe = window.__archhubPointerFrameProbe;
    if (!probe) return null;
    cancelAnimationFrame(probe.frame);
    delete window.__archhubPointerFrameProbe;
    const canvas = document.querySelector(".canvas[data-universal='true']");
    return {
      timestamps: probe.timestamps, overflow: probe.overflow,
      durationMs: performance.now() - probe.started,
      before: probe.before,
      after: { x: Number(canvas?.dataset.panX), y: Number(canvas?.dataset.panY) },
    };
  }));
  try {
    await bounded(page.evaluate(position => {
      const canvas = document.querySelector(".canvas[data-universal='true']");
      const hit = document.elementFromPoint(position.x, position.y);
      if (!canvas || !hit || !canvas.contains(hit)) throw new Error("pointer court canvas is covered");
    }, point));
    await bounded(page.locator(".canvas[data-universal='true']").focus());
    await bounded(page.mouse.move(point.x, point.y));
    space = true; await bounded(page.keyboard.down("Space"));
    pointer = true; await bounded(page.mouse.down());
    collector = true;
    await bounded(page.evaluate(() => {
      const canvas = document.querySelector(".canvas[data-universal='true']");
      const probe = window.__archhubPointerFrameProbe = {
        timestamps: [], frame: null, overflow: false, started: performance.now(),
        before: { x: Number(canvas?.dataset.panX), y: Number(canvas?.dataset.panY) },
      };
      const tick = now => {
        if (probe.timestamps.length >= 512) { probe.overflow = true; return; }
        probe.timestamps.push(now);
        probe.frame = requestAnimationFrame(tick);
      };
      probe.frame = requestAnimationFrame(tick);
    }));
    const deadline = Date.now() + 10000;
    for (let step = 1; step <= 60; step++) {
      if (Date.now() >= deadline) throw new Error("pointer court gesture exceeded 10 seconds");
      await bounded(page.mouse.move(point.x + step * 3, point.y + step));
      await bounded(page.evaluate(() => new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          cancelAnimationFrame(frame);
          reject(new Error("pointer court received no animation frame"));
        }, 1000);
        const frame = requestAnimationFrame(() => { clearTimeout(timer); resolve(); });
      })));
    }
    evidence = await stop(); collector = false;
  } catch (error) { failure = error; }
  finally {
    if (collector) { try { await stop(); } catch (error) { cleanupErrors.push(error); } }
    if (pointer) { try { await bounded(page.mouse.up()); } catch (error) { cleanupErrors.push(error); } }
    if (space) { try { await bounded(page.keyboard.up("Space")); } catch (error) { cleanupErrors.push(error); } }
  }
  if (failure) throw failure;
  if (cleanupErrors.length) throw cleanupErrors[0];
  if (!evidence) throw new Error("pointer court has no frame evidence");
  return evidence;
}

function judgePointerFrames(evidence) {
  const timestamps = evidence.timestamps;
  const intervals = timestamps.slice(1).map((value, index) => value - timestamps[index]);
  const valid = timestamps.every(Number.isFinite) && intervals.every(value => Number.isFinite(value) && value > 0);
  const panChanged = [evidence.before.x, evidence.before.y, evidence.after.x, evidence.after.y].every(Number.isFinite)
    && (evidence.before.x !== evidence.after.x || evidence.before.y !== evidence.after.y);
  const ordered = intervals.slice().sort((a, b) => a - b);
  const p95Ms = valid && ordered.length ? ordered[Math.ceil(ordered.length * 0.95) - 1] : null;
  return {
    ...evidence,
    pass: valid && intervals.length >= 20 && !evidence.overflow && panChanged
      && Number.isFinite(evidence.durationMs) && evidence.durationMs > 0 && evidence.durationMs <= 10000
      && p95Ms !== null && p95Ms <= 16.7,
    p95Ms, limitMs: 16.7, percentileMethod: "nearest-rank",
    sampleCount: intervals.length, panChanged, intervals,
  };
}

module.exports = { measurePointerPan, judgePointerFrames };
