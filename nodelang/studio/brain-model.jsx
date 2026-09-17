// brain-model.jsx -- THE BRAIN, DEFINED ONCE.
// Drawn form: "ArchHub Brain Model.html". Written form: decisions/ADGR-0003.
//
// The brain is a GOVERNANCE layer, not a fact store: it holds what kinds of things exist,
// how they relate, and how they are filed -- and it governs that for every user. Facts are the
// bottom stratum and the least interesting one.
//
// Settings -> Brain, Docs -> Brain, and the website all read from here. Before this file the
// three disagreed: Settings showed a flat list of 8 facts, the docs described four layers with
// a promote path nothing implemented, and the website promised the brain never left the
// machine. One definition now, or the same drift comes back.
(() => {
const B = window.AH;

// -- FOUR STRATA - PROPOSED -- top three are structure and can travel, the bottom is instances --
// NOT IN THE SHIPPED CODE. The brain types a fragment by `kind` (fact / skill / wiring) plus a
// `confidence` field; these strata are a proposal layered OVER `kind`, not a description of it.
const BRAIN_STRATA = [
  { id:'ontology', n:'Ontology', one:'what kinds of things exist', col:B.cyan, travels:'freely',
    holds:'The entity types this practice recognises, and the properties each must carry to be valid.',
    eg:'a wall type has a build-up, a fire rating, an acoustic rating',
    why:'Names no project and no client. Two offices sharing an ontology is what a standard IS.' },
  { id:'relations', n:'Relationships', one:'how things connect', col:B.purple, travels:'freely',
    holds:'The edges: what depends on what, what supersedes what, what must be approved before what.',
    eg:'a detail belongs to an assembly, which answers a regulation',
    why:'The topology is method. Publishing it is publishing how you work \u2014 the thing firms want credit for.' },
  { id:'category', n:'Categorisation', one:'how things are filed', col:B.warn, travels:'on opt-in',
    holds:'The taxonomy and its rules: naming, layer conventions, what counts as which category, what is an exception.',
    eg:'A-WALL-EXT is structural; anything -DEMO is excluded from take-offs',
    why:'Usually safe, but a taxonomy can encode a client list in its own category names. Reviewed before it crosses.' },
  { id:'instances', n:'Instances', one:'the actual facts', col:B.err, travels:'never past firm',
    holds:'The filled-in things: this client, this fee, this address, this drawing, this decision on this day.',
    eg:'Tower A, L03, 29 walls, Habib & Partners',
    why:'The only stratum with a data subject in it. Every sensitive class is an instance.' },
];

// -- THREE LAKES - separation is the model, not containment --
// Names follow the SHIPPED scopes: user / project / firm / community. `project` sits INSIDE the
// personal lake -- it routes to the owner's own replica, never a shared one. Personal and firm are
// sealed client-side; community is cleartext BY DESIGN, because publishing is the point.
const BRAIN_LAKES = [
  { id:'personal', n:'Personal', col:B.blue, owner:'you, personally', sees:'self',
    one:'How you work and what you have worked on: your own conventions, your corrections, the projects you touched.',
    lives:'local disk, always', cloud:'sync between your own devices' },
  { id:'firm', n:'Firm', col:B.purple, owner:"that firm's own admin", sees:'firm',
    one:"The practice's own ontology, relationships and taxonomy \u2014 plus the instances that fill them. Shared inside the office only.",
    lives:'office server or tenant cloud', cloud:'per-office choice \u00b7 local-only is real' },
  { id:'community', n:'Community', col:B.cyan, owner:'ArchHub, operated by the founder', sees:'nobody in particular',
    one:'Structure without instances: ontologies, relationship patterns, taxonomies and skills that offices chose to publish.',
    lives:'ArchHub cloud', cloud:'aggregated across offices' },
];

// -- GATES - every crossing has a decider, a record and a way back --
const BRAIN_GATES = [
  { id:'p2f', from:'personal', to:'firm', label:'PERSONAL \u2192 FIRM',
    decider:'you, per fact', def:'closed', revocable:'yes, and the fact leaves',
    passes:'anything you choose', never:'nothing is forced' },
  { id:'f2p', from:'firm', to:'personal', label:'FIRM \u2192 PERSONAL',
    decider:'you, again', def:'offered, not installed', revocable:'yes',
    passes:'office standards you accept', never:'a fact pushed into your head' },
  { id:'f2c', from:'firm', to:'community', label:'FIRM \u2192 COMMUNITY',
    decider:'firm admin, then founder review', def:'closed', revocable:'yes, unpublish',
    passes:'ontology \u00b7 relationships \u00b7 reviewed taxonomy \u00b7 aggregated behaviour',
    never:'an instance \u2014 no project, client or person',
    note:'Checked server-side on the way in against membership. A write path is also a read path when contributing grants access \u2014 the repo already fixed the version of this bug that let a stranger write into a firm and become a permanent reader.' },
  { id:'c2f', from:'community', to:'firm', label:'COMMUNITY \u2192 FIRM',
    decider:'the office, on adoption', def:'readable', revocable:'yes, drop it',
    passes:'published skills and structure', never:'\u2014' },
];

// -- DATA CLASSES - a class cannot rise above its ceiling even with consent --
const BRAIN_CLASSES = [
  { n:'Client names & contacts',    ceil:'firm',     leaves:'on consent',
    why:'Identifies a third party who never agreed. The office holds it contractually; the community has no basis for it.' },
  { n:'Contract values & invoices', ceil:'firm',     leaves:'on consent',
    why:'Commercially fatal sideways to a competitor. Ranges may publish anonymised; figures never.' },
  { n:'Site addresses & coordinates', ceil:'firm',   leaves:'on consent',
    why:'A coordinate plus a drawing re-identifies a client even with the name stripped. Anonymisation does not survive geography.' },
  { n:'Security details',           ceil:'sealed',   leaves:'no path exists',
    why:'Physical-safety data. No consent screen should be able to release it, so there is no button that does.' },
  { n:'Legal & dispute correspondence', ceil:'sealed', leaves:'no path exists',
    why:'Privilege is lost the moment a third party processes it. Local keeps it intact.' },
  { n:'Staff salaries & team notes', ceil:'personal', leaves:'no',
    why:'Employment data under separate national rules. Belongs to HR systems, not a design brain.' },
  { n:'NDA-covered drawings',       ceil:'firm',     leaves:'never past firm',
    why:'The NDA is with the client, not with ArchHub. Publishing breaches a contract we are not party to.' },
  { n:'Approvals & authority records', ceil:'firm',  leaves:'on consent',
    why:'Public-record adjacent, but the mapping to a project is not. Process patterns may publish; records may not.' },
  { n:'Your own personal files',     ceil:'personal', leaves:'your devices only',
    why:'Yours. The office has no claim on it even while you work there.' },
  { n:'Behaviour patterns',          ceil:'community', leaves:'on firm opt-in',
    why:'No subject to identify once aggregated across offices. The only thing the community learns by itself.' },
  { n:'Published skills',            ceil:'community', leaves:'deliberate act',
    why:'Written to be shared. Authored, reviewed, attributed to the firm by choice.' },
];
const CEIL = {
  sealed:    { col:B.err,     label:'NEVER LEAVES' },
  personal:  { col:B.blue,    label:'PERSONAL' },
  firm:      { col:B.purple,  label:'FIRM' },
  community: { col:B.cyan,    label:'COMMUNITY' },
};

// -- FACTS: the design seeds sample facts here; the app never ships them. Settings > Brain
// reads the real facts from ARCHHUB_LOAD_MEMORY and files them under Instances, unclassified and
// sealed by default, because nothing in the shipped brain classifies a fact yet. --
const BRAIN_FACTS = [];

// -- KEYS - the login WRAPS the data key; the cloud is a relay, not a reader --
// PROPOSED. Today the cloud stores fragment text in clear, so "we cannot read it" is FALSE.
// The work is costed in "ArchHub Brain Encryption Solution.html".
const BRAIN_KEYS = {
  how:'A data key is generated on your device and wrapped by a key derived from your login \u2014 wrapped copies go to the server, the keys themselves never do. Each lake has its own data key, so adding a teammate wraps one key rather than touching a single fact.',
  whyNotPassword:'Sealing straight from the password would force re-encrypting every fact on each password change. Wrapping separates the two: rotate the login, re-wrap one small blob, no fact moves.',
  relay:'The cloud only has to converge devices and teammates, and convergence reads one column \u2014 the clock. Everything you wrote travels as a single sealed blob the server stores and returns without opening.',
  recovery:'ArchHub cannot issue, reset or email the recovery kit \u2014 an emailed reset would mean the inbox was the real key, through a route we control. Firm lakes recover through any admin instead.',
  cost:'Lose the login and the kit both and the personal lake is gone. Sessions, skills, wiring, billing and firm membership survive \u2014 losing the key must not lose the account.',
  risk:'Removing a member is forward-secret only: rotating the firm key hides everything written after they left, not what they already held. Rotation is server-gated, never client-gated.',
  // THE website line. ArchHub Website.html reads this, so the promise cannot drift from the model.
  promise:'Your brain is sealed by your own login before it leaves your machine. We move it between your devices and your team without being able to open it \u2014 not by policy, by arithmetic. What you publish to the community, you publish deliberately.',
  wasWrong:'Your brain stays on your machine. Never to us, not to a remote.',
};

const BRAIN_PATHS = {
  personal:'~/.archhub/brain/personal/',
  firm:'office server or tenant cloud',
  community:'ArchHub cloud \u00b7 no per-firm partition',
  // shipped cloud layout, for reference -- cloud_backend/brain_replica.py
  cloudUser:'cloud_backend/data/replicas/<user_id>/brain.db',
  cloudFirm:'cloud_backend/data/replicas/firm/<firm_key>/brain.db',
  cloudCommunity:'cloud_backend/data/replicas/community/<id>/brain.db',
};

Object.assign(window, {
  BRAIN_STRATA, BRAIN_LAKES, BRAIN_GATES, BRAIN_CLASSES, BRAIN_FACTS,
  BRAIN_KEYS, BRAIN_PATHS, BRAIN_CEIL: CEIL,
});
})();
