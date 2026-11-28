// The parent maps a declared screen coordinate back to the real one, and no
// page can ask it to.
//
// A content process computes every screen coordinate on the declared window
// origin (firefox-71 root, DESIGN-window-origin.md section 3). A chrome actor
// that opens a popup at such a coordinate on the real screen asks the
// CanonicalBrowsingContext of its tab to map it back:
// stealthScreenRectToReal, stealthScreenXDevPxToReal, stealthScreenYDevPxToReal.
// The map holds the declared minus the real origin of the tab, which is the
// host value the whole design keeps out of a page, so what a page must never
// reach is the method itself, on the browsing context of its window or anywhere
// else. Three facts keep it out:
//
//   1. each method is a member of an interface that is [ChromeOnly] and lives in
//      dom/chrome-webidl, and it is itself [ChromeOnly];
//   2. no web-facing WebIDL file (dom/webidl) names it;
//   3. only parent-side code calls it: no child actor, no content script.
//
// This test reads those three from the tree. The negative control is the same
// reader run on a copy of the WebIDL with one [ChromeOnly] removed: it must say
// that the member is exposed.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = file => fs.readFileSync(path.join(TREE, file), 'utf8');

const WEBIDL = 'dom/chrome-webidl/BrowsingContext.webidl';
const METHODS = {
  stealthScreenRectToReal: 'DOMRectReadOnly stealthScreenRectToReal(DOMRectReadOnly aRect);',
  stealthScreenXDevPxToReal: 'double stealthScreenXDevPxToReal(double aXDevPx);',
  stealthScreenYDevPxToReal: 'double stealthScreenYDevPxToReal(double aYDevPx);',
};
const NAME = /\b[Ss]tealthScreen(?:Rect|XDevPx|YDevPx|Context)\w*ToReal\b/;

// The body of `interface <name> ... { ... }` and the extended attributes before it.
function interfaceOf(idl, name) {
  const at = idl.search(new RegExp(`^interface ${name}\\b`, 'm'));
  assert.notEqual(at, -1, `interface ${name} is in the WebIDL`);
  const open = idl.indexOf('{', at);
  let depth = 0;
  let close = -1;
  for (let i = open; i < idl.length; i++) {
    if (idl[i] === '{') depth++;
    if (idl[i] === '}' && --depth === 0) { close = i; break; }
  }
  assert.notEqual(close, -1, `interface ${name} closes`);
  const before = idl.slice(0, at).trimEnd().split('\n').pop();
  return { attributes: before, body: idl.slice(open + 1, close) };
}

// What a page could see of a method: false unless the interface and the member
// are both [ChromeOnly].
function chromeOnly(idl, method) {
  const iface = interfaceOf(idl, 'CanonicalBrowsingContext');
  const interfaceIsChromeOnly = /\bChromeOnly\b/.test(iface.attributes);
  const member = iface.body.split('\n').find(line => line.includes(` ${method}(`));
  if (!member) return { found: false };
  return { found: true, chromeOnly: interfaceIsChromeOnly && /^\s*\[[^\]]*\bChromeOnly\b[^\]]*\]/.test(member) };
}

