const assert = require('node:assert/strict');

const GROUP_FOR_CAPABILITY = Object.freeze({
  Account:'Account', Profile:'Account', Team:'Account', Hub:'Connections', Connections:'Connections',
  Hosts:'Connections', Providers:'Connections', BABOOM:'AI', Models:'AI', Brain:'AI',
  Permissions:'Permissions', Workspaces:'Permissions', Theme:'Appearance', Shortcuts:'Appearance',
  System:'Appearance', Storage:'Storage & About', About:'Storage & About',
});

function settingsNavigator({doc, flush, settle, waitFor}) {
  const shell = doc.querySelector('[data-settings54-shell]');
  assert.ok(shell, 'actual Settings shell exists');
  const sidebar = shell.querySelector('[data-settings54-nav]');
  assert.ok(sidebar, 'actual Settings group rail exists');
  const capabilityButtons = label => [...sidebar.querySelectorAll('[data-settings54-capability-nav] button')]
    .filter(button => button.textContent.trim() === label);
  const capability = async label => {
    const title = [...sidebar.querySelectorAll('[data-settings54-group-title]')]
      .find(node => node.textContent.trim() === GROUP_FOR_CAPABILITY[label]);
    assert.ok(title, label + ' belongs to a Settings group');
    flush(() => title.closest('button').click());
    await settle();
    if (waitFor) await waitFor(() => capabilityButtons(label)[0], 'the admitted Settings selection exposes ' + label);
    const button = capabilityButtons(label)[0];
    assert.ok(button, 'the group has the ' + label + ' capability');
    return button;
  };
  const tab = async label => {
    const button = await capability(label);
    flush(() => button.click());
    await settle();
    const panel = shell.querySelector('[data-settings54-landing]') || shell.querySelector('aside:last-of-type > .ah-scroll');
    assert.ok(panel, label + ' owner renders in the Settings inspector');
    return panel;
  };
  return {shell, sidebar, tab, capability, capabilityButtons,
    labels:Object.keys(GROUP_FOR_CAPABILITY).filter(label => label !== 'System')};
}

module.exports = {settingsNavigator, GROUP_FOR_CAPABILITY};
