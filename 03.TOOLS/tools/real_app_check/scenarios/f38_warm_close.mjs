export const steps = ['Installed Studio offers its native window controls'];

export default async function ({step, js, until, native}) {
  const ready = await until(() => js('typeof window.ARCHHUB_WINDOW_ACTION === "function"'), Boolean);
  const before = ready ? await native({kind:'f38-window-state', phase:'before'}) : {};
  await step(steps[0], async () => ({
    pass: Boolean(ready && before.visible_window_pids?.length && before.listener_http_204),
    got: before,
  }));
  if (!ready || !before.listener_http_204) return;
  await js('window.ARCHHUB_WINDOW_ACTION("close")').catch(() => null);
  const closed = await native({kind:'f38-window-state', phase:'close'});
  if (closed.tray_setup && closed.listener_owned && !closed.visible_window_pids.length) {
    await js('window.ARCHHUB_WINDOW_ACTION("quit")').catch(() => null);
    await native({kind:'f38-window-state', phase:'quit'});
  }
}
