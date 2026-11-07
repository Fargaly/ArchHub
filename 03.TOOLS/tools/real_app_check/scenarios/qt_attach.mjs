export const steps = ['Installed Studio opens Home', 'Click Settings and read its screen'];
export default async function ({step, js, until, clickText}) {
  await step(steps[0], async () => {
    const home = await until(() => js("Boolean(document.querySelector('[data-home-page]'))"), Boolean);
    return {pass: Boolean(home), got: {path: await js('location.pathname')}};
  });
  await step(steps[1], async () => {
    const clicked = await clickText('Settings');
    const screen = await until(() => js("document.querySelector('[data-screen^=settings]')?.dataset.screen || ''"), Boolean);
    return {pass: Boolean(clicked && screen), got: {clicked, screen}};
  });
}