function files(dir, keep, out = []) {
  for (const entry of fs.readdirSync(path.join(TREE, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      if (!['node_modules', 'test', 'tests', 'docs'].includes(entry.name)) files(rel, keep, out);
    } else if (keep(entry.name)) {
      out.push(rel);
    }
  }
  return out;
}

test('each method is [ChromeOnly], on a [ChromeOnly] interface of the chrome-only WebIDL folder', () => {
  const idl = read(WEBIDL);
  const iface = interfaceOf(idl, 'CanonicalBrowsingContext');
  assert.match(iface.attributes, /\bChromeOnly\b/, 'CanonicalBrowsingContext is [ChromeOnly]');
  for (const [method, signature] of Object.entries(METHODS)) {
    assert.ok(iface.body.includes(`[ChromeOnly] ${signature}`), `${method} is declared [ChromeOnly] with its signature`);
    assert.deepEqual(chromeOnly(idl, method), { found: true, chromeOnly: true }, method);
  }
  const folder = read('dom/chrome-webidl/moz.build');
  assert.match(folder, /"BrowsingContext\.webidl"/, 'BrowsingContext.webidl is generated from dom/chrome-webidl');
});

test('negative control: a method without [ChromeOnly] is read as exposed', () => {
  const idl = read(WEBIDL);
  const stripped = idl.replace('[ChromeOnly] double stealthScreenXDevPxToReal', 'double stealthScreenXDevPxToReal');
  assert.notEqual(stripped, idl, 'the copy differs');
  assert.deepEqual(chromeOnly(stripped, 'stealthScreenXDevPxToReal'), { found: true, chromeOnly: false });
  assert.deepEqual(chromeOnly(stripped, 'stealthScreenRectToReal'), { found: true, chromeOnly: true });
  const exposed = idl.replace(/^\[Exposed=Window, ChromeOnly\]\ninterface CanonicalBrowsingContext/m, '[Exposed=Window]\ninterface CanonicalBrowsingContext');
  assert.notEqual(exposed, idl, 'the copy differs');
  assert.equal(chromeOnly(exposed, 'stealthScreenRectToReal').chromeOnly, false, 'a member is not hidden by its own attribute alone');
});

test('no web-facing WebIDL names the methods', () => {
  for (const file of files('dom/webidl', name => name.endsWith('.webidl'))) {
    assert.doesNotMatch(read(file), NAME, file);
  }
});

test('the C++ names are the WebIDL names with a capital letter, declared and defined once', () => {
  const header = read('docshell/base/CanonicalBrowsingContext.h');
  const body = read('dom/ipc/StealthScreenToReal.cpp');
  for (const method of Object.keys(METHODS)) {
    const cpp = method[0].toUpperCase() + method.slice(1);
    assert.equal(header.split(`${cpp}(`).length - 1, 1, `${cpp} is declared once in CanonicalBrowsingContext.h`);
    assert.equal(body.split(`CanonicalBrowsingContext::${cpp}(`).length - 1, 1, `${cpp} is defined once in StealthScreenToReal.cpp`);
  }
});

test('only parent-side code calls the methods', () => {
  // The one module that calls them on a browsing context, and the actors and
  // the window script that call the module. Every one runs in the parent.
  const module = read('toolkit/modules/StealthScreenMap.sys.mjs');
  for (const method of Object.keys(METHODS)) {
    assert.ok(module.includes(`aBrowsingContext.${method}(`), `${method} is called in StealthScreenMap.sys.mjs`);
  }
  const callers = [
    'toolkit/actors/SelectParent.sys.mjs',
    'toolkit/actors/AutoCompleteParent.sys.mjs',
    'toolkit/actors/InputPickerParentCommon.sys.mjs',
    'browser/actors/FormValidationParent.sys.mjs',
    'browser/actors/ContextMenuParent.sys.mjs',
    'browser/base/content/browser.js',
  ];
  for (const file of callers) {
    assert.match(read(file), /resource:\/\/gre\/modules\/StealthScreenMap\.sys\.mjs/, `${file} imports the module`);
    assert.ok(/Parent|^browser\.js$/.test(path.basename(file).replace(/\.sys\.mjs$/, '')), `${file} is a parent-side file`);
  }
  // Nothing that runs in a content process names them: the child actors, the
  // content scripts and the modules they load.
  const content = [
    ...files('toolkit/actors', name => /Child\w*\.(?:sys\.mjs|js)$/.test(name)),
    ...files('browser/actors', name => /Child\w*\.(?:sys\.mjs|js)$/.test(name)),
    ...files('browser/components', name => /Child\w*\.(?:sys\.mjs|js)$/.test(name)),
    ...files('toolkit/components', name => /Child\w*\.(?:sys\.mjs|js)$/.test(name)),
    ...files('juggler/content', () => true),
  ];
  assert.ok(content.length > 20, 'the scan reaches the child actors');
  for (const file of content) {
    assert.doesNotMatch(read(file), NAME, `${file} runs in a content process`);
  }
  // The module itself is loaded from the parent only: the child actors never
  // import it by URL.
  for (const file of content) {
    assert.doesNotMatch(read(file), /StealthScreenMap\.sys\.mjs/, file);
  }
});
