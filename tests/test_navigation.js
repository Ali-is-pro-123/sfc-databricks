const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'navigation.js'), 'utf8');

function element() {
  const listeners = new Map();
  const attributes = new Map();
  return {
    open: false,
    offsetParent: {},
    focused: false,
    addEventListener(type, listener) { listeners.set(type, listener); },
    dispatch(type, event = {}) { listeners.get(type)?.(event); },
    setAttribute(name, value) { attributes.set(name, value); if (name === 'open') this.open = true; },
    removeAttribute(name) { attributes.delete(name); if (name === 'open') this.open = false; },
    hasAttribute(name) { return attributes.has(name); },
    getAttribute(name) { return attributes.get(name); },
    getBoundingClientRect() { return { left: 0, right: 320 }; },
    focus() { this.focused = true; },
  };
}

function setup(nativeDialog) {
  const drawer = element();
  const openButton = element();
  const closeButton = element();
  const classes = new Set();
  const document = {
    body: { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } },
    getElementById(id) {
      return { 'navigation-drawer': drawer, 'open-navigation': openButton, 'close-navigation': closeButton }[id];
    },
    addEventListener(type, listener) { this[`on${type}`] = listener; },
  };
  const media = { addEventListener(type, listener) { this[`on${type}`] = listener; } };
  const window = { matchMedia: () => media };
  if (nativeDialog) {
    drawer.showModal = () => drawer.setAttribute('open', '');
    drawer.close = () => { drawer.removeAttribute('open'); drawer.dispatch('close'); };
  }
  vm.runInNewContext(source, { document, window });
  return { drawer, openButton, closeButton, classes, document, media };
}

for (const nativeDialog of [true, false]) {
  test(`navigation opens and closes with ${nativeDialog ? 'native dialog' : 'fallback'}`, () => {
    const app = setup(nativeDialog);
    app.openButton.dispatch('click');
    assert.equal(app.drawer.hasAttribute('open'), true);
    assert.equal(app.openButton.getAttribute('aria-expanded'), 'true');
    assert.equal(app.closeButton.focused, true);
    assert.equal(app.classes.has('navigation-open'), true);

    app.closeButton.dispatch('click');
    assert.equal(app.drawer.hasAttribute('open'), false);
    assert.equal(app.openButton.getAttribute('aria-expanded'), 'false');
    assert.equal(app.openButton.focused, true);
    assert.equal(app.classes.has('navigation-open'), false);
  });
}

test('fallback closes on Escape and desktop resize', () => {
  const app = setup(false);
  app.openButton.dispatch('click');
  app.document.onkeydown({ key: 'Escape' });
  assert.equal(app.drawer.hasAttribute('open'), false);
  app.openButton.dispatch('click');
  app.media.onchange({ matches: true });
  assert.equal(app.drawer.hasAttribute('open'), false);
});
