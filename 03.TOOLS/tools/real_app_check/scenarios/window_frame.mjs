// The native window and its page agree on size: as opened, maximised through the header's own maximise, and restored.
// The close button sits at the window's right edge and is lit only under the pointer. Reads Windows' client size
// (real_app_check.py window-frame) against the page's own viewport; needs the rig desktop, so it runs in the heavy slot.
export const steps = ['Studio opens and the page fills the window', 'Maximise: the page fills the maximised window', 'Restore: the page follows the window back', 'Open ArchHub restores the maximised window from the tray'];
export default async function ({step, js, until, native, cdp}) {
  await cdp('Emulation.clearDeviceMetricsOverride');  // this check reads the real window, not the harness's 1440 x 900 page
  const read = async () => ({
    frame: await native({kind: 'window-frame'}),
    page: await js(`(() => { const b = document.querySelector('[data-window-button=close]'), r = b && b.getBoundingClientRect(), k = window.devicePixelRatio;
      return {view: [Math.round(innerWidth * k), Math.round(innerHeight * k)], inner: innerWidth, close: r ? [r.left, r.right, r.width] : null,
        lit: b ? getComputedStyle(b).backgroundColor : '', hover: document.documentElement.dataset.windowHover || '',
        maximized: document.documentElement.dataset.windowMaximized || ''}; })()`),
  });
  const agree = ({frame, page}) => !frame.error && Math.abs(page.view[0] - frame.client[0]) <= 2 && Math.abs(page.view[1] - frame.client[1]) <= 2;
  const button = ({page}) => !!page.close && Math.abs(page.close[1] - page.inner) <= 1 && page.hover === '' && /rgba\(0, 0, 0, 0\)|transparent/.test(page.lit);
  const toggle = () => js("window.ARCHHUB_WINDOW_ACTION('maximize').then(result => result.ok)");
  await step(steps[0], async () => {
    await until(() => js("Boolean(document.querySelector('[data-home-page]'))"), Boolean);
    const got = await until(read, agree, 12);
    return {pass: agree(got) && button(got) && got.frame.zoomed === false, got};
  });
  await step(steps[1], async () => {
    const asked = await toggle();
    const got = await until(read, seen => seen.frame.zoomed === true && agree(seen) && seen.page.maximized === 'true', 12);
    return {pass: Boolean(asked) && got.frame.zoomed === true && agree(got) && button(got) && got.page.maximized === 'true', got};
  });
  await step(steps[2], async () => {
    const asked = await toggle();
    const got = await until(read, seen => seen.frame.zoomed === false && agree(seen) && seen.page.maximized === 'false', 12);
    return {pass: Boolean(asked) && got.frame.zoomed === false && agree(got) && button(got) && got.page.maximized === 'false', got};
  });
  await step(steps[3], async () => {
    const asked = await toggle();
    const before = await until(read, seen => seen.frame.zoomed === true, 12);
    if (!asked || !before.frame.zoomed) return {pass: false, got: {before}};
    const closed = await js("window.ARCHHUB_WINDOW_ACTION('close').then(result => result.ok)");
    const hidden = await until(() => native({kind: 'window-frame'}), frame => frame.visible === false, 12);
    if (!closed || hidden.visible !== false) return {pass: false, got: {before, hidden}};
    const open = await native({kind: 'reopen-rig-window'});
    const after = await until(read, seen => seen.frame.visible && seen.frame.zoomed && agree(seen), 12);
    return {pass: open.requested === true && after.frame.visible && after.frame.zoomed && agree(after),
      got: {before, hidden, open, after}};
  });
}
