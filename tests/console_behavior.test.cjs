// Dependency-free regression tests for the production console event handlers.
// The DOM stub is local test data; actual browser acceptance is recorded separately.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {webcrypto} = require('node:crypto');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../app/static/console.js'), 'utf8');
function fragment(start, end) {
  const begin = source.indexOf(start), finish = source.indexOf(end, begin);
  assert.ok(begin >= 0 && finish > begin, 'Production handler boundaries exist');
  return source.slice(begin, finish);
}
class Element {
  constructor(tag, text, className = '') {
    this.tag = tag; this.textContent = text; this.className = className;
    this.children = []; this.listeners = {}; this.disabled = false;
    this.classList = {toggle: (name, selected) => {
      const classes = new Set(this.className.split(' ').filter(Boolean));
      selected ? classes.add(name) : classes.delete(name);
      this.className = [...classes].join(' ');
    }};
  }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
}
function sourceHarness() {
  const root = new Element('section'), input = new Element('input');
  const scenarios = Array.from({length: 12}, () => new Element('button'));
  const requests = [], payloads = new Map();
  const context = vm.createContext({
    $: selector => ({'#source-results': root, '#order-id': input})[selector],
    node: (tag, text, classes) => new Element(tag, text, classes),
    id: encodeURIComponent, sourceGeneration: 0, selectedScenario: 2,
    document: {querySelectorAll: selector => selector === '.scenario' ? scenarios : root.children.filter(card => card.className.includes('logistics-card'))},
    api: async path => {
      requests.push(path);
      if (!payloads.has(path)) throw Object.assign(new Error('Not found'), {status: 404});
      return {status: 200, data: structuredClone(payloads.get(path))};
    },
    jsonView: (target, data) => { target.textContent = JSON.stringify(data); },
    errorText: error => error.message,
  });
  vm.runInContext(fragment('function sourceCard(', '$("#inspect-form").addEventListener'), context);
  return {root, input, scenarios, requests, payloads, context};
}
test('parcel-only retry rebuilds tracking panels and preserves independent OMS/warehouse reads', async () => {
  const h = sourceHarness(); h.input.value = 'ORD-DEMO-110';
  const base = '/api/oms/orders/ORD-DEMO-110';
  h.payloads.set(base, {status: 'PACKED'});
  h.payloads.set('/api/warehouse/orders/ORD-DEMO-110/notes', []);
  h.payloads.set(base + '/parcels', [{parcel_id: 'PAR-110', tracking_number: null}]);
  await h.context.inspect();
  assert.equal(h.root.children.length, 4);
  const oms = h.root.children[0], warehouse = h.root.children[1];
  const retry = h.root.children[2].children[0].children[2];
  h.requests.length = 0;
  h.payloads.set(base + '/parcels', [{parcel_id: 'PAR-110', tracking_number: 'TRK-110'}]);
  await retry.listeners.click();
  await new Promise(setImmediate);
  assert.equal(h.root.children.length, 5);
  assert.equal(h.root.children[3].children[0].children[0].textContent, 'Logistics · TRK-110');
  assert.equal(h.root.children[4].children[0].children[0].textContent, 'Events · TRK-110');
  assert.equal(h.root.children[0], oms);
  assert.equal(h.root.children[1], warehouse);
  assert.deepEqual(h.requests, [base + '/parcels', '/api/logistics/shipments/TRK-110', '/api/logistics/shipments/TRK-110/events']);
  h.payloads.set(base + '/parcels', [{parcel_id: 'PAR-110', tracking_number: null}]);
  await retry.listeners.click();
  assert.equal(h.root.children.length, 4, 'Old tracking panels disappear');
});
test('manual and customer-linked order inspection updates the selected golden scenario', async () => {
  const h = sourceHarness();
  for (const [order, selected] of [['ORD-DEMO-002', 1], ['ORD-DEMO-110', -1], ['ORD-DEMO-012', 11]]) {
    h.input.value = order; await h.context.inspect();
    assert.equal(h.scenarios.findIndex(button => button.className.includes('selected')), selected);
  }
});
test('history pagination prevents double submission without touching reply-form status', async () => {
  const button = new Element('button'); let finish, reads = 0;
  const barrier = new Promise(resolve => { finish = resolve; });
  const context = vm.createContext({
    $: selector => { assert.equal(selector, '#more-messages'); return button; },
    loadMessages: async () => { reads++; await barrier; },
  });
  vm.runInContext(fragment('$("#more-messages").addEventListener', '$("#open-inquiry").addEventListener'), context);
  const pending = button.listeners.click();
  assert.equal(button.disabled, true);
  await button.listeners.click(); assert.equal(reads, 1);
  finish(); await pending; assert.equal(button.disabled, false);
});
test('uncertain conversation write retries reuse a key; new submissions get a new key', async () => {
  const payloads = []; let attempt = 0;
  const context = vm.createContext({
    pendingCommands: new Map(), crypto: webcrypto,
    api: async (path, method, payload) => {
      payloads.push(payload); attempt++;
      if (attempt === 1) throw new Error('Connection interrupted');
      return {status: 201, data: {message_id: 'MSG-accepted'}};
    },
  });
  vm.runInContext(fragment('async function command(', 'async function refreshSummary('), context);
  await assert.rejects(context.command('thread', '/messages', {text: 'hello'}));
  await context.command('thread', '/messages', {text: 'hello'});
  assert.equal(payloads[0].idempotency_key, payloads[1].idempotency_key);
  await context.command('thread', '/messages', {text: 'hello'});
  assert.notEqual(payloads[1].idempotency_key, payloads[2].idempotency_key);
});
test('view switching sets accessible navigation and respects reduced-motion scrolling', () => {
  const views = ['sources', 'support', 'faults', 'simulation'].map(name => ({id: `view-${name}`}));
  const nav = views.map(view => ({
    dataset: {view: view.id.slice(5)}, attributes: {},
    classList: {toggle() {}}, setAttribute(name, value) { this.attributes[name] = value; },
  }));
  const title = {}, scrolls = []; let reduced = false;
  const context = vm.createContext({
    document: {querySelectorAll: selector => selector === '.view' ? views : nav},
    $: () => title, connected: false,
    window: {scrollTo: value => scrolls.push(value), matchMedia: () => ({matches: reduced})},
  });
  vm.runInContext(fragment('function view(', 'document.querySelectorAll(".nav").forEach(button'), context);
  context.view('support');
  assert.equal(title.textContent, '客户会话');
  assert.deepEqual(views.map(view => view.hidden), [true, false, true, true]);
  assert.deepEqual(nav.map(item => item.attributes['aria-pressed']), ['false', 'true', 'false', 'false']);
  assert.equal(scrolls[0].behavior, 'smooth');
  reduced = true; context.view('sources');
  assert.equal(scrolls[1].behavior, 'auto');
});
