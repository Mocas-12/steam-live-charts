const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function browser() {
  let now = 1800000000000;
  class ClockDate extends Date { static now() { return now; } }
  const elements = new Map();
  const element = key => {
    if (!elements.has(key)) elements.set(key, {
      style: {}, classList: { toggle() {}, add() {}, remove() {} },
      addEventListener() {}, querySelectorAll() { return []; },
      innerHTML: '', textContent: '',
    });
    return elements.get(key);
  };
  const context = vm.createContext({
    Date: ClockDate, location: { hash: '' },
    localStorage: { getItem() { return null; }, setItem() {} },
    document: { querySelector: element, querySelectorAll() { return []; }, addEventListener() {} },
    fetch: () => new Promise(() => {}), setInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8'), context);
  const api = vm.runInContext('({state, render, updateMeta, isDataStale, metaText})', context);
  return { ...api, element, advance(seconds) { now += seconds * 1000; }, now: now / 1000 };
}

test('data age, not receipt time, determines freshness', () => {
  const b = browser();
  const meta = { updated_at: b.now, ttl: 60, stale: false, refresh_failed: false };
  assert.equal(b.isDataStale(meta), false);
  b.advance(61);
  assert.equal(b.isDataStale(meta), true);
  assert.match(b.metaText(meta), /历史缓存/);
  assert.match(b.metaText(meta), /UTC\+8/);
  assert.match(b.metaText({ ...meta, refresh_failed: true }), /刷新失败/);
});

test('alerts and trend expire even when the next request never returns', () => {
  const b = browser();
  b.state.meta['most-played'] = { updated_at: b.now, ttl: 60, stale: false };
  b.state.data['most-played'] = [{ appid: 1, rank: 1, name: 'A', players: 1000,
    surge: 50, spark: [500, 1000], image: '', url: '' }];
  b.updateMeta();
  assert.match(b.element('#list-most-played').innerHTML, /class="surge"/);
  assert.match(b.element('#list-most-played').innerHTML, /<svg/);
  b.advance(61);
  b.updateMeta();
  assert.doesNotMatch(b.element('#list-most-played').innerHTML, /class="surge"|<svg/);
  assert.equal(b.state.data['most-played'][0].surge, 50);
});

test('switching the active board selects its own metadata', () => {
  const b = browser();
  b.state.meta['most-played'] = { updated_at: b.now, ttl: 60, stale: false };
  b.state.meta.specials = { updated_at: b.now - 3600, ttl: 120, stale: true };
  b.updateMeta();
  assert.match(b.element('#updated-at').textContent, /已采集/);
  b.state.active = 'specials';
  b.updateMeta();
  assert.match(b.element('#updated-at').textContent, /历史缓存/);
});
