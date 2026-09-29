const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'local_clock.js'), 'utf8');

test('header clock shows local date and time and updates while the page stays open', () => {
  let current = '2026-09-28T10:15:00.000Z';
  const clock = {};
  const dateText = {};
  const timeText = {};
  const events = {};
  let interval;
  class FakeDate extends Date {
    constructor() { super(current); }
  }
  const document = {
    hidden: false,
    getElementById(id) {
      return {
        'current-local-datetime': clock,
        'current-local-date': dateText,
        'current-local-time': timeText,
      }[id];
    },
    addEventListener(name, callback) { events[name] = callback; },
  };
  const window = {
    setInterval(callback, delay) { interval = { callback, delay }; },
    addEventListener(name, callback) { events[name] = callback; },
  };

  vm.runInNewContext(source, { document, window, Date: FakeDate, Intl });
  assert.equal(clock.dateTime, current);
  assert.match(dateText.textContent, /28.*Sep.*2026/);
  assert.match(timeText.textContent, /\d.*(AM|PM)/i);
  assert.equal(interval.delay, 30000);

  current = '2026-09-29T11:45:00.000Z';
  interval.callback();
  assert.equal(clock.dateTime, current);
  assert.match(dateText.textContent, /29.*Sep.*2026/);
  events.pageshow();
  events.visibilitychange();
  assert.equal(clock.dateTime, current);
});

test('pages without the authenticated header do not start a clock', () => {
  const document = { getElementById: () => null };
  vm.runInNewContext(source, { document });
});
