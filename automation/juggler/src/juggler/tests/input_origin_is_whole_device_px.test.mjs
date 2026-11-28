// The origin that a mouse or wheel point gets in the chrome window is a whole number of device pixels, the same one the parent
// subtracts when it hands the point to the page (nsDisplayRemote's offset is rounded at its birth). With the layout rect of the
// <browser>, which is fractional where the chrome above it is not whole (44 CSS px of chrome at 1.75 is 77.65 device px), the
// page saw R(R(x * s + T) - T) and was off by one for some x.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const JUGGLER = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const handlerSource = fs.readFileSync(path.join(JUGGLER, 'protocol/PageHandler.js'), 'utf8');

function methodText(source, name, prefix) {
  const at = source.search(new RegExp('^  ' + (prefix || '') + name + '\\(', 'm'));
  assert.ok(at >= 0, name + ' is a method');
  const open = source.indexOf('{', source.indexOf(')', at));
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0)
      return source.slice(at, i + 1);
  }
  throw new Error('unbalanced ' + name);
}

// The page handler with the two methods of the input mapping, over a chrome window of the given scale whose <browser> starts
// at (left, top) CSS pixels.
function handler({scale, chromeAppUnits, zoom = 1}) {
  const appUnitsPerDevicePixel = Math.round(60 / scale);
  const body = methodText(handlerSource, '_browserOrigin') + ',\n' + methodText(handlerSource, 'async _pagePixels', '');
  const object = new Function('return {\n' + body + '\n};')();
  const rect = {left: 0, top: chromeAppUnits / 60, width: 1920, height: 1080};
  return Object.assign(object, {
    _contentPage: {send: async () => ({zoom})},
    _pageTarget: {
      _linkedBrowser: {getBoundingClientRect: () => rect},
      _window: {devicePixelRatio: 60 / appUnitsPerDevicePixel},
    },
    appUnitsPerDevicePixel,
  });
}

// Gecko's two roundings, in app units: nsContentUtils::ToWidgetPoint (the CSS point to app units, then to device pixels,
// rounded) and BrowserParent::GetChildProcessOffset (app units to device pixels, rounded).
const toApp = css => Math.round(css * 60);
const toDevice = (appUnits, apd) => Math.round(appUnits / apd);

test('a point sent at x lands at R(x * s) in the page at every scale, for every x', async () => {
  for (const scale of [1, 1.25, 1.5, 1.75, 2]) {
    // 44 CSS px of toolbar, 1 of border: the offset of the <browser>, in app units, as the chrome lays it out.
    const h = handler({scale, chromeAppUnits: 44 * 60 + 60});
    const apd = h.appUnitsPerDevicePixel;
    const page = await h._pagePixels();
    // The parent's whole offset: the rounding of the same app units.
    const wholeParentOffset = toDevice(44 * 60 + 60, apd);
    for (let x = 0; x < 400; x += 0.37) {
      const point = page.inWindow(x, x);
      const sentToWidget = toDevice(toApp(point.y), apd);
      const inPage = sentToWidget - wholeParentOffset;
      const expected = toDevice(toApp(x), apd);
      assert.equal(inPage, expected, 'scale ' + scale + ', x = ' + x);
    }
  }
});

test('the old origin, the layout rect, is off by one at 1.75: the case this test is red on the old code', async () => {
  const apd = 34;                                  // 1.75
  const chromeAppUnits = 44 * 60;                  // 77.65 device pixels
  const wholeParentOffset = toDevice(chromeAppUnits, apd);
  let off = 0;
  for (let x = 0; x < 400; x += 0.37) {
    const oldPoint = x + chromeAppUnits / 60;      // x * zoom + rect.top
    if (toDevice(toApp(oldPoint), apd) - wholeParentOffset !== toDevice(toApp(x), apd))
      off++;
  }
  assert.ok(off > 0, 'a fractional origin is off by one for some x');
});

test('the origin is the same whole offset as the parent: whole device pixels', async () => {
  for (const scale of [1, 1.25, 1.5, 1.75, 2]) {
    const h = handler({scale, chromeAppUnits: 44 * 60});
    const apd = h.appUnitsPerDevicePixel;
    const origin = h._browserOrigin();
    assert.equal(origin.top * 60 / apd, toDevice(44 * 60, apd), 'scale ' + scale);
    assert.equal(origin.left, 0);
  }
});

test('the browser\'s origin is the only thing the input mapping reads of the layout rect, apart from the size', () => {
  const body = methodText(handlerSource, 'async _pagePixels', '');
  const withoutComments = body.replace(/\/\/[^\n]*/g, '');
  assert.equal((withoutComments.match(/rect\.(left|top)/g) || []).length, 0, '_pagePixels adds no layout origin of its own');
});
