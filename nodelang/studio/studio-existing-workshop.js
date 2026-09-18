/* Conversation projection over the existing admitted Workshop HTTP boundary. */
(function (global) {
  'use strict';
  const fail = text => { throw new Error(text); };
  const text = value => typeof value === 'string' && value.length > 0;
  const revision = value => Number.isSafeInteger(value) && value >= 0;
  const storageName = 'archhub.existing-workshop.pending.v1';
  const releaseStorageName = 'archhub.existing-workshop.releases.v1';

  function create({get, post, pendingStorage, projectCanvas,
      uuid = () => global.crypto.randomUUID(),
      hash = async value => Array.from(new Uint8Array(await global.crypto.subtle.digest(
        'SHA-256', new TextEncoder().encode(value))), byte => byte.toString(16).padStart(2, '0')).join('')}) {
    let canvas = null, workshops = [], workshop = null, workshopNotice = '', epoch = 0, membershipEpoch = 0;
    let snapshot = null, nativeWork = null, nativeRead = 0;
    let pageTarget = null, pageEpoch = 0;
    let conversationCatalog = null, conversationCatalogPage = null, catalogEpoch = 0;
    let conversationCreation = null, conversationWrite = null;
    const catalogReads = new Map();
    let applicationUpdate = null, applicationUpdateError = '', applicationUpdatePending = '';
    let updateRead = null, updateWrite = null, updateEpoch = 0, updateWatchers = 0, updateTimer = null, updateReads = 0;
    let topologyCanvas = null, topologyGraph = null, topologyError = '', topologyPending = false;
    let topologyRead = null, topologyWrite = null, topologyRequiresRefresh = false;
    let providerRead = null, providerSave = null;
    let themeCanvas = null, themeWrite = null, themeError = '';
    const updateActive = () => ['checking', 'downloading', 'restarting'].includes(applicationUpdate?.state);
    const listeners = new Set(), reads = new Map(), sends = new Map(), creations = new Map();
    const publish = () => {
      snapshot = {canvas, workshops, workshop, workshopPage:pageTarget, workshopNotice, nativeWork,
        conversationCatalog, conversationCatalogPage, conversationCreation,
        applicationUpdate, applicationUpdateError, applicationUpdatePending,
        theme: {configuration:themeCanvas?.configuration || null, pending:!!themeWrite, error:themeError},
        topology:topologyCanvas ? {canvas:topologyCanvas, graph:topologyGraph, selected:topologyCanvas.selected,
          pending:topologyPending, error:topologyError, requires_refresh:topologyRequiresRefresh} : null};
      // Presentation failures must not convert an accepted write into a retry.
      for (const listener of listeners) { try { listener(); } catch (_) {} }
    };
    const current = (stamp, root) => epoch === stamp.epoch && membershipEpoch === stamp.membership && canvas?.graph_id === stamp.graph &&
      canvas?.root === stamp.scope && workshops.some(row => row.root === root);
    const stampFor = root => {
      if (!canvas || !workshops.some(row => row.root === root)) fail('This Workshop is no longer on the canvas.');
      return {graph:canvas.graph_id, scope:canvas.root, epoch, membership:membershipEpoch};
    };
    const topologyIdentity = value => JSON.stringify([value?.application_root, value?.authorization?.subject,
      value?.authorization?.session, value?.scope?.current]);
    const acceptTheme = value => {
      const config = value?.configuration, fields = config?.theme_fields, theme = config?.theme;
      if (!revision(value?.revision) || value.interaction_projection?.revision !== value.revision ||
          !Array.isArray(value.interaction_projection?.bindings) || !text(value.application_root) ||
          !text(value.authorization?.subject) || !text(value.authorization?.session) || !text(value.scope?.current) ||
          !theme || Object.keys(theme).length !== 35 || !Array.isArray(fields) || fields.length !== 35 ||
          new Set(fields.map(field => field.key)).size !== 35 || fields.some(field =>
            !text(field.key) || !/^#[0-9a-fA-F]{6}$/.test(theme[field.key]) || field.value !== theme[field.key] ||
            !text(field.control) || !text(field.event_fact_input) || !text(field.token_root)) ||
          !Array.isArray(config.history) || !Array.isArray(config.personal_wip_heads)) {
        fail('Personal Settings did not return its current theme and controls.');
      }
      if (themeCanvas && topologyIdentity(themeCanvas) === topologyIdentity(value) && value.revision < themeCanvas.revision) {
        fail('The returned Personal Settings revision is stale.');
      }
      global.ArchHubTheme?.validate(theme);
      global.ArchHubTheme?.apply(theme);
      themeCanvas = value;
      publish();
      return value;
    };
    const themeBinding = (value, control, facts) => {
      const matches = value.interaction_projection.bindings.filter(row => row.control === control);
      if (matches.length !== 1 || !text(matches[0].interaction) || !text(matches[0].event) ||
          matches[0].projection_mode !== 'interaction-delta-v1' || matches[0].acknowledgement_mode !== 'receipt-v1') {
        fail('Personal Settings has no current control for this change.');
      }
      const row = matches[0], specs = row.event_facts;
      if (!Array.isArray(specs) || specs.length !== facts.length || facts.some(fact => !specs.some(spec =>
          spec.input === fact.input && spec.value_kind === 'text' &&
          Number.isSafeInteger(spec.maximum_bytes) && new TextEncoder().encode(fact.value).length <= spec.maximum_bytes))) {
        fail('The theme value does not match its declared input.');
      }
      return {interaction:row.interaction, control, event:row.event, revision:value.revision,
        projection_mode:'interaction-delta-v1', ...(facts.length ? {event_facts:facts} : {})};
    };
    const changeTheme = (kind, key, value) => {
      if (themeWrite) fail('Wait for the current theme save to finish.');
      if (kind === 'preview' && (typeof value !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(value))) {
        fail('Enter a six-digit hex colour, such as #1177aa.');
      }
      if (kind === 'baboom-startup' && value !== 'on' && value !== 'off') fail('BABOOM startup must be on or off.');
      if (kind === 'composer-model' && (typeof value !== 'string' || value.length > 200 || /[^\x21-\x7e]/.test(value))) {
        fail('The model route is invalid.');
      }
      const identity = themeCanvas && topologyIdentity(themeCanvas);
      let acceptedRead = false, submitted = false, committed = false;
      themeError = '';
      const save = async (fresh, held) => {
        if (identity && topologyIdentity(fresh) !== identity) fail('The view changed. Review its Personal Settings before saving.');
        const base = held ? fresh : acceptTheme(fresh), config = base.configuration;
        acceptedRead = true;
        if (kind !== 'baboom-startup' && kind !== 'composer-model' && config.personal_wip_heads.length !== 1) fail('Personal Settings needs one draft before Save or Restore.');
        let control, facts = [];
        if (kind === 'preview') {
          const field = config.theme_fields.find(field => field.key === key);
          if (!field) fail('The selected colour is not declared in Personal Settings.');
          control = field.control;
          facts = [{input:field.event_fact_input, value}];
        } else if (kind === 'baboom-startup') {
          const setting = config.baboom_startup;
          if (!setting || setting.available !== true || !text(setting.control) || !text(setting.event_fact_input)) {
            fail('BABOOM startup cannot be changed from this view.');
          }
          if (setting.value === value) fail('BABOOM startup is already ' + value + '.');
          control = setting.control;
          facts = [{input:setting.event_fact_input, value}];
        } else if (kind === 'composer-model') {
          const setting = config.composer_model;
          if (!setting || setting.available !== true || !text(setting.control) || !text(setting.event_fact_input)) {
            fail('The model selection cannot be saved from this view.');
          }
          // Only a pick the graph holds is unchanged. With no binding the graph
          // takes its first value, even '', so a clear also retires a pick an
          // older build recorded beside the graph.
          if (setting.source === 'graph' && setting.value === value) {
            return held ? null : {ok:true, unchanged:true, configuration_state:{composer_model:setting}};
          }
          control = setting.control;
          facts = [{input:setting.event_fact_input, value}];
        } else {
          const entry = config.history.find(entry => entry.revision === key && !entry.current && text(entry.restore_control));
          if (!entry) fail('This theme version cannot be restored from the current view.');
          control = entry.restore_control;
        }
        const request = themeBinding(base, control, facts);
        submitted = true;
        const result = await post('/api/universal/interaction', request);
        committed = result?.ok === true && revision(result.committed_revision) && result.committed_revision > base.revision;
        if (result?.projection_mode !== 'interaction-delta-v1' || result.base_revision !== base.revision ||
            !committed || result.committed_revision > result.revision ||
            !revision(result.revision) || result.revision <= base.revision ||
            !Array.isArray(result.control_state?.controls) || !result.control_state.controls.length ||
            !result.configuration_state || !result.interaction_projection ||
            (kind === 'preview' && result.configuration_state.theme?.[key] !== value) ||
            (kind === 'baboom-startup' && result.configuration_state.baboom_startup?.value !== value) ||
            (kind === 'composer-model' && result.configuration_state.composer_model?.value !== value) ||
            (kind === 'restore' && result.configuration_state.preview_revision === config.preview_revision)) {
          fail('The theme save needs reconciliation. Refresh Personal Settings before another save.');
        }
        acceptTheme({...base, revision:result.revision, interaction_projection:result.interaction_projection,
          configuration:{...config, ...result.configuration_state}});
        return result;
      };
      const operation = Promise.resolve().then(async () => {
        // A model pick saves against the view this page holds while no newer
        // revision has been seen. Reading the whole canvas first doubled the
        // pick on a 137-node scratch graph (read then save 5162 ms, save alone
        // 2572 ms, 2026-09-17). The server refuses a revision it has moved past
        // before writing anything; only then, or when the held view cannot
        // make the request, is the view read fresh. A held view never answers
        // "unchanged" on its own.
        if (kind === 'composer-model' && themeCanvas?.configuration?.composer_model?.available === true &&
            !(topologyCanvas?.revision > themeCanvas.revision)) {
          try {
            const saved = await save(themeCanvas, true);
            if (saved) return saved;
          } catch (error) {
            if (committed || (submitted && !(error.status === 409 ||
                /^(expected revision \d+, current revision is \d+|interaction projection cache is unavailable)$/.test(error.message || '')))) {
              throw error;
            }
          }
          acceptedRead = false; submitted = false;
        }
        return save(await get('/api/universal/canvas'), false);
      }).catch(async error => {
        if (!acceptedRead || submitted) themeCanvas = null;
        themeError = committed ? 'Saved in Personal Settings; refresh to review. Do not repeat this save.' :
          submitted && !(error.status >= 400 && error.status < 500) ?
            'Save outcome unknown; refresh Personal Settings before saving again.' :
          error.message || 'Personal Settings could not be saved.';
        if (error.status === 409 || (kind === 'baboom-startup' && submitted && error.status === 400)) {
          try {
            const refreshed = await get('/api/universal/canvas');
            if (!identity || topologyIdentity(refreshed) === identity) acceptTheme(refreshed);
          } catch (_) {}
          themeError = kind === 'baboom-startup' ?
            'BABOOM startup was not changed. Review the refreshed setting and try again.' :
            kind === 'composer-model' ? 'The model selection changed before this save. Pick the model again.' :
            'Personal Settings changed before this save. Review the refreshed theme and save again.';
        }
        publish();
        throw new Error(themeError);
      }).finally(() => { themeWrite = null; publish(); });
      themeWrite = operation;
      publish();
      return operation;
    };
    const acceptTopology = value => {
      if (!value || value.ok === false || !revision(value.revision) || !text(value.application_root) ||
          !text(value.authorization?.subject) || !text(value.authorization?.session) || !text(value.scope?.current) ||
          !Array.isArray(value.nodes) || !Array.isArray(value.wires) ||
          value.interaction_projection?.revision !== value.revision || !Array.isArray(value.interaction_projection?.bindings)) {
        fail('The canvas did not return its current graph interaction authority.');
      }
      if (topologyCanvas && topologyIdentity(value) === topologyIdentity(topologyCanvas) && value.revision < topologyCanvas.revision) {
        fail('The returned canvas is stale.');
      }
      const graph = typeof projectCanvas === 'function' ? projectCanvas(value) : null;
      if (topologyCanvas && (value.authorization.subject !== topologyCanvas.authorization.subject ||
          value.authorization.session !== topologyCanvas.authorization.session)) {
        epoch += 1; workshop = null; nativeWork = null; pageTarget = null; pageEpoch += 1;
        conversationCatalog = null; conversationCatalogPage = null; catalogEpoch += 1; conversationCreation = null;
      }
      topologyCanvas = value; topologyGraph = graph;
      if (value.workshop_scope) api.setCanvas(value.workshop_scope);
      publish(); return value;
    };
    // One committed drag is the held canvas with the admitted points at the
    // receipted revision. Reading the whole canvas back only to learn the two
    // facts the receipt already states cost the drag a second full projection.
    const acceptTopologyLayout = (identity, moved, committedRevision) => {
      const value = topologyCanvas;
      if (!value || topologyIdentity(value) !== identity || !revision(committedRevision) ||
          committedRevision < value.revision ||
          Object.keys(moved).some(root => !value.nodes.some(node => node.id === root))) {
        fail('The saved positions could not be confirmed. Refresh the canvas.');
      }
      return acceptTopology({...value, revision:committedRevision,
        nodes:value.nodes.map(node => moved[node.id]
          ? {...node, x:moved[node.id].x, y:moved[node.id].y} : node),
        interaction_projection:{...value.interaction_projection, revision:committedRevision}});
    };
    const readTopology = async identity => {
      const value = acceptTopology(await get('/api/universal/canvas'));
      if (identity && topologyIdentity(value) !== identity) fail('The canvas scope changed. Choose the connection again.');
      return value;
    };
    const topologyBinding = (value, control, facts = []) => {
      if (!text(control)) fail('This connection has no admitted graph control.');
      const matches = value.interaction_projection.bindings.filter(row => row.control === control);
      if (matches.length !== 1 || !text(matches[0].interaction) || !text(matches[0].event) ||
          matches[0].acknowledgement_mode !== 'receipt-v1' || matches[0].projection_mode !== 'topology-delta-v1') {
        fail('Refresh the canvas to obtain its connection lease.');
      }
      const binding = matches[0], expectedFacts = binding.event_facts || [];
      if (!Array.isArray(expectedFacts) || expectedFacts.length !== facts.length || facts.some(fact =>
          !expectedFacts.some(spec => spec.input === fact.input && spec.value_kind === 'number' &&
            Number.isSafeInteger(fact.value) && fact.value >= 0 &&
            (spec.minimum == null || fact.value >= spec.minimum) && (spec.maximum == null || fact.value <= spec.maximum)))) {
        fail('The selected endpoint is outside the admitted connection choices.');
      }
      return {interaction:binding.interaction, control, event:binding.event, revision:value.revision,
        projection_mode:binding.acknowledgement_mode, ...(facts.length ? {event_facts:facts} : {})};
    };
    const runTopology = (key, task) => {
      if (conversationWrite) fail('Wait for conversation creation to finish before editing the canvas.');
      if (topologyWrite) {
        if (topologyWrite.key === key) return topologyWrite.promise;
        fail('Wait for the current connection operation to finish.');
      }
      if (!topologyCanvas || topologyRequiresRefresh) fail('Read the canvas before editing connections.');
      const identity = topologyIdentity(topologyCanvas);
      let submitted = false;
      topologyPending = true; topologyError = ''; publish();
      const operation = Promise.resolve().then(async () => {
        if (topologyRead) await topologyRead;
        if (topologyIdentity(topologyCanvas) !== identity) fail('The canvas scope changed. Choose the connection again.');
        return task(identity, async (path, body) => {
          submitted = true;
          return post(path, body);
        });
      }).catch(error => {
        topologyRequiresRefresh = topologyRequiresRefresh || submitted;
        topologyError = (error.message || 'The connection operation was refused.') +
          (submitted ? ' Refresh the canvas and inspect the connection before trying again.' : '');
        publish(); throw error;
      }).finally(() => { topologyWrite = null; topologyPending = false; publish(); });
      topologyWrite = {key, promise:operation};
      return operation;
    };
    const acceptUpdate = result => {
      if (!result || result.ok !== true || !text(result.current_build) || result.current_build.length > 256 ||
          !['idle', 'checking', 'downloading', 'ready', 'restarting', 'failed'].includes(result.state) ||
          (result.available_build != null && (!text(result.available_build) || result.available_build.length > 256)) ||
          (result.detail != null && (typeof result.detail !== 'string' || result.detail.length > 4096)) ||
          typeof result.restart_supported !== 'boolean' || (result.state === 'ready' && !text(result.available_build)) ||
          [result.updated_from, result.updated_to].some(build => build != null && (!text(build) || build.length > 256))) {
        fail('Application update status could not be verified.');
      }
      applicationUpdate = {ok:true, current_build:result.current_build, state:result.state,
        available_build:result.available_build || null, detail:result.detail || '', restart_supported:result.restart_supported,
        updated_from:result.updated_from || null, updated_to:result.updated_to || null};
      applicationUpdateError = ''; publish(); return applicationUpdate;
    };
    const scheduleUpdateRead = () => {
      if (updateTimer !== null) global.clearTimeout(updateTimer);
      updateTimer = null;
      if (!updateWatchers || global.document?.hidden || applicationUpdateError || !updateActive() || updateWrite) return;
      updateTimer = global.setTimeout(() => {
        updateTimer = null;
        if (updateWatchers && !global.document?.hidden) api.refreshApplicationUpdate().catch(() => {});
      }, 5000);
    };
    const updateVisibility = () => {
      if (global.document?.hidden) { scheduleUpdateRead(); return; }
      if (updateWatchers && !applicationUpdateError && (updateActive() || !applicationUpdate)) {
        api.refreshApplicationUpdate().catch(() => {});
      }
    };
    const records = () => {
      // Storage restrictions must not prevent reading the conversation.
      pendingStorage = pendingStorage || global.sessionStorage;
      if (!pendingStorage) fail('Session storage is required to preserve pending messages.');
      const held = JSON.parse(pendingStorage.getItem(storageName) || '{}');
      if (!held || Array.isArray(held) || typeof held !== 'object' || Object.entries(held).some(
        ([key, value]) => !/^[a-f0-9]{64}$/.test(key) || !text(value) || value.length > 128)) {
        fail('Pending Workshop messages need recovery.');
      }
      return held;
    };
    const releaseRecords = () => {
      pendingStorage = pendingStorage || global.sessionStorage;
      if (!pendingStorage) fail('Session storage is required to recover finished reviews.');
      const raw = pendingStorage.getItem(releaseStorageName) || '{}';
      if (raw.length > 65536) fail('Pending review recovery exceeds its storage limit.');
      const held = JSON.parse(raw), fields = ['graph', 'scope', 'root', 'work', 'request_id', 'owner', 'view'];
      if (!held || Array.isArray(held) || typeof held !== 'object' || Object.keys(held).length > 8 ||
          Object.entries(held).some(([key, value]) => {
            if (!/^[a-f0-9]{64}$/.test(key) || !value || Array.isArray(value)) return true;
            const local = value.result !== undefined || value.resolution !== undefined;
            const expected = local ? [...fields, 'result', 'resolution'] : fields;
            return Object.keys(value).length !== expected.length || expected.some(field => !text(value[field]) ||
              value[field].length > (field === 'request_id' ? 119 : 4096)) ||
              (local && (!value.result.endsWith(':project-result') ||
                value.resolution !== value.result.slice(0, -':project-result'.length) + ':project-local-resolution'));
          })) {
        fail('Pending review recovery is invalid.');
      }
      return held;
    };
    async function readWorkshop(root, before = null, feed = (pageTarget?.root === root ? pageTarget.feed : 'all') || 'all',
        feedInitialized = pageTarget?.root === root && pageTarget.feedInitialized === true) {
      if (!['all', 'messages', 'activity'].includes(feed)) fail('Choose a valid Workshop feed.');
      const stamp = stampFor(root);
      const contentKnown = (workshop?.root === root && workshop.storage === 'conversation-content') ||
        (pageTarget?.root === root && pageTarget.storage === 'conversation-content');
      if (!pageTarget || pageTarget.root !== root || pageTarget.before !== before || pageTarget.feed !== feed ||
          pageTarget.feedInitialized !== feedInitialized) {
        pageTarget = {root, before, feed, feedInitialized,
          ...(contentKnown ? {storage:'conversation-content'} : {})}; pageEpoch += 1;
        workshop = null; publish();
      }
      const pageStamp = pageEpoch;
      const isCurrent = () => current(stamp, root) && pageStamp === pageEpoch &&
        pageTarget?.root === root && pageTarget.before === before && pageTarget.feed === feed;
      const key = JSON.stringify([stamp.epoch, stamp.membership, pageStamp, root, before, feed]);
      if (reads.has(key)) return reads.get(key);
      const previous = workshop?.root === root && !workshop.error ? workshop : null;
      const ordinary = previous?.storage === 'conversation-content';
      const operation = (async () => {
        try {
          const result = await get('/api/universal/workshop?root=' + encodeURIComponent(root) +
            '&scope=' + encodeURIComponent(stamp.scope) +
            (feed === 'all' ? '' : '&feed=' + feed) +
            (before === null ? '' : '&before=' + encodeURIComponent(before)) +
            (previous ? '&after=' + previous.revision : '') +
            (ordinary ? '&content_after=' + encodeURIComponent(previous.content_cursor) : ''));
          if (!isCurrent()) return null;
          if (!result || result.ok === false) fail(result?.error || 'Workshop history was refused.');
          if (result.graph_id !== stamp.graph || result.root !== root || result.scope_root !== stamp.scope ||
              !revision(result.revision) || result.revision < canvas.revision ||
              (previous && result.revision < previous.revision)) fail('Workshop history is stale or belongs to another scope.');
          const content = result.storage === 'conversation-content';
          const modelAgent = result.model_agent ?? null;
          if (modelAgent !== null && (!text(modelAgent.root) || modelAgent.root.length > 512 ||
              !text(modelAgent.model) || modelAgent.model.length > 512 ||
              !/^[a-f0-9]{64}$/.test(modelAgent.binding_digest))) fail('The conversation model binding is invalid.');
          const modelChanged = JSON.stringify(previous?.model_agent ?? null) !== JSON.stringify(modelAgent);
          if (content && (!text(result.content_cursor) || result.page_before !== before || (result.feed || 'all') !== feed)) {
            fail('Workshop history returned an invalid page.');
          }
          if (result.unchanged) {
            if (!previous || (!content && result.revision !== previous.revision) || content !== ordinary ||
                (content && (result.content_cursor !== previous.content_cursor ||
                  result.page_before !== previous.page_before))) fail('Workshop history needs a full refresh.');
            if (result.participants !== undefined) {
              if (!Array.isArray(result.participants) || result.participants.some(row =>
                  !row || !text(row.root) || typeof row.label !== 'string' || typeof row.attached !== 'boolean')) {
                fail('Workshop participant status is invalid.');
              }
              if (JSON.stringify(previous.participants) === JSON.stringify(result.participants) &&
                  result.revision === previous.revision && !modelChanged) return previous;
              workshop = {...previous, revision:result.revision, participants:result.participants,
                model_agent:modelAgent}; publish(); return workshop;
            }
            if (result.revision !== previous.revision || modelChanged) {
              workshop = {...previous, revision:result.revision, model_agent:modelAgent}; publish(); return workshop;
            }
            return previous;
          }
          if (!Array.isArray(result.messages) || !Array.isArray(result.participants) ||
              result.messages.length > 100 || (!content && before !== null)) fail('Workshop history is invalid.');
          if (content && ((!text(result.next_before) && result.next_before !== null) ||
              (result.next_before !== null && result.next_before === before) ||
              typeof result.has_older !== 'boolean' || result.has_older !== (result.next_before !== null) ||
              !revision(result.total) || result.total < result.messages.length ||
              result.messages.some((row, index, rows) => !row || !text(row.root) ||
                typeof row.body !== 'string' || !Number.isSafeInteger(row.sequence) || row.sequence < 1 ||
                (index > 0 && row.sequence <= rows[index - 1].sequence)) ||
              new Set(result.messages.map(row => row.root)).size !== result.messages.length)) {
            fail('Workshop history is invalid.');
          }
          if (content) pageTarget = {...pageTarget, storage:'conversation-content'};
          workshop = {...result, model_agent:modelAgent, error:''}; publish(); return workshop;
        } catch (error) {
          if (!isCurrent()) return null;
          workshop = {root, scope_root:stamp.scope, messages:[], participants:[],
            ...(ordinary || before !== null || contentKnown ?
              {storage:'conversation-content', page_before:before, feed} : {}),
            error:error.message || String(error)};
          publish(); throw error;
        }
      })();
      reads.set(key, operation);
      try { return await operation; } finally { if (reads.get(key) === operation) reads.delete(key); }
    }
    async function readConversationCatalog(root, after = null) {
      const stamp = stampFor(root);
      if (after !== null && (!text(after) || after.length > 4096)) fail('The conversation catalog position is invalid.');
      if (!conversationCatalogPage || conversationCatalogPage.root !== root || conversationCatalogPage.after !== after) {
        conversationCatalogPage = {root, after}; catalogEpoch += 1;
        conversationCatalog = null; publish();
      }
      const pageStamp = catalogEpoch;
      const isCurrent = () => current(stamp, root) && pageStamp === catalogEpoch &&
        conversationCatalogPage?.root === root && conversationCatalogPage.after === after;
      const key = JSON.stringify([stamp.epoch, stamp.membership, pageStamp, root, after]);
      if (catalogReads.has(key)) return catalogReads.get(key);
      const previous = conversationCatalog?.root === root && !conversationCatalog.error ? conversationCatalog : null;
      const operation = (async () => {
        try {
          const result = await get('/api/universal/workshop?root=' + encodeURIComponent(root) +
            '&scope=' + encodeURIComponent(stamp.scope) + '&catalog=1' +
            (after === null ? '' : '&after=' + encodeURIComponent(after)));
          if (!isCurrent()) return null;
          if (!result || result.ok !== true) fail(result?.error || 'The conversation catalog was refused.');
          if (result.graph_id !== stamp.graph || result.root !== root || result.scope_root !== stamp.scope ||
              !text(result.workbench_root) || !revision(result.revision) || result.revision < canvas.revision ||
              (previous && result.revision < previous.revision)) fail('The conversation catalog is stale or belongs to another scope.');
          if (!Array.isArray(result.conversations) || result.conversations.length > 50 ||
              result.conversations.some(row => !row || !text(row.root) || row.root.length > 512 ||
                !text(row.title) || new TextEncoder().encode(row.title).byteLength > 512 ||
                typeof row.is_general !== 'boolean' || !Array.isArray(row.participant_roots) ||
                row.participant_roots.length > 1024 || !row.participant_roots.length ||
                row.participant_roots.some(value => !text(value) || value.length > 512) ||
                new Set(row.participant_roots).size !== row.participant_roots.length) ||
              new Set(result.conversations.map(row => row.root)).size !== result.conversations.length ||
              typeof result.has_more !== 'boolean' ||
              (result.next_after !== null && (!text(result.next_after) || result.next_after.length > 4096 || result.next_after === after)) ||
              result.has_more !== (result.next_after !== null)) fail('The conversation catalog page is invalid.');
          if (['owner', 'view', 'self', 'can_create', 'participants'].some(field => result[field] !== undefined) &&
              (!text(result.owner) || !text(result.view) || !text(result.self) || typeof result.can_create !== 'boolean' ||
                !Array.isArray(result.participants) || result.participants.length > 1024 ||
                result.participants.some(row => !row || !text(row.root) || typeof row.label !== 'string' ||
                  typeof row.attached !== 'boolean') || new Set(result.participants.map(row => row.root)).size !== result.participants.length)) {
            fail('The conversation catalog participant authority is invalid.');
          }
          conversationCatalog = {...result, page_after:after, error:''}; publish(); return conversationCatalog;
        } catch (error) {
          if (!isCurrent()) return null;
          conversationCatalog = {root, graph_id:stamp.graph, scope_root:stamp.scope, page_after:after,
            conversations:[], has_more:false, next_after:null, error:error.message || String(error)};
          publish(); throw error;
        }
      })();
      catalogReads.set(key, operation);
      try { return await operation; } finally { if (catalogReads.get(key) === operation) catalogReads.delete(key); }
    }
    // Each mounted editor owns a separate ordinary page. Handles are document
    // local: never clone a tab's page identity from sessionStorage.
    const editorHandles = new WeakSet();
    const editorLabels = new Map();
    async function openConversationEditor(root, requestKey, kind = 'message') {
      let stamp = stampFor(root);
      if (!['message','work'].includes(kind)) fail('Unknown conversation editor.');
      if (!text(requestKey) || requestKey.length > 128) fail('Editor identity is invalid.');
      let page = null, queue = Promise.resolve(), uncertain = null, staged = false;
      const request = async (fields, requestStamp = stamp) => {
        if (!current(requestStamp, root)) fail('Return to this conversation to reconcile its draft.');
        const projection = await api.refreshWorkshop(root);
        if (!current(requestStamp, root) || !projection || projection.error || !revision(projection.revision) ||
            !text(projection.owner) || !text(projection.view)) {
          fail('Refresh this conversation before changing draft protection.');
        }
        const result = await post('/api/universal/workshop', {root, scope:stamp.scope,
          revision:projection.revision, ...fields});
        const row = result?.page;
        if (!result || result.ok !== true || result.refused === true || result.graph_id !== stamp.graph || result.root !== root ||
            result.scope_root !== stamp.scope || result.request_revision !== projection.revision ||
            !revision(result.revision) || result.revision < projection.revision ||
            !text(projection.owner) || !text(projection.view) ||
            result.owner !== projection.owner || result.view !== projection.view ||
            !row || !text(row.page_id) || !revision(row.page_revision) || row.page_revision < 1 ||
            (page && row.page_id !== page.page_id) || !['open','closed'].includes(row.state) ||
            !['unknown','dirty','clear'].includes(row.draft_state)) {
          fail('Draft protection could not be confirmed. Retry to reconcile it.');
        }
        if (fields.action === 'page-change' && (row.page_revision !== fields.page_revision + 1 ||
            (fields.change === 'close' ? row.state !== 'closed' : row.state !== 'open') ||
            (fields.change === 'dirty' && (row.draft_state !== 'dirty' || row.resolution_kind !== 'none')) ||
            (['initial-empty','saved'].includes(fields.change) &&
              (row.draft_state !== 'clear' || row.resolution_kind !== fields.change)))) {
          fail('Draft protection returned an unexpected transition. Retry to reconcile it.');
        }
        page = row;
        if (!current(requestStamp, root)) fail('Conversation changed; its draft remains protected.');
        return row;
      };
      page = await request({action:'page-open', request_key:requestKey});
      if (page.state !== 'open') fail('This editor was already closed. Reopen the conversation.');
      if (page.page_revision === 1) await request({action:'page-change', page_id:page.page_id,
        page_revision:1, change:'initial-empty'});
      const labelKey = JSON.stringify([stamp.graph, root, page.page_id]);
      editorLabels.set(labelKey, kind === 'message' ? 'Message editor in this window' : 'Repair editor in this window');
      if (editorLabels.size > 128) editorLabels.delete(editorLabels.keys().next().value);
      const serial = task => {
        const operation = queue.then(task);
        queue = operation.catch(() => {});
        return operation;
      };
      const apply = async fields => {
        uncertain = fields;
        const row = await request(fields);
        uncertain = null;
        if (fields.change === 'dirty') staged = fields.resolution_reference !== undefined;
        return row;
      };
      const change = (kind, reference) => serial(async () => {
        if (uncertain) fail('Retry the unresolved draft protection change first.');
        if (page.state !== 'open') fail('This editor is closed.');
        if (kind === 'dirty' && reference === undefined && page.draft_state === 'dirty' &&
            page.resolution_kind === 'none' && !staged) return page;
        const row = await apply({action:'page-change', page_id:page.page_id,
          page_revision:page.page_revision, change:kind,
          ...(reference === undefined ? {} : {resolution_reference:reference})});
        return row;
      });
      const handle = Object.freeze({root,
        dirty:() => change('dirty'),
        stageMessage:id => change('dirty', id),
        savedMessage:(messageId, expected) => serial(async () => {
          if (uncertain || page.state !== 'open' || page.page_revision !== expected.page_revision) {
            fail('Message saved; a newer or unresolved draft remains protected.');
          }
          return apply({action:'page-change', page_id:page.page_id, page_revision:page.page_revision,
            change:'saved', resolution_reference:messageId});
        }),
        close:() => change('close'),
        retry:() => serial(async () => {
          if (!current(stamp, root)) {
            const next = stampFor(root);
            if (next.graph !== stamp.graph || next.scope !== stamp.scope) {
              fail('Return to this conversation to reconcile its draft.');
            }
            // Re-admit this exact page through the server's five-root identity
            // check; a sibling canvas change must not strand its local draft.
            await request({action:'page-status', page_id:page.page_id}, next);
            stamp = next;
          }
          if (uncertain) await apply(uncertain);
          if (page.state !== 'open') fail('This editor was closed. Reopen the conversation.');
          return page;
        }),
      });
      editorHandles.add(handle);
      return handle;
    }
    const reviewedPages = new WeakMap();
    const reviewedConversations = new WeakMap();
    const ownerPageRequest = async (root, fields, stamp = stampFor(root)) => {
      if (!current(stamp, root)) fail('Conversation changed. Review its storage again.');
      const projection = await api.refreshWorkshop(root);
      if (!current(stamp, root) || !projection || projection.error || projection.can_manage_history !== true) {
        fail('Conversation storage review requires its admitted application owner.');
      }
      const result = await post('/api/universal/workshop', {root, scope:stamp.scope,
        revision:projection.revision, ...fields});
      if (!result || result.ok !== true || result.graph_id !== stamp.graph || result.root !== root ||
          result.scope_root !== stamp.scope || result.revision !== projection.revision ||
          !revision(result.activity_revision) || !result.protection ||
          !['unknown','ready'].includes(result.protection.tracking_state) ||
          typeof result.protection.protected !== 'boolean') {
          fail('Conversation storage response could not be reconciled. Refresh before continuing.');
        }
      if (!result.retention || ['activity_revision','archive_revision','last_sequence','content_generation'].some(
            field => !revision(result.retention[field])) || result.retention.activity_revision !== result.activity_revision ||
          ['last_activity_at','archived_at'].some(field => result.retention[field] !== null &&
            (!Number.isFinite(result.retention[field]) || result.retention[field] < 0 || result.retention[field] > 253402300799))) {
        fail('Conversation retention metadata is invalid.');
      }
      if (!current(stamp, root)) fail('Conversation changed. Review its storage again.');
      return result;
    };
    const api = {
      openConversationEditor,
      async startSession(details) {
        if (!details || typeof details.prompt !== 'string' || !details.prompt.trim() || details.prompt.length > 12000 ||
            (!!details.model === !!details.native) || details.model && !text(details.model) ||
            details.native && (!text(details.native.app) || !text(details.native.session_id))) {
          fail('Write a request and choose one agent or model.');
        }
        const viewIdentity = () => JSON.stringify([canvas?.graph_id,
          topologyCanvas?.authorization?.subject, topologyCanvas?.authorization?.session]);
        const identity = viewIdentity(), graph = canvas?.graph_id;
        if (!text(graph) || !text(topologyCanvas?.authorization?.subject) || !text(topologyCanvas?.authorization?.session)) {
          fail('Wait for the application connection before starting a session.');
        }
        const body = {action:'start-session',prompt:details.prompt.trim(),
          ...(details.native ? {native:{app:details.native.app,session_id:details.native.session_id}} : {model:details.model})};
        const pendingKey = await hash(JSON.stringify({kind:'start-session',identity,body}));
        if (!/^[a-f0-9]{64}$/.test(pendingKey) || viewIdentity() !== identity) fail('Your application connection changed.');
        if (sends.has(pendingKey)) return sends.get(pendingKey);
        const saved = records();
        if (!saved[pendingKey] && Object.keys(saved).length >= 32) fail('Reconcile pending operations before starting more sessions.');
        const id = saved[pendingKey] || uuid();
        if (!text(id) || id.length > 128) fail('Session request identity is invalid.');
        saved[pendingKey] = id; pendingStorage.setItem(storageName, JSON.stringify(saved));
        const operation = (async () => {
          const result = await post('/api/universal/workshop', {...body,idempotency_key:id});
          if (result?.ok !== true || !text(result.title) || result.graph_id !== graph || result.idempotency_key !== id ||
              !text(result.root) || !text(result.message_id) || !revision(result.revision) ||
              !Array.isArray(result.scope_path) || !result.scope_path.length || result.scope_path.some(root => !text(root))) {
            fail('Session creation is unconfirmed. Your request identity is retained; do not start a duplicate.');
          }
          let warning = '';
          const deliveryState = result.delivery?.state;
          const settled = details.native
            ? text(result.contact) && ['replied','started','delivered','received'].includes(deliveryState)
            : deliveryState === 'replied' && text(result.delivery.node) && text(result.delivery.reply_message_id);
          if (!settled) warning = deliveryState === 'not_sent' && result.delivery.provider_not_called === true
            ? 'Session saved. ' + (typeof result.delivery.message === 'string'
              ? result.delivery.message.slice(0,2000) : 'The model was not called. Check its connection before retrying.')
            : 'Session saved. The agent reply is not confirmed; review the delivery outcome before retrying.';
          try {
            const remaining = records();
            if (settled && remaining[pendingKey] === id) delete remaining[pendingKey];
            pendingStorage.setItem(storageName, JSON.stringify(remaining));
          } catch (_) { warning = [warning,'Session saved; pending request storage needs reconciliation.'].filter(Boolean).join(' '); }
          return {...result,accepted:true,warning,navigation_current:viewIdentity() === identity};
        })();
        sends.set(pendingKey, operation);
        try { return await operation; } finally { if (sends.get(pendingKey) === operation) sends.delete(pendingKey); }
      },
      async nativeAgents(root = null, apps = ['claude','codex','opencode','antigravity','antigravity-ide']) {
        const allowed = ['claude','codex','opencode','antigravity','antigravity-ide'];
        if (!Array.isArray(apps) || !apps.length || apps.length > 5 || apps.some(app => !allowed.includes(app))) {
          fail('Choose a supported agent environment.');
        }
        const stamp = root ? stampFor(root) : null;
        const query = new URLSearchParams({apps:apps.join(',')});
        if (stamp) { query.set('root', root); query.set('scope', stamp.scope); }
        const result = await get('/api/universal/native-agents?' + query);
        if (stamp && !current(stamp, root)) fail('The conversation changed during discovery.');
        if (!result || !['ok','unavailable'].includes(result.status) || !Array.isArray(result.rows) ||
            result.rows.length > 64 || result.rows.some(row => !allowed.includes(row.app) ||
              !text(row.session_id) || typeof row.title !== 'string' || typeof row.connected !== 'boolean')) {
          fail('Native agent discovery returned an invalid result.');
        }
        return result;
      },
      async bindNativeContact(selection, node = null) {
        if (!selection || !text(selection.app) || !text(selection.session_id) || node !== null && !text(node)) {
          fail('Choose one live native session.');
        }
        const viewIdentity = () => JSON.stringify([canvas?.graph_id, canvas?.root,
          (topologyCanvas || canvas)?.authorization?.subject, (topologyCanvas || canvas)?.authorization?.session]);
        const identity = viewIdentity();
        const fresh = await api.nativeAgents(null, [selection.app]);
        const matches = fresh.rows.filter(row => row.app === selection.app && row.session_id === selection.session_id);
        if (fresh.status !== 'ok' || matches.length !== 1 || !matches[0].connected || matches[0].selectable === false) {
          fail('That native session is no longer uniquely available. Refresh the agent list.');
        }
        if (!text(fresh.workshop?.root) || !text(fresh.workshop?.scope) || !revision(fresh.revision)) {
          fail('The application did not return its Workshop connection.');
        }
        if (identity !== viewIdentity()) fail('The graph changed before connecting.');
        const result = await post('/api/universal/native-contact', {action:'bind',
          root:fresh.workshop.root, scope:fresh.workshop.scope, node,
          app:selection.app, session_id:selection.session_id, revision:fresh.revision});
        if (!result?.ok || !text(result.contact) || !/^[a-f0-9]{64}$/.test(result.binding_digest) ||
            result.app !== selection.app || result.session_id !== selection.session_id ||
            result.root !== fresh.workshop.root || result.scope !== fresh.workshop.scope || !revision(result.revision)) {
          fail('The connection result is unconfirmed. Inspect the graph before connecting again.');
        }
        // Keep the accepted receipt even when the user has moved to another view.
        return {...result, navigation_current:identity === viewIdentity()};
      },
      async sendNativeContact(root, contact, message, editor = null) {
        const stamp = stampFor(root), held = workshop;
        if (!held || held.root !== root || held.error || !text(held.owner) || !text(held.view) || held.can_send !== true ||
            !contact || !text(contact.root) || !/^[a-f0-9]{64}$/.test(contact.binding_digest) ||
            !text(message?.trim()) || message.length > 12000) fail('Refresh the conversation and its connected agent before sending.');
        if (editor && (!editorHandles.has(editor) || editor.root !== root)) fail('Message editor belongs to another conversation.');
        const body = {action:'send', root, scope:stamp.scope, contact:contact.root,
          binding_digest:contact.binding_digest, text:message.trim()};
        const pendingKey = await hash(JSON.stringify({graph:stamp.graph, owner:held.owner, view:held.view, body}));
        if (!/^[a-f0-9]{64}$/.test(pendingKey) || !current(stamp, root) || workshop !== held) {
          fail('The conversation changed before sending.');
        }
        if (sends.has(pendingKey)) return sends.get(pendingKey);
        const saved = records();
        if (!saved[pendingKey] && Object.keys(saved).length >= 32) fail('Reconcile pending messages before sending more.');
        const id = saved[pendingKey] || uuid();
        if (!text(id) || id.length > 128) fail('Message identity is invalid.');
        saved[pendingKey] = id; pendingStorage.setItem(storageName, JSON.stringify(saved));
        const operation = (async () => {
          const staged = editor ? await editor.stageMessage(id) : null;
          if (!current(stamp, root)) fail('The conversation changed before sending.');
          const result = await post('/api/universal/native-contact', {...body,idempotency_key:id});
          if (!result?.ok || result.root !== root || result.contact !== contact.root ||
              !text(result.message_id) || result.idempotency_key !== id || !revision(result.revision)) {
            fail('The message result is unconfirmed. Its pending identity has been retained.');
          }
          let warning = '';
          if (editor) {
            try { await editor.savedMessage(result.message_id, staged); }
            catch (_) { warning = 'Message saved; draft protection needs reconciliation.'; }
          }
          try {
            const remaining = records();
            if (remaining[pendingKey] === id) delete remaining[pendingKey];
            pendingStorage.setItem(storageName, JSON.stringify(remaining));
          } catch (_) { warning = 'Message saved; pending recovery could not be updated.'; }
          workshopNotice = warning || (result.delivery?.state === 'started'
            ? 'Message saved and delivery started. The agent reply will appear here.'
            : 'Message saved. Check its delivery outcome in this conversation.');
          if (current(stamp, root)) await api.refreshWorkshop(root).catch(() => {});
          publish();
          return {...result,accepted:true};
        })();
        sends.set(pendingKey, operation);
        try { return await operation; } finally { if (sends.get(pendingKey) === operation) sends.delete(pendingKey); }
      },
      async sendModelConversation(root, agent, message, editor = null) {
        const stamp = stampFor(root), held = workshop;
        if (!held || held.root !== root || held.error || !text(held.owner) || !text(held.view) || held.can_send !== true ||
            !agent || !text(agent.root) || !text(agent.model) || !/^[a-f0-9]{64}$/.test(agent.binding_digest) ||
            held.model_agent?.root !== agent.root || held.model_agent.model !== agent.model ||
            held.model_agent.binding_digest !== agent.binding_digest || !text(message?.trim()) || message.length > 12000) {
          fail('Refresh this conversation and its model node before sending.');
        }
        if (editor && (!editorHandles.has(editor) || editor.root !== root)) fail('Message editor belongs to another conversation.');
        const body = {action:'send-model', root, scope:stamp.scope, node:agent.root,
          binding_digest:agent.binding_digest, prompt:message.trim()};
        const pendingKey = await hash(JSON.stringify({graph:stamp.graph, owner:held.owner, view:held.view, body}));
        if (!/^[a-f0-9]{64}$/.test(pendingKey) || !current(stamp, root) || workshop !== held) fail('The conversation changed before sending.');
        if (sends.has(pendingKey)) return sends.get(pendingKey);
        const saved = records();
        if (!saved[pendingKey] && Object.keys(saved).length >= 32) fail('Reconcile pending messages before sending more.');
        const id = saved[pendingKey] || uuid();
        if (!text(id) || id.length > 128) fail('Message identity is invalid.');
        saved[pendingKey] = id; pendingStorage.setItem(storageName, JSON.stringify(saved));
        const operation = (async () => {
          const staged = editor ? await editor.stageMessage(id) : null;
          if (!current(stamp, root)) fail('The conversation changed before sending.');
          const result = await post('/api/universal/workshop', {...body,idempotency_key:id});
          if (result?.ok !== true || result.graph_id !== stamp.graph || result.root !== root ||
              result.scope_root !== stamp.scope || result.node !== agent.root || result.binding_digest !== agent.binding_digest ||
              !text(result.message_id) || result.idempotency_key !== id || !revision(result.revision) ||
              !['replied','not_sent','failed','already_recorded','unknown'].includes(result.delivery?.state) ||
              (result.delivery.state === 'replied' && !text(result.delivery.reply_message_id))) {
            fail('The model result is unconfirmed. Its pending identity is retained.');
          }
          if (result.delivery.state !== 'replied') {
            if (current(stamp, root)) await api.refreshWorkshop(root).catch(() => {});
            fail(result.delivery.state === 'not_sent' && result.delivery.provider_not_called === true
              ? (result.delivery.message || 'Your message is saved. The model was not called; resolve its connection and retry.')
              : 'Your message is saved, but no model reply is confirmed. Retry only to reconcile this same request.');
          }
          let warning = '';
          if (editor) {
            try { await editor.savedMessage(result.message_id, staged); }
            catch (_) { warning = 'Reply saved; draft protection needs reconciliation.'; }
          }
          try {
            const remaining = records();
            if (remaining[pendingKey] === id) delete remaining[pendingKey];
            pendingStorage.setItem(storageName, JSON.stringify(remaining));
          } catch (_) { warning = 'Reply saved; pending recovery could not be updated.'; }
          if (current(stamp, root)) {
            workshopNotice = warning;
            await api.refreshWorkshop(root).catch(() => {}); publish();
          }
          return {...result,accepted:true,warning};
        })();
        sends.set(pendingKey, operation);
        try { return await operation; } finally { if (sends.get(pendingKey) === operation) sends.delete(pendingKey); }
      },
      async reviewConversationPages(root, after = null) {
        const stamp = stampFor(root);
        if (after !== null && (!text(after) || after.length > 512)) fail('Storage review cursor is invalid.');
        const result = await ownerPageRequest(root, {action:'page-owner-review', limit:50,
          ...(after === null ? {} : {after_page_id:after})}, stamp);
        const identityFields = ['session_root','subject_root','view_root','tenant_root','assurance_root'];
        if (!Array.isArray(result.pages) || result.pages.length > 50 || result.pages.some((row,index,rows) =>
            !row || !text(row.page_id) || row.page_id.length > 512 || !revision(row.page_revision) || row.page_revision < 1 ||
            !['open','closed'].includes(row.state) || !['unknown','dirty','clear'].includes(row.draft_state) ||
            typeof row.resolution_kind !== 'string' || identityFields.some(field => !text(row[field])) ||
            Object.keys(row).some(field => !['page_id','page_revision','state','draft_state','resolution_kind',
              'opened_at','changed_at',...identityFields].includes(field)) ||
            !Number.isFinite(row.opened_at) || row.opened_at < 0 ||
            !Number.isFinite(row.changed_at) || row.changed_at < row.opened_at || row.changed_at > 253402300799 ||
            (row.state === 'closed' && row.draft_state === 'clear') ||
            (index > 0 && row.page_id <= rows[index-1].page_id) || (after !== null && row.page_id <= after)) ||
            result.next_page_id !== null && (result.pages.length === 0 ||
              result.next_page_id !== result.pages[result.pages.length-1].page_id)) {
          fail('Protected editor metadata is invalid.');
        }
        const pages = result.pages.map(row => {
          const copy = Object.freeze({...row, editor_label:editorLabels.get(JSON.stringify([stamp.graph,root,row.page_id])) ||
            'Earlier browser editor'}); reviewedPages.set(copy, {stamp, root}); return copy;
        });
        const review = Object.freeze({...result, pages:Object.freeze(pages),
          retention:Object.freeze({...result.retention}), protection:Object.freeze({...result.protection})});
        reviewedConversations.set(review, {stamp, root});
        return review;
      },
      async resolveConversationTracking(root, review) {
        const held = reviewedConversations.get(review);
        if (!held || held.root !== root || review.protection.tracking_state !== 'unknown') {
          fail('Review the earlier conversation activity before resolving it.');
        }
        const result = await ownerPageRequest(root, {action:'page-tracking-resolve',
          activity_revision:review.activity_revision, disposition:'discard-untracked-drafts'}, held.stamp);
        if (result.protection.tracking_state !== 'ready') fail('Earlier activity resolution is not confirmed.');
        reviewedConversations.delete(review);
        return result;
      },
      async archiveConversation(root, review) {
        const held = reviewedConversations.get(review);
        if (!held || held.root !== root || review.protection.protected !== false || review.retention.archived_at !== null) {
          fail('Review and resolve conversation protection before archiving.');
        }
        const status = review.retention;
        const result = await ownerPageRequest(root, {action:'conversation-archive',
          activity_revision:status.activity_revision, archive_revision:status.archive_revision,
          head:status.last_sequence, content_generation:status.content_generation}, held.stamp);
        if (result.retention.archived_at === null || result.retention.last_sequence !== status.last_sequence ||
            result.retention.content_generation !== status.content_generation) fail('Conversation archive is not confirmed.');
        reviewedConversations.delete(review);
        return result;
      },
      async discardConversationPage(root, page) {
        const held = reviewedPages.get(page);
        if (!held || held.root !== root) fail('Review this protected editor before releasing it.');
        const result = await ownerPageRequest(root, {action:'page-owner-discard', page_id:page.page_id,
          page_revision:page.page_revision}, held.stamp);
        if (!result.page || result.page.page_id !== page.page_id || result.page.page_revision !== page.page_revision + 1 ||
            result.page.state !== 'closed' || result.page.draft_state !== 'clear' || result.page.resolution_kind !== 'owner-discard') {
          fail('Editor release is not confirmed. Refresh its metadata before retrying.');
        }
        reviewedPages.delete(page);
        return result;
      },
      getSnapshot: () => snapshot,
      setThemeCanvas(value) {
        try { themeError = ''; return acceptTheme(value); }
        catch (error) { themeCanvas = null; themeError = error.message; publish(); return null; }
      },
      async refreshTheme() {
        if (themeWrite) fail('Wait for the current theme save to finish.');
        themeError = '';
        try { return acceptTheme(await get('/api/universal/canvas')); }
        catch (error) { themeCanvas = null; themeError = error.message; publish(); throw error; }
      },
      previewThemeToken: (key, value) => changeTheme('preview', key, value),
      restoreThemeRevision: root => changeTheme('restore', root),
      setBaboomStartup: value => changeTheme('baboom-startup', null, value),
      setComposerModel: value => changeTheme('composer-model', null, value),
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      readProviders() {
        if (providerRead) return providerRead;
        providerRead = Promise.resolve().then(() => get('/api/universal/providers')).then(result => {
          if (!result || result.ok !== true || !Array.isArray(result.providers)) fail('Provider status could not be read.');
          return result.providers;
        }).finally(() => { providerRead = null; });
        return providerRead;
      },
      async saveProviderKey(provider, key) {
        if (providerSave) fail('Wait for the current key save to finish.');
        if (provider !== 'openrouter' || typeof key !== 'string' || !key.trim() || key.length > 8192) {
          fail('Enter a raw OpenRouter API key.');
        }
        // The raw key travels only in this authenticated request; never publish it.
        const operation = (async () => {
          if (providerRead) await providerRead.catch(() => {});
          try {
            const result = await post('/api/universal/provider-key', {provider, key});
            if (!result || result.ok !== true || result.provider !== provider || result.state !== 'keyed' ||
                result.source !== 'secrets store') fail('The provider key save could not be confirmed.');
            return {ok:true, provider, state:'keyed', source:'secrets store'};
          } catch (error) {
            const message = String(error?.message || 'The provider key could not be saved.');
            throw new Error(message.split(key).join('[redacted]').split(key.trim()).join('[redacted]').slice(0, 1000));
          }
        })();
        providerSave = operation;
        try { return await operation; } finally { providerSave = null; }
      },
      async enrollSocialAccount({provider, account_id, vault_entry, token}) {
        if (providerSave) fail('Wait for the current credential save to finish.');
        if (!['linkedin', 'meta'].includes(provider) || !text(account_id) || account_id.length > 256 ||
            typeof vault_entry !== 'string' || !/^social-[A-Za-z0-9._-]+$/.test(vault_entry) || vault_entry.length > 128 ||
            typeof token !== 'string' || !token || token.length > 16384) {
          fail('Enter a social- reference, provider account ID and access token.');
        }
        const operation = Promise.resolve().then(async () => {
          try {
            const result = await post('/api/universal/social-credential', {provider, account_id, vault_entry, token});
            if (result?.ok !== true || result.state !== 'enrolled' || result.provider !== provider ||
                result.account_id !== account_id || result.vault_entry !== vault_entry ||
                result.account_binding !== 'operator-declared' ||
                result.vault_reference !== 'dpapi://ArchHub/' + vault_entry || !revision(result.revision)) {
              fail('Social account enrollment could not be confirmed.');
            }
            // Never publish credentials or retain an arbitrary response payload.
            return {ok:true, provider, account_id, vault_entry, state:'enrolled',
              account_binding:'operator-declared', vault_reference:result.vault_reference};
          } catch (_) {
            throw new Error('Social account save could not be confirmed. The credential may be saved; review its reference before retrying.');
          }
        });
        providerSave = operation;
        try { return await operation; } finally { providerSave = null; token = ''; }
      },
      async removeLocalSocialAccount({provider, account_id, vault_entry}) {
        if (providerSave) fail('Wait for the current credential change to finish.');
        if (!['linkedin', 'meta'].includes(provider) || !text(account_id) || account_id.length > 256 ||
            typeof vault_entry !== 'string' || !/^social-[A-Za-z0-9._-]+$/.test(vault_entry) || vault_entry.length > 128) {
          fail('Enter the social- reference and its exact provider account ID.');
        }
        const operation = Promise.resolve().then(async () => {
          try {
            const result = await post('/api/universal/social-credential-remove', {provider, account_id, vault_entry});
            if (result?.ok !== true || !['removed', 'absent'].includes(result.state) ||
                result.provider !== provider || result.account_id !== account_id || result.vault_entry !== vault_entry ||
                result.provider_token_revoked !== false || typeof result.graph_reference_retained !== 'boolean' ||
                !revision(result.revision)) fail('Local credential removal could not be confirmed.');
            return {ok:true, provider, account_id, vault_entry, state:result.state,
              provider_token_revoked:false, graph_reference_retained:result.graph_reference_retained};
          } catch (_) {
            throw new Error('Local credential removal could not be confirmed. Check the saved account before retrying.');
          }
        });
        providerSave = operation;
        try { return await operation; } finally { providerSave = null; }
      },
      setTopologyCanvas: acceptTopology,
      selectTopology(root) {
        return runTopology(JSON.stringify(['select', root]), async (identity, command) => {
          const value = await readTopology(identity);
          // Work the canvas does not draw is still selectable for its Workshop review.
          const hiddenWork = Array.isArray(value.hidden_work) ? value.hidden_work : [];
          if (!text(root) || ![...value.nodes, ...value.wires, ...hiddenWork].some(row => row?.id === root)) {
            fail('Choose a node in the current canvas scope.');
          }
          if (value.selected === root) return value;
          const result = await command('/api/universal/gesture', {
            roots:[root], focus:root, expected_scope:value.scope.current,
          });
          if (!result || topologyIdentity(result) !== identity || result.selected !== root ||
              !revision(result.revision) || result.revision < value.revision ||
              topologyIdentity(topologyCanvas) !== identity) {
            fail('The selected node needs reconciliation in its original canvas.');
          }
          return acceptTopology(result);
        });
      },
      moveTopologyNodes(positions, expectedRevision = topologyCanvas?.revision, expectedPositions = null) {
        const copy = Object.fromEntries(Object.entries(positions || {}).map(([root, point]) => [root, {x:point?.x, y:point?.y}]));
        const roots = Object.keys(copy);
        const bases = Object.fromEntries(Object.entries(expectedPositions ?? Object.fromEntries(roots.map(root => {
          const node = topologyCanvas?.nodes.find(node => node.id === root);
          return [root, {x:node?.x, y:node?.y}];
        }))).map(([root, point]) => [root, {x:point?.x, y:point?.y}]));
        if (!roots.length || roots.some(root => !text(root) || !Number.isFinite(copy[root].x) || !Number.isFinite(copy[root].y))) {
          fail('Choose nodes with valid canvas positions.');
        }
        return runTopology(JSON.stringify(['positions', copy, bases]), async (identity, command) => {
          // The canvas the drag started from is the one the owner checks the save
          // against: it carries expected_positions and the scope, and the owner
          // refuses under its lock if either moved. Re-reading the whole canvas
          // first only asked again what the write itself answers.
          const value = topologyCanvas;
          if (!value || topologyIdentity(value) !== identity) fail('The canvas scope changed. Choose the node again.');
          if (!revision(expectedRevision) || value.revision < expectedRevision) fail('The layout revision is invalid. Refresh the canvas.');
          if (roots.some(root => !value.nodes.some(node => node.id === root))) fail('A moved node is no longer on this canvas.');
          if (roots.length > 256 || Object.keys(bases).length !== roots.length || roots.some(root => {
            const node = value.nodes.find(node => node.id === root), base = bases[root];
            return !Number.isFinite(base?.x) || !Number.isFinite(base?.y) || node.x !== base.x || node.y !== base.y;
          })) fail('A moved node changed position. Refresh before arranging it again.');
          const result = await command('/api/universal/gesture', {
            expected_scope:value.scope.current, positions:copy, expected_positions:bases,
            projection_mode:'receipt-v1', projection_revision:value.revision,
          });
          if (!result || result.ok !== true || result.projection_mode !== 'receipt-v1' ||
              !revision(result.base_revision) || result.base_revision < value.revision || !revision(result.committed_revision) ||
              result.committed_revision < result.base_revision) fail('The layout save needs reconciliation.');
          acceptTopologyLayout(identity, copy, result.committed_revision);
          return result;
        });
      },
      refreshTopologyCanvas() {
        if (topologyWrite) return topologyWrite.promise;
        if (topologyRead) return topologyRead;
        topologyPending = true; topologyError = ''; publish();
        const operation = Promise.resolve().then(() => readTopology()).then(value => {
          topologyRequiresRefresh = false; return value;
        }).catch(error => {
          topologyError = error.message || 'The canvas could not be refreshed.';
          topologyRequiresRefresh = true; throw error;
        }).finally(() => { topologyRead = null; topologyPending = !!topologyWrite; publish(); });
        topologyRead = operation; return operation;
      },
      connectTopology(source, sourcePort, target, targetPort) {
        return runTopology(JSON.stringify(['connect', source, sourcePort, target, targetPort]), async (identity, command) => {
          if (![source, sourcePort, target, targetPort].every(text) || source === target) fail('Choose distinct nodes and their declared ports.');
          const value = await readTopology(identity);
          const output = value.nodes.find(node => node.id === source)?.ports?.find(port => port.id === sourcePort);
          const input = value.nodes.find(node => node.id === target)?.ports?.find(port => port.id === targetPort);
          if (!output || !input || output.side !== 'source' || input.side !== 'target' ||
              output.connectable !== true || input.connectable !== true || output.mode !== 'connection' || input.mode !== 'connection') {
            fail('Choose an admitted output and input connection port.');
          }
          const choices = output.connect_choices;
          if (!Array.isArray(choices)) fail('The output has no admitted connection choices.');
          const index = choices.findIndex(choice => choice.id === targetPort && choice.owner === target);
          if (index < 0 || choices.filter(choice => choice.id === targetPort && choice.owner === target).length !== 1) {
            fail('That input is not a current compatible connection choice.');
          }
          const body = topologyBinding(value, output.connect_control, [{input:output.connect_event_fact_input, value:index}]);
          const result = await command('/api/universal/interaction', body);
          if (!result || result.ok === false || result.projection_mode !== 'receipt-v1' ||
              result.base_revision !== value.revision || !revision(result.committed_revision) ||
              result.committed_revision <= value.revision || !text(result.created_root)) fail('The created connection needs reconciliation.');
          const latest = await readTopology(identity);
          if (latest.revision < result.committed_revision || !latest.wires.some(wire => wire.id === result.created_root &&
              wire.source === source && wire.source_interface === sourcePort && wire.target === target && wire.target_interface === targetPort)) {
            fail('The created connection is not visible in the refreshed graph.');
          }
          return result;
        });
      },
      disconnectTopology(root) {
        return runTopology(JSON.stringify(['disconnect', root]), async (identity, command) => {
          if (!text(root) || !topologyCanvas.wires.some(wire => wire.id === root && wire.nary === false)) {
            fail('Choose a binary connection on this canvas.');
          }
          const selected = acceptTopology(await command('/api/universal/select', {roots:[], focus:root}));
          if (topologyIdentity(selected) !== identity || selected.selected !== root) fail('The selected connection scope changed.');
          const wires = selected.wires.filter(wire => wire.id === root && wire.nary === false && wire.selected === true);
          if (wires.length !== 1) fail('The selected connection is no longer available.');
          const body = topologyBinding(selected, wires[0].disconnect_control);
          const result = await command('/api/universal/interaction', body);
          if (!result || result.ok === false || result.projection_mode !== 'receipt-v1' ||
              result.base_revision !== selected.revision || !revision(result.committed_revision) ||
              result.committed_revision <= selected.revision) fail('Connection removal needs reconciliation.');
          const latest = await readTopology(identity);
          if (latest.revision < result.committed_revision || latest.wires.some(wire => wire.id === root)) {
            fail('The removed connection remains in the refreshed graph.');
          }
          return result;
        });
      },
      watchApplicationUpdate() {
        updateWatchers += 1;
        if (updateWatchers === 1) {
          global.document?.addEventListener('visibilitychange', updateVisibility);
          updateVisibility();
        }
        let stopped = false;
        return () => {
          if (stopped) return;
          stopped = true; updateWatchers -= 1;
          if (!updateWatchers) {
            global.document?.removeEventListener('visibilitychange', updateVisibility);
            scheduleUpdateRead();
          }
        };
      },
      async refreshApplicationUpdate() {
        if (updateWrite) return updateWrite.promise;
        if (updateRead?.epoch === updateEpoch) return updateRead.promise;
        const stamp = updateEpoch, count = updateReads += 1;
        applicationUpdatePending = 'read'; publish();
        let timeout = null, abandoned = false;
        const reading = Promise.resolve().then(() => get('/api/universal/application-update'));
        // An answer that arrives after the read was abandoned still applies while no newer read or update
        // request has started, so a slow first read never loses the one-time update confirmation.
        reading.then(result => {
          if (!abandoned || stamp !== updateEpoch || count !== updateReads || updateWrite) return;
          acceptUpdate(result); scheduleUpdateRead();
        }).catch(() => {});
        const operation = (async () => {
          try {
            // A read that never answers must not hold back the next one, such as the desktop push.
            const result = await Promise.race([reading,
              new Promise((_, reject) => { timeout = global.setTimeout?.(() => { abandoned = true; reject(new Error(
                'Update status did not answer within 15 seconds. Use Read status to reconnect.')); }, 15000); })]);
            return stamp === updateEpoch ? acceptUpdate(result) : applicationUpdate;
          } catch (error) {
            if (stamp === updateEpoch) {
              applicationUpdateError = (error.message || 'Update status could not be read. Use Read status to reconnect.').slice(0, 4096);
              publish();
            }
            throw error;
          } finally {
            if (timeout != null) global.clearTimeout(timeout);
            if (stamp === updateEpoch) {
              updateRead = null; applicationUpdatePending = ''; publish(); scheduleUpdateRead();
            }
          }
        })();
        updateRead = {epoch:stamp, promise:operation};
        return operation;
      },
      async applicationUpdateAction(action) {
        if (!['check', 'reload', 'acknowledge'].includes(action)) fail('Unknown application update action.');
        if (updateWrite) {
          if (updateWrite.action === action) return updateWrite.promise;
          fail('Wait for the current update request to finish.');
        }
        if (action === 'reload' && (applicationUpdateError || applicationUpdate?.state !== 'ready' ||
            applicationUpdate.restart_supported !== true)) fail('A downloaded update and desktop restart support are required.');
        if (action === 'check' && updateActive()) fail('An application update is already in progress.');
        if (action === 'acknowledge' && (applicationUpdateError || !applicationUpdate?.updated_to)) {
          fail('No update confirmation is waiting.');
        }
        updateEpoch += 1;
        applicationUpdateError = ''; applicationUpdatePending = action; publish();
        if (updateTimer !== null) global.clearTimeout(updateTimer);
        updateTimer = null;
        const operation = (async () => {
          try { return acceptUpdate(await Promise.resolve().then(() => post('/api/universal/application-update', {action}))); }
          catch (error) {
            applicationUpdateError = ((error.message || 'The update request could not be confirmed.') +
              ' Read status before trying again.').slice(0, 4096);
            publish(); throw error;
          } finally {
            updateWrite = null; applicationUpdatePending = ''; publish(); scheduleUpdateRead();
          }
        })();
        updateWrite = {action, promise:operation};
        return operation;
      },
      setCanvas(value) {
        if (!value || !text(value.graph_id) || !text(value.root) || !revision(value.revision) ||
            !Array.isArray(value.workshops) || value.workshops.some(row => !row || !text(row.root) || !text(row.label)) ||
            new Set(value.workshops.map(row => row.root)).size !== value.workshops.length) {
          fail('The runtime did not return a valid Workshop scope.');
        }
        if (canvas && value.graph_id === canvas.graph_id && value.revision < canvas.revision) {
          fail('The Workshop scope is stale.');
        }
        const scopeChanged = !canvas || value.graph_id !== canvas.graph_id || value.root !== canvas.root;
        if (workshops.some(row => !value.workshops.some(next => next.root === row.root))) membershipEpoch += 1;
        if (scopeChanged || (conversationCatalogPage && !value.workshops.some(row => row.root === conversationCatalogPage.root)) ||
            value.revision > (conversationCatalog?.revision ?? canvas?.revision ?? -1)) {
          conversationCatalog = null; conversationCatalogPage = null; catalogEpoch += 1;
        }
        if (scopeChanged || (conversationCreation && !value.workshops.some(row => row.root === conversationCreation.anchor_root))) {
          conversationCreation = null;
        }
        if (scopeChanged) {
          epoch += 1; workshop = null; nativeWork = null;
          pageTarget = null; pageEpoch += 1;
        } else if ((pageTarget && !value.workshops.some(row => row.root === pageTarget.root)) ||
            value.revision > (workshop?.revision ?? canvas.revision)) {
          workshop = null;
          pageTarget = pageTarget && value.workshops.some(row => row.root === pageTarget.root)
            ? {...pageTarget} : null;
          pageEpoch += 1;
        }
        canvas = {graph_id:value.graph_id, root:value.root, revision:value.revision};
        workshops = value.workshops.map(row => ({...row}));
        if (workshop && !workshops.some(row => row.root === workshop.root)) { epoch += 1; workshop = null; }
        publish();
      },
      refreshWorkshop: root => readWorkshop(root, pageTarget?.root === root ? pageTarget.before : null),
      async loadOlderWorkshop(root) {
        if (workshop?.root !== root || workshop.error || workshop.storage !== 'conversation-content' ||
            !text(workshop.next_before)) fail('No older Workshop page is available.');
        return readWorkshop(root, workshop.next_before);
      },
      showLatestWorkshop: root => readWorkshop(root, null),
      showWorkshopFeed: (root, feed) => readWorkshop(root, null, feed, true),
      refreshConversationCatalog: root => readConversationCatalog(root,
        conversationCatalogPage?.root === root ? conversationCatalogPage.after : null),
      async loadNextConversationPage(root) {
        if (conversationCatalog?.root !== root || conversationCatalog.error || !text(conversationCatalog.next_after)) {
          fail('No next conversation catalog page is available.');
        }
        return readConversationCatalog(root, conversationCatalog.next_after);
      },
      showFirstConversationPage: root => readConversationCatalog(root, null),
      async createConversation(root, details = {}) {
        const stamp = stampFor(root);
        const fromCatalog = conversationCatalog?.root === root && !conversationCatalog.error &&
          typeof conversationCatalog.can_create === 'boolean';
        const held = fromCatalog ? conversationCatalog : workshop;
        const heldCurrent = () => (fromCatalog ? conversationCatalog : workshop) === held;
        if (!held || held.root !== root || held.error || !text(held.owner) || !text(held.view) ||
            !revision(held.revision) || held.revision < canvas.revision || !Array.isArray(held.participants)) {
          fail('Read the current Workshop and its participants before creating a conversation.');
        }
        if (fromCatalog && held.can_create !== true) fail('This catalog does not admit conversation creation for the current user.');
        if (!details || typeof details !== 'object' || Array.isArray(details) ||
            Object.keys(details).some(key => !['title', 'participant_roots'].includes(key))) {
          fail('Conversation creation accepts a title and admitted participants only.');
        }
        const title = typeof details.title === 'string' ? details.title.trim() : '';
        const participants = Array.isArray(details.participant_roots) ? [...details.participant_roots] : [];
        if (!title || title.includes('\0') || new TextEncoder().encode(title).byteLength > 512 ||
            !participants.length || participants.length > 64 || new Set(participants).size !== participants.length ||
            !participants.includes(held.owner) || participants.some(value => !text(value) ||
              !held.participants.some(row => row.root === value && row.attached === true))) {
          fail('Enter a title of at most 512 UTF-8 bytes and choose 1 to 64 current participants, including the owner.');
        }
        const pendingKey = await hash(JSON.stringify({kind:'create-conversation', graph:stamp.graph,
          scope:stamp.scope, root, owner:held.owner, view:held.view, title, participant_roots:participants}));
        if (!/^[a-f0-9]{64}$/.test(pendingKey)) fail('Conversation retry identity could not be prepared.');
        if (!current(stamp, root) || !heldCurrent()) fail('The Workshop changed before conversation creation. Refresh and retry.');
        if (conversationWrite) {
          if (conversationWrite.key === pendingKey) return conversationWrite.promise;
          fail('Wait for the current conversation creation to finish.');
        }
        if (topologyWrite || topologyRead) fail('Wait for the current canvas operation before creating a conversation.');
        const saved = records();
        if (!saved[pendingKey] && Object.keys(saved).length >= 32) fail('Recover pending Workshop operations before creating more.');
        const id = saved[pendingKey] || uuid();
        if (!text(id) || id.length > 128) fail('Conversation retry identity is invalid.');
        saved[pendingKey] = id; pendingStorage.setItem(storageName, JSON.stringify(saved));
        conversationCreation = {anchor_root:root, pending:true, error:'', accepted:false, requires_refresh:false}; publish();
        const operation = Promise.resolve().then(async () => {
          let result;
          try {
            if (!current(stamp, root) || !heldCurrent()) fail('The Workshop changed before the creation request.');
            result = await post('/api/universal/workshop', {action:'create-conversation', root, scope:stamp.scope,
              revision:held.revision, title, participant_roots:participants, idempotency_key:id});
            if (!result || result.ok !== true) fail(result?.error || 'Conversation creation was refused.');
            if (result.graph_id !== stamp.graph || result.scope_root !== stamp.scope || result.idempotency_key !== id ||
                !text(result.root) || result.root === root || result.root.length > 512 || result.title !== title ||
                result.is_general !== false || typeof result.created !== 'boolean' || !revision(result.revision) ||
                result.revision < held.revision || (result.created && result.revision <= held.revision) ||
                !Array.isArray(result.participant_roots) || JSON.stringify(result.participant_roots) !== JSON.stringify(participants)) {
              fail('The conversation creation response could not be reconciled.');
            }
          } catch (error) {
            const uncertain = new Error((error.message || 'Conversation creation could not be confirmed.') +
              ' Refresh the Workshop and retry the same title and participants; its saved identity will be reused.');
            uncertain.creationUncertain = true;
            if (current(stamp, root)) {
              conversationCreation = {anchor_root:root, pending:false, error:uncertain.message,
                accepted:false, requires_refresh:true}; publish();
            } else {
              workshopNotice = 'Conversation creation in the previous workspace needs reconciliation. Its retry identity is saved.';
              publish();
            }
            throw uncertain;
          }
          let warning = '';
          try {
            const saved = records();
            if (saved[pendingKey] === id) delete saved[pendingKey];
            pendingStorage.setItem(storageName, JSON.stringify(saved));
          } catch (_) { warning = 'Conversation accepted. Pending identity storage needs recovery.'; }
          const accepted = {...result, accepted:true, original_graph:stamp.graph, original_scope:stamp.scope,
            original_workshop:root, warning};
          if (!current(stamp, root)) {
            workshopNotice = 'Conversation created in the previous workspace. Open its Workshop to continue.'; publish();
            return {...accepted, navigated:true, canvas_refreshed:false};
          }
          try {
            const fresh = await get('/api/universal/canvas');
            if (!current(stamp, root)) {
              workshopNotice = 'Conversation created in the previous workspace. Open its Workshop to continue.'; publish();
              return {...accepted, navigated:true, canvas_refreshed:false};
            }
            if (!fresh || fresh.application_root !== stamp.graph || fresh.scope?.current !== stamp.scope ||
                fresh.authorization?.subject !== held.owner || fresh.authorization?.session !== held.view ||
                !revision(fresh.revision) || fresh.revision < result.revision ||
                !fresh.workshop_scope || fresh.workshop_scope.graph_id !== stamp.graph ||
                fresh.workshop_scope.root !== stamp.scope || fresh.workshop_scope.revision !== fresh.revision) {
              fail('The created conversation needs a fresh canvas from this same owner and scope.');
            }
            acceptTopology(fresh);
            const visible = fresh.nodes.some(row => row.id === result.root);
            conversationCreation = {anchor_root:root, root:result.root, title, pending:false, error:'',
              accepted:true, requires_refresh:false, node_visible:visible,
              notice:warning || (visible ? '' : 'Open Workshop Workbench to see the new conversation node.')};
            publish();
            if (current(stamp, root)) await readConversationCatalog(root, null).catch(() => {});
            return {...accepted, canvas_refreshed:true, node_visible:visible};
          } catch (error) {
            if (current(stamp, root)) {
              conversationCreation = {anchor_root:root, root:result.root, title, pending:false,
                accepted:true, requires_refresh:true,
                error:'Conversation created. ' + (error.message || 'Canvas refresh failed.') + ' Refresh the canvas to continue.'};
              publish();
            }
            return {...accepted, canvas_refreshed:false, warning:'Conversation created; the canvas needs refresh.'};
          }
        }).finally(() => { if (conversationWrite?.promise === operation) conversationWrite = null; });
        conversationWrite = {key:pendingKey, promise:operation};
        return operation;
      },
      async readProjectFile(root, file) {
        const stamp = stampFor(root);
        if (!file || !Number.isSafeInteger(file.size) || file.size < 1 || file.size > 65536 ||
            typeof file.arrayBuffer !== 'function') fail('Choose one UTF-8 text source file of 1–65,536 bytes.');
        const bytes = await file.arrayBuffer();
        if (bytes.byteLength !== file.size || bytes.byteLength > 65536) fail('The selected file changed while reading.');
        let content;
        try { content = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true}).decode(bytes); }
        catch (_) { fail('The source file must contain valid UTF-8 text.'); }
        if (content.includes('\0')) fail('Choose a text source file, not a binary file.');
        const sha256 = await hash(content);
        if (!/^[a-f0-9]{64}$/.test(sha256)) fail('The source file hash could not be computed.');
        if (!current(stamp, root)) fail('The Workshop changed while reading the source file.');
        return {path:file.webkitRelativePath || file.name, content, sha256, bytes:bytes.byteLength};
      },
      async createProjectWork(root, details) {
        const stamp = stampFor(root);
        if (workshops.find(row => row.root === root)?.native_work_available === false) {
          fail('Native project work is not yet available in this conversation.');
        }
        const {title, description, criterion, verification, path, content, x, y,
          model = 'nex-agi/nex-n2.5-pro:free', runtime = 'openrouter'} = details || {};
        if (!['openrouter', 'claude'].includes(runtime)) fail('Choose an available repair runtime.');
        if ([title, description, criterion, verification].some(value => !text(value) || !value.trim()) ||
            title.length > 160 || description.length > 12000 || criterion.length > 4000 || verification.length > 4000) {
          fail('Enter a title, requested change, acceptance criterion, and verification method.');
        }
        if (!text(path) || path.length > 512 || /[\\:\x00-\x1f\x7f]/.test(path) ||
            path.split('/').some(part => !part || part === '.' || part === '..')) {
          fail('Use a relative source path such as src/example.js, without parent-directory segments.');
        }
        if (!text(content) || content.includes('\0') || new TextEncoder().encode(content).byteLength > 65536) {
          fail('Choose one UTF-8 text source file of 1–65,536 bytes.');
        }
        if (!Number.isFinite(x) || !Number.isFinite(y)) fail('The Work node needs a valid canvas position.');
        if (runtime === 'claude' && (!text(model) || new TextEncoder().encode(model).byteLength > 160 ||
            model !== model.trim() || /\s/.test(model) || model.startsWith('-'))) fail('Enter one Claude model identifier.');
        if (runtime === 'openrouter' && (!text(model) || model.length > 256 ||
            !/^(?:openrouter\/free|[a-z0-9][a-z0-9._-]*\/[a-z0-9][a-z0-9._-]*:free)$/i.test(model.trim()))) {
          fail('Choose openrouter/free or an explicit OpenRouter model ID ending in :free.');
        }
        const selectedModel = model.trim();
        const sha256 = await hash(content);
        if (!/^[a-f0-9]{64}$/.test(sha256)) fail('The source file hash could not be computed.');
        const key = JSON.stringify([stamp.epoch, stamp.graph, stamp.scope, root, title, description,
          criterion, verification, path, sha256, x, y, selectedModel, runtime]);
        if (!current(stamp, root)) fail('The Workshop changed before Work creation.');
        if (creations.has(key)) return creations.get(key);
        const artifactId = uuid();
        if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(artifactId)) {
          fail('The repair artifact identity could not be prepared.');
        }
        const operation = (async () => {
          let result, dispatched = false;
          try {
            const projection = await api.refreshWorkshop(root);
            if (!current(stamp, root) || !projection || projection.error || !revision(projection.revision)) {
              fail('Refresh the Workshop before creating Work.');
            }
            dispatched = true;
            result = await post('/api/universal/work', {title:title.trim(), description:description.trim(),
              workshop_root:root, workshop_scope:stamp.scope, revision:projection.revision,
              x, y, projection:false, structured_references:{requirements:{acceptance_criteria:[{
                criterion:criterion.trim(), verification:verification.trim()}]}, inputs:{model:selectedModel,
                data_class:'public-text', artifact_name:artifactId + '.patch', files:[{path, content, sha256}],
                ...(runtime === 'claude' ? {runtime:'claude', limits:{max_turns:12, max_processes:8,
                  max_input_bytes:262144, max_output_bytes:4194304, max_event_bytes:1048576,
                  max_events:512, max_process_bytes:805306368, startup_timeout_seconds:60,
                  turn_timeout_seconds:180, lifetime_seconds:600, stop_timeout_seconds:30}} : {})}}});
            if (!result || result.ok === false || !text(result.created_root) || !text(result.membership_wire) ||
                !revision(result.revision) || result.workshop_root !== root || result.workshop_scope !== stamp.scope) {
              fail(result?.error || 'The creation response or conversation link is incomplete.');
            }
          } catch (error) {
            if (!dispatched) throw error;
            const uncertain = new Error((error.message || 'Work creation could not be confirmed.') +
              ' Refresh the canvas and inspect its Work nodes before trying again; creation may have partially succeeded.');
            uncertain.creationUncertain = true;
            if (!current(stamp, root)) {
              workshopNotice = 'Work creation in the previous workspace could not be confirmed. Inspect its canvas before retrying.';
              publish();
            }
            throw uncertain;
          }
          if (!current(stamp, root)) {
            workshopNotice = 'Repair Work was created in the previous workspace. Open its canvas to continue.';
            publish();
          }
          return {...result, accepted:true, original_graph:stamp.graph, original_scope:stamp.scope,
            original_workshop:root, navigated:!current(stamp, root)};
        })();
        creations.set(key, operation);
        try { return await operation; } finally { if (creations.get(key) === operation) creations.delete(key); }
      },
      async refreshNativeWork(root, work = null) {
        if (work !== null && !text(work)) fail('Choose a Work node before reading its saved results.');
        const stamp = stampFor(root), read = ++nativeRead;
        const result = await get('/api/universal/workshop-native?root=' + encodeURIComponent(root) +
          '&scope=' + encodeURIComponent(stamp.scope) + (work ? '&work=' + encodeURIComponent(work) : ''));
        if (!current(stamp, root) || read !== nativeRead) return null;
        if (!result || result.ok === false || result.root !== root || result.scope !== stamp.scope ||
            (work && result.artifacts_work !== work)) fail('Workshop execution status was refused.');
        if (result.selected_work_mode != null && !['agent', 'project'].includes(result.selected_work_mode)) {
          fail('The selected Work runtime could not be verified.');
        }
        if (result.existing_artifacts != null && (!Array.isArray(result.existing_artifacts) ||
            result.existing_artifacts.length > 32 || result.existing_artifacts.some(row =>
              !row || row.work !== result.artifacts_work || !text(row.publication) || !text(row.publisher) || typeof row.available !== 'boolean' ||
              !/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.patch$/.test(row.name) || !/^[a-f0-9]{64}$/.test(row.digest) ||
              !revision(row.bytes) || row.bytes <= 0 || row.bytes > 262144))) {
          fail('Saved agent publication metadata could not be verified.');
        }
        if (result.artifacts != null && (!Array.isArray(result.artifacts) || result.artifacts.some(row =>
            !row || row.work !== result.artifacts_work || row.outcome !== 'succeeded' ||
            (row.mode != null && !['project', 'agent'].includes(row.mode)) ||
            !text(row.result) || !text(row.receipt) || !text(row.name) ||
            !/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.patch$/.test(row.name) || !/^[a-f0-9]{64}$/.test(row.digest) ||
            !revision(row.bytes) || row.bytes > 262144))) fail('Saved Work artifact metadata could not be verified.');
        if (result.failures != null && (!Array.isArray(result.failures) || result.failures.length > 32 ||
            result.failures.some(row => !row || row.work !== result.artifacts_work || row.outcome !== 'failed' ||
              !text(row.result) || !text(row.receipt) || !text(row.worker) || !text(row.error) ||
              !Number.isFinite(row.created_at)))) fail('Failed Work result metadata could not be verified.');
        if (result.local_deliveries != null && (!Array.isArray(result.local_deliveries) || result.local_deliveries.length > 32 ||
            new Set(result.local_deliveries.map(row => row?.grant)).size !== result.local_deliveries.length ||
            result.local_deliveries.some(row => !row || row.work !== result.artifacts_work ||
              !text(row.grant) || row.result !== row.grant + ':project-result' || !text(row.worker) ||
              !/^[a-f0-9]{64}$/.test(row.input_digest) || row.provider_outcome !== 'unknown' || row.output_bytes !== 0 ||
              !['unreceived', 'local_delivery_abandoned'].includes(row.state) ||
              (row.state === 'unreceived' ? row.resolution !== null : row.resolution !== row.grant + ':project-local-resolution')))) {
          fail('Unreceived project result metadata could not be verified.');
        }
        // Status contains metadata only, even if a malformed server includes text.
        const {artifact_text, ...status} = result;
        const pending = Object.values(releaseRecords()).find(row => row.graph === stamp.graph &&
          row.scope === stamp.scope && row.root === root && row.owner === result.owner && row.view === result.view);
        nativeWork = pending ? {...status, state:'release_pending', work:pending.work,
          request_id:pending.request_id, release_resolution:pending.resolution ?
            {result:pending.result, resolution:pending.resolution} : null} : status;
        publish(); return nativeWork;
      },
      async readExistingPublication(root, work, publication) {
        const stamp = stampFor(root), held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop status first.');
        const matches = (held.existing_artifacts || []).filter(row => row.work === work && row.publication === publication);
        if (matches.length !== 1 || matches[0].available !== true) fail('Select one available saved agent publication.');
        const selected = matches[0], requestId = uuid();
        const result = await post('/api/universal/workshop-native', {action:'read_publication',
          root, scope:stamp.scope, work, request_id:requestId, data_class:'public-text', publication});
        if (!current(stamp, root) || nativeWork !== held || !result || result.ok !== true ||
            result.root !== root || result.scope !== stamp.scope || result.work !== work ||
            result.owner !== held.owner || result.view !== held.view || result.request_id !== requestId ||
            result.publication !== publication || result.name !== selected.name ||
            result.digest !== selected.digest || result.bytes !== selected.bytes ||
            typeof result.artifact_text !== 'string' ||
            new TextEncoder().encode(result.artifact_text).byteLength !== selected.bytes ||
            await hash(result.artifact_text) !== selected.digest) fail('The saved publication could not be verified.');
        if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed while opening the result.');
        return result;
      },
      async readWorkRequirements(root, work) {
        const stamp = stampFor(root);
        const held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop operation status first.');
        if (!text(work)) fail('Choose the Work whose acceptance gate you want to correct.');
        const requestId = 'requirements-read-' + uuid().replaceAll('-', '');
        const result = await post('/api/universal/workshop-native', {action:'read_requirements', root,
          scope:stamp.scope, work, request_id:requestId, data_class:'public-text'});
        if (!result || result.ok !== true || result.root !== root || result.scope !== stamp.scope ||
            result.work !== work || result.request_id !== requestId || result.owner !== held.owner ||
            result.view !== held.view || !text(result.target) || !/^[a-f0-9]{64}$/.test(result.digest) ||
            !result.requirements || typeof result.requirements !== 'object' || Array.isArray(result.requirements) ||
            typeof result.editable !== 'boolean' || typeof result.wired !== 'boolean' ||
            !text(result.state) || !revision(result.revision)) {
          fail('The Work requirements response could not be verified.');
        }
        if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed while reading the Work requirements.');
        return result;
      },
      async reviseWorkRequirements(root, work, details) {
        const stamp = stampFor(root);
        const held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop operation status first.');
        const gate = details?.gate, spec = gate?.spec;
        if (!text(work) || !details || !/^[a-f0-9]{32}$/.test(details.revision_id) ||
            !revision(details.expected_revision) ||
            !text(details.expected_target) || !/^[a-f0-9]{64}$/.test(details.expected_digest) ||
            !gate || typeof gate !== 'object' || gate.kind !== 'pytest' || !spec || typeof spec !== 'object' ||
            !text(spec.path) || spec.path.length > 1024 ||
            Object.keys(gate).some(key => !['kind', 'spec'].includes(key)) ||
            Object.keys(spec).some(key => !['path', 'selector', 'args', 'timeout_seconds'].includes(key)) ||
            ('selector' in spec && spec.selector !== spec.path)) {
          fail('Enter one pytest path inside this Work’s CDE before saving the corrected gate.');
        }
        const requestId = 'requirements-revision-' + details.revision_id;
        const result = await post('/api/universal/workshop-native', {action:'revise_requirements', root,
          scope:stamp.scope, work, request_id:requestId, data_class:'public-text',
          revision_id:details.revision_id, expected_revision:details.expected_revision,
          expected_target:details.expected_target, expected_digest:details.expected_digest, gate});
        const applied = result?.requirements_revision;
        if (!result || result.ok !== true || result.root !== root || result.scope !== stamp.scope ||
            result.work !== work || result.request_id !== requestId || result.owner !== held.owner ||
            result.view !== held.view || !applied || applied.applied !== true ||
            applied.revision_id !== details.revision_id || !text(applied.target) ||
            !/^[a-f0-9]{64}$/.test(applied.input_digest) || typeof applied.reused !== 'boolean') {
          fail('The corrected gate response needs reconciliation; reopen the Work requirements before retrying.');
        }
        return result;
      },
      async readWorkConfiguration(root, work) {
        const stamp = stampFor(root);
        const held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop operation status first.');
        if (!text(work)) fail('Choose the Work whose configuration you want to read.');
        const requestId = 'configuration-read-' + uuid().replaceAll('-', '');
        const result = await post('/api/universal/workshop-native', {action:'read_work_configuration', root,
          scope:stamp.scope, work, request_id:requestId, data_class:'public-text'});
        const names = ['cde-container', 'inputs', 'requirements'];
        const fields = result?.fields;
        if (!result || result.ok !== true || result.root !== root || result.scope !== stamp.scope ||
            result.work !== work || result.request_id !== requestId || result.owner !== held.owner ||
            result.view !== held.view || !fields || typeof fields !== 'object' ||
            Object.keys(fields).sort().join() !== names.join() ||
            names.some(name => !fields[name] || !text(fields[name].target) || typeof fields[name].wired !== 'boolean' ||
              (fields[name].wired ? !/^[a-f0-9]{64}$/.test(fields[name].digest) : fields[name].digest !== null)) ||
            typeof result.editable !== 'boolean' || !text(result.state) || !revision(result.revision) ||
            typeof result.artifact_ready !== 'boolean') {
          fail('The Work configuration response could not be verified.');
        }
        if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed while reading the Work configuration.');
        if (result.drafts !== undefined && (!Array.isArray(result.drafts) || result.drafts.length > 64 ||
            result.drafts.some(draft => !draft || !/^[a-f0-9]{32}$/.test(draft.revision_id) ||
              !revision(draft.expected_revision) || !text(draft.proposing_actor) ||
              !['general', 'artifact-publication'].includes(draft.purpose) ||
              !draft.fields || typeof draft.fields !== 'object' || Array.isArray(draft.fields) ||
              !Object.keys(draft.fields).length || Object.keys(draft.fields).some(name => !names.includes(name)) ||
              Object.values(draft.fields).some(entry => !entry || !text(entry.expected_target) ||
                !(entry.expected_digest === null || /^[a-f0-9]{64}$/.test(entry.expected_digest)) ||
                !entry.value || typeof entry.value !== 'object' || Array.isArray(entry.value))))) {
          fail('The saved agent proposals could not be verified.');
        }
        return result;
      },
      async discardWorkConfiguration(root, work, details) {
        const stamp = stampFor(root), held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope || !text(work) ||
            !/^[a-f0-9]{32}$/.test(details?.revision_id) || !revision(details?.expected_revision)) {
          fail('Read the Work configuration before discarding a proposal.');
        }
        const requestId = 'discard-configuration-' + details.revision_id;
        const result = await post('/api/universal/workshop-native', {action:'discard_work_configuration',
          root, scope:stamp.scope, work, request_id:requestId, data_class:'public-text',
          revision_id:details.revision_id, expected_revision:details.expected_revision});
        if (!result || result.ok !== true || result.root !== root || result.scope !== stamp.scope ||
            result.work !== work || result.request_id !== requestId || result.owner !== held.owner ||
            result.view !== held.view || result.discard?.discarded !== true ||
            result.discard.revision_id !== details.revision_id || !revision(result.discard.revision)) {
          fail('Proposal discard was not confirmed. Reopen the configuration before retrying.');
        }
        if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed while discarding the proposal.');
        return result;
      },
      async configureWork(root, work, details) {
        const stamp = stampFor(root);
        const held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop operation status first.');
        const names = ['cde-container', 'inputs', 'requirements'];
        const fields = details?.fields;
        if (!text(work) || !details || !/^[a-f0-9]{32}$/.test(details.revision_id) || !revision(details.expected_revision) ||
            !['general', 'artifact-publication'].includes(details.purpose) || !fields || typeof fields !== 'object' ||
            !Object.keys(fields).length || Object.keys(fields).some(name => !names.includes(name)) ||
            Object.values(fields).some(entry => !entry || typeof entry !== 'object' ||
              Object.keys(entry).sort().join() !== 'expected_digest,expected_target,value' ||
              !text(entry.expected_target) ||
              !(entry.expected_digest === null || /^[a-f0-9]{64}$/.test(entry.expected_digest)) ||
              !entry.value || typeof entry.value !== 'object' || Array.isArray(entry.value))) {
          fail('Read the current Work configuration before saving a change.');
        }
        const requestId = 'configuration-' + details.revision_id;
        // The exact configuration, including its read revision, is resent unchanged on retry.
        const result = await post('/api/universal/workshop-native', {action:'configure_work', root,
          scope:stamp.scope, work, request_id:requestId, data_class:'public-text',
          revision_id:details.revision_id, expected_revision:details.expected_revision,
          purpose:details.purpose, fields});
        const applied = result?.work_configuration;
        if (!result || result.ok !== true || result.root !== root || result.scope !== stamp.scope ||
            result.work !== work || result.request_id !== requestId || result.owner !== held.owner ||
            result.view !== held.view || !applied || applied.applied !== true ||
            applied.revision_id !== details.revision_id || !/^[a-f0-9]{64}$/.test(applied.input_digest) ||
            typeof applied.reused !== 'boolean') {
          fail('The Work configuration response needs reconciliation; reopen it before retrying.');
        }
        return result;
      },
      async nativeWorkAction(root, action, work, details = {}) {
        let submitted = false;
        try {
        const stamp = stampFor(root);
        if (!['prepare', 'prepare_project', 'prepare_native', 'approve_native', 'stop_native', 'recover_project', 'recover_local_project', 'recover_review', 'refresh_project_review', 'approve_project', 'abandon_project', 'execute', 'publish', 'release', 'reconcile',
            'read_artifact', 'read_project', 'revise_project'].includes(action)) fail('Unknown Workshop operation.');
        const held = nativeWork;
        if (!held || held.root !== root || held.scope !== stamp.scope) fail('Read this Workshop operation status first.');
        // A status read started before this action must not replace its input
        // while preparation or execution is waiting for a response.
        nativeRead += 1;
        const allowedDetails = action === 'recover_local_project' ? ['result', 'resolution'] :
          action === 'refresh_project_review' ? ['delegation', 'input_digest'] :
          action === 'abandon_project' ? ['grant', 'result', 'input_digest'] :
          action === 'revise_project' ? ['draft', 'result', 'resolution'] : ['approve_project', 'approve_native'].includes(action) ? ['input_digest'] :
          ['read_artifact', 'recover_project', 'recover_review'].includes(action) ? ['result', 'receipt'] : [];
        if (Object.keys(details).some(key => !allowedDetails.includes(key))) {
          fail('Unexpected Workshop operation fields.');
        }
        const reviewExpired = held.review_expired === true ||
          (Number.isFinite(held.review_expires_at) && Date.now() / 1000 >= held.review_expires_at);
        if (action === 'prepare_native' && (held.artifacts_work !== work || held.selected_work_mode !== 'agent')) {
          fail('Read the selected Work’s native runtime before preparing it.');
        }
        if (action === 'approve_native' && (held.mode !== 'agent' || held.state !== 'awaiting_approval' ||
            held.approved !== false || reviewExpired || held.work !== work || !text(held.worker) ||
            !/^[a-f0-9]{64}$/.test(details.input_digest) || details.input_digest !== held.input_digest)) {
          fail('Review the exact current native repair input before approving it.');
        }
        if (action === 'stop_native' && held.mode !== 'agent') fail('Only a retained native operation can be stopped.');
        if (action === 'refresh_project_review' && (held.mode !== 'project' || held.state !== 'awaiting_approval' ||
            held.approved !== false || !reviewExpired || held.revision_pending || held.work !== work ||
            !text(held.worker) || !text(details.delegation) || details.delegation !== held.delegation ||
            !/^[a-f0-9]{64}$/.test(details.input_digest) || details.input_digest !== held.input_digest)) {
          fail('Refresh only the exact expired, unapproved project review.');
        }
        if (action === 'approve_project' && (held.mode !== 'project' || held.state !== 'awaiting_approval' || reviewExpired ||
            !text(details.input_digest) || details.input_digest !== held.input_digest)) {
          fail('Review the current repair input before approving it.');
        }
        if (action === 'execute' && ['project', 'agent'].includes(held.mode) &&
            (held.state !== 'awaiting_approval' || held.approved !== true || reviewExpired)) fail('Approve this repair input before generating the artifact.');
        const localRevision = action === 'revise_project' && ('result' in details || 'resolution' in details);
        let localRevisionSource = null;
        if (held.revision_pending && ['prepare', 'prepare_project', 'prepare_native', 'recover_project', 'recover_local_project',
            'recover_review', 'release'].includes(action)) fail('Finish the saved Work revision before preparing or closing it.');
        if (localRevision) {
          const matches = (held.local_deliveries || []).filter(row => row.work === work &&
            row.result === details.result && row.resolution === details.resolution &&
            row.state === 'local_delivery_abandoned' && row.provider_outcome === 'unknown');
          if (!text(details.result) || !text(details.resolution) || matches.length !== 1 ||
              !['idle', 'local_delivery_abandoned'].includes(held.state) ||
              (held.state !== 'idle' && held.work !== work) ||
              (held.local_resolution && (held.local_resolution.result !== details.result ||
                held.local_resolution.resolution !== details.resolution))) {
            fail('Read the exact saved local-delivery decision before revising this Work.');
          }
          localRevisionSource = matches[0];
        }
        if (action === 'revise_project' && ((!localRevision && (held.mode !== 'project' || held.state !== 'published' ||
            held.work !== work)) || !details.draft || !/^[a-f0-9]{32}$/.test(details.draft.revision_id) ||
            !/^[a-f0-9]{64}$/.test(details.draft.base_digest))) {
          fail('Read and review this Work’s published result before saving its revision.');
        }
        let requestId = nativeWork?.request_id, selectedArtifact = null;
        if (localRevision && held.state === 'idle') requestId = 'local-revision-' + details.draft.revision_id;
        if (action === 'abandon_project') {
          if (!text(work) || !text(details.grant) || !text(details.result) ||
              !/^[a-f0-9]{64}$/.test(details.input_digest) ||
              !['idle', 'uncertain', 'local_delivery_abandoned'].includes(held.state) ||
              (held.state !== 'idle' && held.work !== work) ||
              (held.local_deliveries || []).filter(row => row.work === work && row.grant === details.grant &&
                row.result === details.result && row.input_digest === details.input_digest &&
                row.provider_outcome === 'unknown' && row.output_bytes === 0).length !== 1) {
            fail('Read the exact unreceived project result before closing its local delivery.');
          }
          if (held.state === 'idle') {
            const key = await hash(JSON.stringify(['native-local-delivery-resolution', stamp.graph,
              held.owner, held.view, stamp.scope, root, work, details.grant, details.result, details.input_digest]));
            if (!/^[a-f0-9]{64}$/.test(key) || !current(stamp, root) || nativeWork !== held) {
              fail('Workshop changed before closing local delivery.');
            }
            const saved = records();
            if (!saved[key] && Object.keys(saved).length >= 32) fail('Recover pending Workshop operations first.');
            requestId = saved[key] || uuid();
            saved[key] = requestId; pendingStorage.setItem(storageName, JSON.stringify(saved));
          }
        } else if (action === 'prepare' || action === 'prepare_project' || action === 'prepare_native' || action === 'recover_project' || action === 'recover_local_project' || action === 'recover_review') {
          if (!text(work)) fail('Choose a Work node.');
          if (action === 'recover_local_project' && (!['idle', 'local_delivery_abandoned'].includes(held.state) ||
              !text(details.result) || !text(details.resolution) ||
              (held.local_deliveries || []).filter(row => row.work === work && row.result === details.result &&
                row.resolution === details.resolution && row.state === 'local_delivery_abandoned' &&
                row.provider_outcome === 'unknown').length !== 1)) {
            fail('Read the saved local-delivery decision before preparing this Work again.');
          }
          if (action === 'recover_project' && (!text(details.result) || !text(details.receipt) ||
              (held.failures || []).filter(row => row.work === work && row.result === details.result &&
                row.receipt === details.receipt && row.outcome === 'failed').length !== 1)) {
            fail('Read this Work’s exact failed result before preparing a retry.');
          }
          if (action === 'recover_review' && (held.state !== 'idle' || !text(details.result) || !text(details.receipt) ||
              (held.artifacts || []).filter(row => row.work === work && row.result === details.result &&
                row.receipt === details.receipt && row.outcome === 'succeeded').length !== 1)) {
            fail('Read this Work’s saved patch and finish the current operation before resuming its review.');
          }
          if (!text(nativeWork?.owner) || !text(nativeWork?.view)) fail('Read the native Workshop status before preparing.');
          const key = await hash(JSON.stringify([action === 'recover_review' ? 'native-project-review-recovery' :
            action === 'recover_local_project' ? 'native-project-local-recovery' :
            action === 'recover_project' ? 'native-project-recovery' :
            action === 'prepare_native' ? 'native-agent-work' : action === 'prepare_project' ? 'native-project-work' : 'native-work', stamp.graph, nativeWork.owner,
            nativeWork.view, stamp.scope, root, work,
            ...(['recover_project', 'recover_review'].includes(action) ? [details.result, details.receipt] :
              action === 'recover_local_project' ? [details.result, details.resolution] : [])]));
          if (!/^[a-f0-9]{64}$/.test(key)) fail('Workshop request identity is invalid.');
          if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed before preparing the operation.');
          const saved = records();
          if (!saved[key] && Object.keys(saved).length >= 32) fail('Recover pending Workshop operations first.');
          requestId = saved[key] || uuid();
          if (!text(requestId) || requestId.length > 119) fail('Workshop request identity is invalid.');
          saved[key] = requestId; pendingStorage.setItem(storageName, JSON.stringify(saved));
        } else if (action === 'read_project') {
          if (!text(work)) fail('Choose the Work to revise.');
          requestId = uuid();
        } else if (action === 'read_artifact') {
          if (Object.keys(details).length) {
            if (!text(work) || !text(details.result) || !text(details.receipt)) fail('Choose the exact saved artifact.');
            const matches = (held.artifacts || []).filter(row => row.work === work &&
              row.result === details.result && row.receipt === details.receipt);
            if (matches.length !== 1) fail('Read this Work’s saved artifacts before downloading.');
            selectedArtifact = matches[0];
            requestId = uuid(); // Read identity only: no grant or pending-operation storage.
          } else {
            work = held.work; selectedArtifact = held.artifact;
          }
          if (!selectedArtifact || selectedArtifact.outcome === 'failed') fail('This Work has no successful patch artifact.');
          if (!text(requestId) || requestId.length > 119) fail('Artifact read identity is invalid.');
        } else if (!localRevision) { work = nativeWork?.work; }
        if (!current(stamp, root) || !text(requestId) || !text(work)) fail('Refresh the Workshop operation first.');
        let releaseKey, localRelease = null;
        if (action === 'release') {
          if (!text(nativeWork?.owner) || !text(nativeWork?.view)) fail('Refresh the review owner before finishing.');
          if (held.mode === 'agent' && !['published', 'release_pending'].includes(held.state)) {
            const failed = held.native_result;
            const confirmedFailure = held.state === 'settled' && failed?.state === 'settled' &&
              failed.outcome === 'failed' && failed.work === held.work && text(failed.grant) &&
              failed.receipt === failed.grant + ':native-receipt' &&
              failed.result === failed.grant + ':native-result' && revision(failed.revision);
            const cancellation = held.native_cancellation;
            if (!confirmedFailure && (held.state !== 'native_cancelled' ||
                cancellation?.state !== 'cancelled' || cancellation.releasable !== true ||
                cancellation.work !== held.work || cancellation.worker !== held.worker || !text(held.worker) ||
                !text(cancellation.assignment) || !text(cancellation.cancellation) ||
                cancellation.cancellation !== cancellation.assignment + ':native-cancellation' ||
                !text(cancellation.session_close_receipt) || !revision(cancellation.revision))) {
              fail('Confirm this native failure or cancellation before closing it.');
            }
          }
          const decision = nativeWork.state === 'release_pending' ? nativeWork.release_resolution :
            nativeWork.state === 'local_delivery_abandoned' ? nativeWork.local_resolution : null;
          if (decision) {
            if (!text(decision.result) || !decision.result.endsWith(':project-result') ||
                decision.resolution !== decision.result.slice(0, -':project-result'.length) + ':project-local-resolution') {
              fail('Read the exact local delivery decision before closing its panel.');
            }
            localRelease = {result:decision.result, resolution:decision.resolution};
          }
          const record = {graph:stamp.graph, scope:stamp.scope, root, work, request_id:requestId,
            owner:nativeWork.owner, view:nativeWork.view, ...(localRelease || {})};
          releaseKey = await hash(JSON.stringify(record));
          if (!/^[a-f0-9]{64}$/.test(releaseKey)) fail('Review recovery identity is invalid.');
          if (!current(stamp, root)) fail('Workshop changed before finishing the review.');
          const saved = releaseRecords();
          if (!saved[releaseKey] && Object.keys(saved).length >= 8) fail('Recover pending finished reviews first.');
          saved[releaseKey] = record;
          const raw = JSON.stringify(saved);
          if (raw.length > 65536) fail('Pending review recovery exceeds its storage limit.');
          pendingStorage.setItem(releaseStorageName, raw);
        }
        try {
          submitted = true;
          const result = await post('/api/universal/workshop-native', {action, root, scope:stamp.scope,
            work, request_id:requestId, data_class:'public-text',
            ...(['approve_project', 'approve_native'].includes(action) ? {input_digest:details.input_digest} : {}),
            ...(action === 'refresh_project_review' ? {delegation:details.delegation, input_digest:details.input_digest} : {}),
            ...(action === 'abandon_project' ? {grant:details.grant, result:details.result, input_digest:details.input_digest} : {}),
            ...(action === 'recover_local_project' ? {result:details.result, resolution:details.resolution} : {}),
            ...(action === 'release' && localRelease ? localRelease : {}),
            ...(action === 'revise_project' ? {draft:details.draft} : {}),
            ...(localRevision ? {result:details.result, resolution:details.resolution} : {}),
            ...(['read_artifact', 'recover_project', 'recover_review'].includes(action) && details.result ?
              {result:details.result, receipt:details.receipt} : {})});
          if (action === 'revise_project' && result?.revision_rejection) {
            const refusal = result.revision_rejection;
            const error = new Error('The Work revision was refused. Review its inputs or reconcile its saved draft.');
            if (result.ok === true && result.root === root && result.scope === stamp.scope &&
                result.work === work && result.request_id === requestId &&
                result.owner === held.owner && result.view === held.view &&
                refusal.revision_id === details.draft.revision_id && refusal.confirmed === true &&
                refusal.staged === false) error.revisionRejectedNoWrite = true;
            throw error;
          }
          if (!result || result.ok === false || result.root !== root || result.scope !== stamp.scope ||
              result.request_id !== requestId || result.work !== work ||
              (action === 'approve_project' && (result.mode !== 'project' || result.input_digest !== details.input_digest)) ||
              (['prepare_native', 'approve_native', 'stop_native'].includes(action) &&
                (result.mode !== 'agent' || result.owner !== held.owner || result.view !== held.view)) ||
              (action === 'approve_native' && (result.input_digest !== details.input_digest ||
                result.worker !== held.worker || result.approved !== true || result.state !== 'awaiting_approval')) ||
              (action === 'refresh_project_review' && (!current(stamp, root) || nativeWork !== held ||
                result.owner !== held.owner || result.view !== held.view || result.mode !== 'project' ||
                result.state !== 'awaiting_approval' || result.approved !== false || result.worker !== held.worker ||
                !text(result.delegation) || result.delegation === details.delegation ||
                result.input_digest !== held.input_digest || result.review_text !== held.review_text ||
                result.model !== held.model || result.artifact_name !== held.artifact_name ||
                !Number.isFinite(result.review_expires_at) || result.review_expires_at <= Date.now() / 1000 ||
                result.review_refresh?.delegation !== details.delegation ||
                result.review_refresh?.input_digest !== details.input_digest ||
                result.review_refresh?.request_id !== requestId)) ||
              (action === 'recover_local_project' && (!current(stamp, root) || nativeWork !== held ||
                result.owner !== held.owner || result.view !== held.view || result.mode !== 'project' ||
                result.recovery_kind !== 'local_delivery' || result.recovery?.provider_outcome !== 'unknown' ||
                result.recovery_request?.result !== details.result || result.recovery_request?.resolution !== details.resolution ||
                result.recovery_request?.work !== work || result.recovery_request?.request_id !== requestId ||
                !['attaching', 'recovering', 'preparing', 'awaiting_approval', 'uncertain'].includes(result.state) ||
                result.approved !== false)) ||
              (action === 'abandon_project' && (!current(stamp, root) || nativeWork !== held ||
                result.owner !== held.owner || result.view !== held.view || result.state !== 'local_delivery_abandoned' ||
                result.local_resolution?.decision !== 'abandon_local_delivery' ||
                result.local_resolution?.provider_outcome !== 'unknown' ||
                result.local_resolution?.grant !== details.grant || result.local_resolution?.result !== details.result ||
                result.local_resolution?.input_digest !== details.input_digest || result.local_resolution?.work !== work ||
                result.local_resolution?.actor !== held.owner || result.local_resolution?.view !== held.view ||
                result.local_resolution?.scope !== stamp.scope ||
                result.local_resolution?.resolution !== details.grant + ':project-local-resolution')) ||
              (action === 'revise_project' && (!current(stamp, root) || nativeWork !== held ||
                result.owner !== held.owner || result.view !== held.view ||
                result.state !== (localRevision ? 'local_delivery_abandoned' : 'published') ||
                (localRevision && (result.approved !== false || result.mode !== 'project' ||
                  result.artifact != null || result.receipt != null ||
                  result.local_resolution?.decision !== 'abandon_local_delivery' ||
                  result.local_resolution?.provider_outcome !== 'unknown' ||
                  result.local_resolution?.actor !== held.owner || result.local_resolution?.view !== held.view ||
                  result.local_resolution?.scope !== stamp.scope ||
                  ['work','result','resolution','grant','input_digest','worker'].some(key =>
                    result.local_resolution?.[key] !== localRevisionSource[key]) ||
                  (held.local_resolution && (Object.keys(result.local_resolution).length !== Object.keys(held.local_resolution).length ||
                    Object.keys(held.local_resolution).some(key => result.local_resolution[key] !== held.local_resolution[key]))))) ||
                result.work_revision?.applied !== true ||
                result.work_revision.revision_id !== details.draft.revision_id ||
                !/^[a-f0-9]{64}$/.test(result.work_revision.input_digest) ||
                !/^[a-f0-9]{64}$/.test(result.work_revision.current_input_digest))) ||
              (action === 'release' && (result.state !== 'released' || result.released !== true ||
                result.owner !== held.owner || result.view !== held.view ||
                (localRelease && (result.result !== localRelease.result || result.resolution !== localRelease.resolution ||
                  result.owner !== held.owner || result.view !== held.view))))) {
            fail('Workshop operation response needs reconciliation.');
          }
          if (action === 'read_project') {
            const draft = result.draft;
            if (result.owner !== held.owner || result.view !== held.view || result.state !== 'draft' || result.mode !== 'project' || !draft ||
                !text(draft.title) || !text(draft.description) || !revision(draft.revision) ||
                !/^[a-f0-9]{64}$/.test(draft.input_digest) ||
                draft.inputs?.data_class !== 'public-text' || !Array.isArray(draft.inputs.files) ||
                draft.inputs.files.length < 1 || draft.inputs.files.length > 8 ||
                !Array.isArray(draft.requirements?.acceptance_criteria) ||
                draft.requirements.acceptance_criteria.length < 1 || draft.requirements.acceptance_criteria.length > 8) {
              fail('The Work draft could not be read completely.');
            }
            if (draft.pending_revision != null) {
              const pending = draft.pending_revision;
              if (!/^[a-f0-9]{32}$/.test(pending.revision_id) ||
                  !/^[a-f0-9]{64}$/.test(pending.base_digest) || !/^[a-f0-9]{64}$/.test(pending.input_digest) ||
                  pending.inputs?.data_class !== 'public-text' || !Array.isArray(pending.inputs.files) ||
                  pending.inputs.files.length < 1 || pending.inputs.files.length > 8 ||
                  !Array.isArray(pending.requirements?.acceptance_criteria) ||
                  pending.requirements.acceptance_criteria.length < 1 || pending.requirements.acceptance_criteria.length > 8 ||
                  (held.local_deliveries || []).filter(row => row.work === work &&
                    row.state === 'local_delivery_abandoned' && row.provider_outcome === 'unknown' &&
                    row.result === pending.result && row.resolution === pending.resolution).length !== 1) {
                fail('The saved revision does not match this Work’s local delivery decision.');
              }
            }
            if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed while reading this Work.');
            return result; // Selected source text stays in the editor, not the native status cache.
          }
          if (action === 'read_artifact') {
            const artifact = result.artifact;
            if (!['project', 'agent'].includes(result.mode) ||
                result.mode !== (details.result ? selectedArtifact.mode || 'project' : held.mode) || typeof result.artifact_text !== 'string' ||
                !artifact || !text(artifact.name) || !/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.patch$/.test(artifact.name) ||
                !/^[a-f0-9]{64}$/.test(artifact.digest) || !revision(artifact.bytes) || artifact.bytes > 262144 ||
                new TextEncoder().encode(result.artifact_text).byteLength !== artifact.bytes ||
                selectedArtifact.digest !== artifact.digest || selectedArtifact.name !== artifact.name ||
                selectedArtifact.bytes !== artifact.bytes || selectedArtifact.result !== artifact.result ||
                selectedArtifact.receipt !== artifact.receipt ||
                await hash(result.artifact_text) !== artifact.digest) fail('The patch artifact could not be verified.');
            if (!current(stamp, root) || nativeWork !== held) fail('The Workshop changed before downloading the patch.');
            return result; // Artifact text stays with this download, never in the native snapshot or storage.
          }
          if (action === 'release') {
            try {
              const saved = records();
              for (const key of Object.keys(saved)) if (saved[key] === requestId) delete saved[key];
              pendingStorage.setItem(storageName, JSON.stringify(saved));
              const releases = releaseRecords();
              delete releases[releaseKey];
              pendingStorage.setItem(releaseStorageName, JSON.stringify(releases));
            } catch (_) { workshopNotice = 'Review finished. Pending operation storage needs recovery.'; }
          }
          // Stop may overlap the retained native execute request. A delayed
          // acknowledgement must not replace a newer status or settled result;
          // the finally read reconciles current host state without replay.
          const supersededNative = held.mode === 'agent' && ['execute', 'stop_native'].includes(action) && nativeWork !== held;
          if (current(stamp, root) && !supersededNative) { nativeRead += 1; nativeWork = result; publish(); }
          return result;
        } finally {
          // Reconcile response loss through a read; never retry execution here.
          if (current(stamp, root)) await api.refreshNativeWork(root,
            ['read_artifact', 'read_project'].includes(action) ? work : null).catch(() => {});
        }
        } catch (error) {
          // Only local preflight proves that no request could have staged data.
          // Transport failures retain the exact submission for reconciliation.
          if (action === 'revise_project' && !submitted) error.revisionRejectedNoWrite = true;
          throw error;
        }
      },
      async approveNativeWork(root, reviewedDigest) {
        const stamp = stampFor(root), held = nativeWork;
        if (!held || held.state !== 'awaiting_approval') fail('Prepare and review the input first.');
        if (held.mode === 'agent') return api.nativeWorkAction(root, 'approve_native', held.work,
          {input_digest:reviewedDigest});
        if (held.mode === 'project') return api.nativeWorkAction(root, 'approve_project', held.work,
          {input_digest:reviewedDigest});
        const body = {root, scope:stamp.scope, work:held.work, delegation:held.delegation, input_digest:held.input_digest};
        const inspected = await get('/api/universal/workshop-model-approval?' + new URLSearchParams(body));
        if (!current(stamp, root) || nativeWork !== held) fail('Workshop changed during review.');
        if (!inspected || inspected.ok === false || inspected.delegation !== held.delegation ||
            inspected.work !== held.work || inspected.input_digest !== held.input_digest || !revision(inspected.revision)) {
          fail('Workshop approval state could not be reconciled.');
        }
        if (inspected.expired) fail('The reviewed delegation has expired.');
        if (!inspected.approved) await post('/api/universal/workshop-model-approval', {...body, revision:inspected.revision});
        return api.refreshNativeWork(root);
      },
      async disconnectAgent(root, agent) {
        // Revokes only this agent's Session Link grant; it never ends its Agent Session
        // enrolment or cancels work already delivered. A retiring channel can be retried.
        const stamp = stampFor(root);
        if (!text(agent) || agent.length > 512 || !agent.startsWith('app:agent-session:runtime:')) {
          fail('Choose an agent to disconnect.');
        }
        const projection = await api.refreshWorkshop(root);
        if (!current(stamp, root) || !projection || projection.error || projection.root !== root ||
            !Array.isArray(projection.participants) || !projection.participants.some(row => row.root === agent) ||
            !revision(projection.revision)) {
          fail('Refresh the Workshop before disconnecting an agent.');
        }
        const result = await post('/api/universal/workshop', {action:'agent-disconnect', root, scope:stamp.scope,
          revision:projection.revision, agent});
        if (!result || result.ok === false) fail(result?.error || 'The disconnect was refused.');
        const outcome = result.disconnect;
        if (result.ok !== true || result.root !== root || result.agent !== agent || result.scope_root !== stamp.scope ||
            result.revision !== projection.revision || !outcome || !['ok', 'uncertain'].includes(outcome.status) ||
            ['detached', 'revoked', 'local_call_joined', 'worker_stopped'].some(key => typeof outcome[key] !== 'boolean') ||
            !['revoked', 'no_channel', 'detached_without_revocation', 'uncertain'].includes(result.outcome) ||
            !['none', 'attached', 'attaching', 'retiring'].includes(result.session_link) ||
            (result.outcome === 'revoked' && !(outcome.status === 'ok' && outcome.detached && outcome.revoked && outcome.local_call_joined))) {
          fail('The disconnect response could not be reconciled. Refresh before retrying.');
        }
        if (current(stamp, root)) await api.refreshWorkshop(root).catch(() => {});
        return {outcome:result.outcome, session_link:result.session_link, disconnect:{...outcome}};
      },
      async workshopAction(root, action, commandId, details = {}, editor = null) {
        const stamp = stampFor(root);
        if (action !== 'send' || Object.keys(details).some(key => !['target', 'message'].includes(key))) {
          fail('This Workshop exposes messaging only; execution uses its existing agent authority.');
        }
        if (editor && (!editorHandles.has(editor) || editor.root !== root)) fail('Message editor belongs to another conversation.');
        const held = workshop;
        const category = held?.send_category || workshops.find(row => row.root === root)?.send_category;
        if (!held || held.root !== root || held.error || !text(held.owner) || !text(held.view) ||
            !text(held.self) || !text(category) || held.can_send !== true) fail('Refresh the Workshop before sending.');
        if (!text(details.target) || !held.participants.some(row => row.root === details.target && row.attached) ||
            typeof details.message !== 'string' || !details.message.trim() || details.message.length > 12000) {
          fail('Choose a current participant and enter a bounded message.');
        }
        const body = {root, scope:stamp.scope, category, text:details.message.trim(),
          refs:[], evidence:[], recipients:[details.target], reply_to:null, created_at:null};
        const pendingKey = await hash(JSON.stringify({graph:stamp.graph, owner:held.owner, view:held.view, body}));
        if (!/^[a-f0-9]{64}$/.test(pendingKey)) fail('Message identity could not be prepared.');
        if (!current(stamp, root) || workshop !== held) fail('The Workshop changed before sending. Refresh and retry.');
        if (sends.has(pendingKey)) return sends.get(pendingKey);
        const saved = records();
        if (commandId && (!text(commandId) || commandId.length > 128)) fail('Message identity is invalid.');
        if (saved[pendingKey] && commandId && saved[pendingKey] !== commandId) fail('Reconcile the pending message before choosing another identity.');
        if (!saved[pendingKey] && Object.keys(saved).length >= 32) fail('Reconcile pending messages before sending more.');
        const id = saved[pendingKey] || commandId || uuid();
        if (!text(id) || id.length > 128) fail('Message identity is invalid.');
        saved[pendingKey] = id;
        pendingStorage.setItem(storageName, JSON.stringify(saved));
        const operation = (async () => {
          const stagedPage = editor ? await editor.stageMessage(id) : null;
          if (!current(stamp, root)) fail('Conversation changed before sending.');
          const result = await post('/api/universal/workshop', {...body, idempotency_key:id});
          if (!result || result.ok === false) fail(result?.error || 'The message was refused.');
          if (result.workshop !== root || !text(result.root) || result.idempotency_key !== id ||
              !revision(result.revision)) fail('The message response could not be reconciled. Retry with the same identity.');
          let warning = '';
          if (editor) {
            try { await editor.savedMessage(result.root, stagedPage); }
            catch (_) { warning = 'Message accepted. Its draft protection still needs reconciliation.'; }
          }
          try {
            const saved = records();
            if (saved[pendingKey] === id) delete saved[pendingKey];
            pendingStorage.setItem(storageName, JSON.stringify(saved));
          } catch (_) { warning = [warning, 'Message accepted. Pending message recovery could not be updated.'].filter(Boolean).join(' '); }
          const accepted = {...result, accepted:true, original_graph:stamp.graph,
            original_scope:stamp.scope, original_workshop:root, warning};
          if (!current(stamp, root)) {
            workshopNotice = 'Message accepted in the previous workspace. Open it to see the result.';
            publish(); return {...accepted, navigated:true};
          }
          workshopNotice = warning;
          if (current(stamp, root)) {
            // Reconcile the accepted send without waiting on an obsolete poll.
            pageEpoch += 1; pageTarget = {root, before:null, feed:pageTarget?.feed || 'all',
              feedInitialized:pageTarget?.feedInitialized === true,
              storage:pageTarget?.storage || workshop?.storage}; workshop = null;
            publish();
            await api.refreshWorkshop(root).catch(() => {});
          }
          return accepted;
        })();
        sends.set(pendingKey, operation);
        try { return await operation; } finally { if (sends.get(pendingKey) === operation) sends.delete(pendingKey); }
      },
    };
    return api;
  }
  global.ArchHubExistingWorkshop = {create};
})(typeof window === 'undefined' ? globalThis : window);
