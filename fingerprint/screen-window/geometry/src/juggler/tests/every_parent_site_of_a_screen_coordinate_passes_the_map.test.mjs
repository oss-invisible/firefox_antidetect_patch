// RULE: every parent site that receives a screen coordinate from a content
// process maps it back to the real screen, and a site that is not in the list
// below is an error.
//
// A content process computes every screen coordinate on the declared window
// origin (firefox-71 root, DESIGN-window-origin.md). A parent site that uses such
// a value on the real screen (a popup position, an APZ anchor, a drag image, the
// screen of an autoscroll) passes it through the map first: StealthScreenMap.sys.mjs
// (StealthScreenRectToReal, StealthScreenXDevPxToReal, StealthScreenYDevPxToReal,
// StealthContextScreenToReal) in JS, StealthMapDragRect in C++. A site that does
// not is wrong by (declared - real) on every host whose window is not where the
// declaration says, and nothing else shows it.
//
// What this test reads, from the tree and without a browser:
//   1. JS_SITES: each site, by file and the code that receives the value, and the
//      one map call that must be on the same line or before it;
//   2. CPP_SITES and SENDS: the same for the C++ that receives a rect from the
//      child (the drag image) and for what the parent sends the child in
//      declared space (the drag points, the matrix);
//   3. the scan: every parent-side JS file of browser/ and toolkit/ that holds a
//      receiving pattern (a screenXDevPx or screenYDevPx name, a `.screenRect`
//      property, an actor parent that opens a popup at a screen position), and
//      every message of a `parent:` section of an .ipdl file that carries a
//      point or a rect, is either one of the sites above or in the table of
//      what needs no map, with the reason. A new one fails here: the next port
//      or the next feature that adds a site must list it and map it.
//
// Negative controls: a copy of each site with its map call removed fails, a copy
// with the map moved after the use fails, a site that no list names is found, a
// message that no list names is found, and an exemption whose code is gone fails.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = file => fs.readFileSync(path.join(TREE, file), 'utf8');
const exists = file => fs.existsSync(path.join(TREE, file));

// kind 'line': every line that uses the value holds the map call (group 1 of
// `map` is the value it wraps). kind 'before': a line that maps the value in
// place comes before every line that uses it.
const JS_SITES = [
  {
    file: 'browser/actors/ContextMenuParent.sys.mjs',
    what: 'the context menu: the click position of the message',
    uses: /\bcontext\.screen[XY]DevPx\b/,
    map: /^\s*context = StealthContextScreenToReal\(wgp\.browsingContext, context\);/,
    kind: 'before',
  },
  {
    file: 'browser/actors/FormValidationParent.sys.mjs',
    what: 'the form validation bubble: the screen rect of the element',
    uses: /\baPanelData\.screenRect\b/,
    map: /StealthScreenRectToReal\(this\.browsingContext, (aPanelData\.screenRect)\)/,
    kind: 'line',
  },
  {
    file: 'toolkit/actors/AutoCompleteParent.sys.mjs',
    what: 'the autocomplete popup: the rect of the input',
    uses: /\bopenPopupAtScreenRect\(/,
    map: /^\s*rect = StealthScreenRectToReal\(this\.browsingContext, rect\);/,
    kind: 'before',
  },
  {
    file: 'toolkit/actors/InputPickerParentCommon.sys.mjs',
    what: 'the date, time and color pickers: the rect of the input',
    uses: /\baData\.rect\b/,
    map: /StealthScreenRectToReal\(this\.browsingContext, (aData\.rect)\)/,
    kind: 'line',
  },
  {
    file: 'toolkit/actors/SelectParent.sys.mjs',
    what: 'the select dropdown: the rect of the select element',
    uses: /(?<![.\w])data\.rect\b/,
    map: /StealthScreenRectToReal\(this\.browsingContext, (data\.rect)\)/,
    kind: 'line',
  },
  {
    file: 'browser/base/content/browser.js',
    what: 'the tooltip of a page: the position of the message',
    uses: /\b[xy]DevPix \/ window\.devicePixelRatio/,
    map: /^\s*xDevPix = StealthScreenXDevPxToReal\(_browser\.browsingContext, xDevPix\);/,
    map2: /^\s*yDevPix = StealthScreenYDevPxToReal\(_browser\.browsingContext, yDevPix\);/,
    kind: 'before',
  },
  {
    file: 'toolkit/components/pictureinpicture/PictureInPicture.sys.mjs',
    what: 'the Picture-in-Picture toggle context menu: the click position of the message',
    uses: /\bdata\.screen[XY]DevPx\b/,
    map: /^\s*PictureInPicture\.openToggleContextMenu\(win, StealthContextScreenToReal\(this\.browsingContext, aMessage\.data\)\);/,
    kind: 'before',
  },
  {
    file: 'browser/components/genai/GenAI.sys.mjs',
    what: 'the selection shortcuts panel: the selection position of the message',
    uses: /\bdata\.screen[XY]DevPx\b/,
    map: /^\s*data = StealthContextScreenToReal\(browser\.browsingContext, data\);/,
    kind: 'before',
  },
  {
    file: 'toolkit/content/widgets/browser-custom-element.mjs',
    what: 'the autoscroll: the start position of the message (the screen, the popup, the start of the scroll, the APZ anchor)',
    uses: /\bscreen[XY]DevPx\b(?!,)/,
    declaration: /^\s*screen[XY]DevPx,\s*$/,
    map: /^\s*screenXDevPx = StealthScreenXDevPxToReal\(browsingContext, screenXDevPx\);/,
    map2: /^\s*screenYDevPx = StealthScreenYDevPxToReal\(browsingContext, screenYDevPx\);/,
    kind: 'before',
  },
];

// C++ that receives a rect from the child, and what the parent sends the child
// in declared space. `span`: the call may continue on the next line.
const CPP_SITES = [
  {
    file: 'widget/nsBaseDragService.cpp',
    what: 'DrawDrag: the rect of the drag image, where the parent consumes what the child sent (TakeVisualization), mapped in place before the session is torn down',
    uses: /\bTakeVisualization\(aScreenDragRect\)/,
    map: /^\s*StealthMapDragRect\(mSourceTopWindowContext, aScreenDragRect\);/,
    end: /^\s*mDragStartData = nullptr;/,
    include: /#include "StealthChromeOffset\.h"/,
    kind: 'after',
  },
  {
    file: 'dom/ipc/BrowserParent.cpp',
    what: 'the matrix and the remote rect sent to the child: the declared ones',
    uses: /(?:->|\.|\b)SendChildToParentMatrix\(/,
    absent: true,
    // BrowserParent.cpp has one include of ours: StealthGetDimensionInfo.h, which includes StealthChromeOffset.h.
    include: /#include "StealthGetDimensionInfo\.h"/,
    kind: 'absent',
  },
  {
    file: 'widget/nsBaseDragService.cpp',
    what: 'the end point and the drop point of a drag, sent to the child in declared space',
    uses: /\bSend(?:EndDragSession|StoreDropTargetAndDelayEndDragSession)\(/,
    // The empty point of a session that is torn down is no coordinate; the other is a definition.
    declaration: /LayoutDeviceIntPoint\(\)|nsBaseDragSession::Send/,
    span: 2,
    map: /StealthDragPoint\(/,
    include: /#include "StealthChromeOffset\.h"/,
    kind: 'line',
  },
];

// What receives a coordinate and needs no map, and why. `pattern` must still be
// in the file: an exemption whose code is gone is an error.
const NEEDS_NO_MAP = [
  {
    file: 'browser/base/content/nsContextMenu.sys.mjs',
    pattern: /context\.screenXDevPx/,
    why: 'reads the context that ContextMenuParent has already mapped (a site above)',
  },
  {
    file: 'toolkit/modules/StealthScreenMap.sys.mjs',
    pattern: /screenXDevPx/,
    why: 'the map itself: the module that implements the functions the sites call',
  },
];

// The messages of a `parent:` section of an .ipdl file (child to parent) that
// carry a point or a rect, and what is done with each. A message that is not
// here fails the scan.
const IPDL_MESSAGES = {
  'PBrowser::InvokeDragSession': 'mapped: StealthMapDragRect in DrawDrag (CPP_SITES)',
  'PBrowserBridge::UpdateDimensions': 'the rect is never read for its position: StealthDeclaredDimensionInfo builds the frame\'s rect from the top window\'s declared state only (dom/ipc/StealthWindowOrigin.h)',
  'PBrowser::LookUpDictionary': 'macOS only (nsIWidget::LookUpDictionary); no build of ours runs on macOS',
  'PBrowser::SynthesizeNativeMouseEvent': 'chrome-only test API of nsIDOMWindowUtils; a page cannot call it and no product code does',
  'PBrowser::SynthesizeNativeMouseMove': 'the same test API',
  'PBrowser::SynthesizeNativeMouseScrollEvent': 'the same test API',
  'PBrowser::SynthesizeNativeTouchPoint': 'the same test API',
  'PBrowser::SynthesizeNativeTouchPadPinch': 'the same test API',
  'PBrowser::SynthesizeNativeTouchTap': 'the same test API',
  'PBrowser::SynthesizeNativePenInput': 'the same test API',
  'PBrowser::SynthesizeNativeTouchpadDoubleTap': 'the same test API',
  'PBrowser::SynthesizeNativeTouchpadPan': 'the same test API',
  'PDocAccessible::CaretMoveEvent': 'accessibility clients only (off unless an assistive technology asks); not a popup and not page-visible',
  'PDocAccessible::FocusEvent': 'the same accessibility event',
  'PAPZBridge::UpdateWheelTransaction': 'the APZ of the parent process: the point is the parent\'s own input event',
  'PAPZBridge::ProcessUnhandledEvent': 'the same: the parent\'s own input event',
  'PAPZBridge::StartAutoscroll': 'the anchor is the value that browser-custom-element.mjs maps (JS_SITES) before CanonicalBrowsingContext::StartApzAutoscroll',
};

const GEOMETRY_TYPES = /\b(?:LayoutDeviceIntPoint|LayoutDeviceIntRect|LayoutDevicePoint|LayoutDeviceRect|DesktopIntPoint|DesktopPoint|DesktopIntRect|DesktopRect|ScreenIntPoint|ScreenPoint|ScreenRect|ScreenIntRect)\b/;

const isComment = line => /^\s*(?:\/\/|\/\*|\*(?:\s|\/|$))/.test(line);

// The problems of one site in one text: [] when it passes the map.
function problemsOf(site, text) {
  const lines = text.split('\n');
  const span = site.span || 1;
  const joined = i => lines.slice(i, i + span).join('\n');
  const problems = [];
  if (site.include && !site.include.test(text)) problems.push('does not include or import the map');
  if (/\.(?:mjs|js)$/.test(site.file) && !/StealthScreenMap\.sys\.mjs/.test(text)) {
    problems.push('does not import StealthScreenMap.sys.mjs');
  }
  const useLines = [];
  lines.forEach((line, i) => {
    if (isComment(line) || (site.declaration && site.declaration.test(line))) return;
    if (site.kind === 'before' && (site.map.test(line) || (site.map2 && site.map2.test(line)))) return;
    if (site.uses.test(line)) useLines.push(i);
  });
  if (site.kind === 'absent') {
    for (const i of useLines) problems.push(`line ${i + 1} sends the real value: ${lines[i].trim()}`);
    return problems;
  }
  if (useLines.length === 0) {
    problems.push('no line uses the value any more: the pattern of the list is stale');
    return problems;
  }
  if (site.kind === 'after') {
    const at = lines.findIndex(line => site.map.test(line));
    if (at === -1) {
      problems.push(`no line maps the value (${site.map})`);
      return problems;
    }
    for (const i of useLines) {
      const end = lines.findIndex((line, j) => j > i && site.end.test(line));
      if (!(i < at && (end === -1 || at < end))) problems.push(`line ${i + 1} reads the rect of the child and the map at line ${at + 1} is not between it and the end of the session: ${lines[i].trim()}`);
    }
    return problems;
  }
  if (site.kind === 'line') {
    for (const i of useLines) {
      if (!site.map.test(joined(i))) problems.push(`line ${i + 1} uses the value without the map: ${lines[i].trim()}`);
    }
    return problems;
  }
  for (const map of [site.map, site.map2].filter(Boolean)) {
    const at = lines.findIndex(line => map.test(line));
    if (at === -1) {
      problems.push(`no line maps the value (${map})`);
      continue;
    }
    const raw = useLines.find(i => i < at);
    if (raw !== undefined) problems.push(`line ${raw + 1} uses the value before the map at line ${at + 1}: ${lines[raw].trim()}`);
  }
  return problems;
}

// The text of a site with its map call taken away.
function withoutMap(site, text) {
  if (site.kind === 'line') {
    const wrapped = new RegExp(site.map.source, site.map.flags.replace('g', '') + 'g');
    return text.replace(wrapped, '$1');
  }
  return text.split('\n').filter(line => !(site.map.test(line) || (site.map2 && site.map2.test(line)))).join('\n');
}

// The text of a site with its map moved to the end of the file.
function withMapAfterTheUse(site, text) {
  const lines = text.split('\n');
  const moved = lines.filter(line => site.map.test(line) || (site.map2 && site.map2.test(line)));
  return lines.filter(line => !moved.includes(line)).concat(moved).join('\n');
}

// --- the scan -----------------------------------------------------------------

const SKIP_DIRS = new Set(['node_modules', 'test', 'tests', 'testing', 'third_party', 'vendor', 'pdfjs', 'docs', 'locales', 'themes', 'branding', 'crashtests', 'gtest']);
const isChildSide = file => /Child\w*\.(?:sys\.mjs|mjs|js)$/.test(path.basename(file)) || file.startsWith('juggler/content/');

function jsFiles(dir, out = []) {
  for (const entry of fs.readdirSync(path.join(TREE, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) jsFiles(rel, out);
    } else if (/\.(?:mjs|js|jsm)$/.test(entry.name) && !/\.min\.js$/.test(entry.name)) {
      out.push(rel);
    }
  }
  return out;
}

// The receiving patterns of a parent-side JS file: a device-px name, a `.screenRect`
// property, and an actor parent that opens a popup at a screen position.
function receivingPatterns(text) {
  const found = [];
  if (/\bscreen[XY]DevPx\b/.test(text)) found.push('screen[XY]DevPx');
  if (/\.screenRect\b/.test(text)) found.push('.screenRect');
  if (/JSWindowActorParent/.test(text) && /\bopenPopupAtScreen(?:Rect)?\(/.test(text)) found.push('actor parent that opens a popup at a screen position');
  return found;
}

// The files of `files` (a Map of path to text) that hold a receiving pattern and
// are neither a site nor in the table of what needs no map.
function unlistedJsSites(files) {
  const listed = new Set([...JS_SITES, ...NEEDS_NO_MAP].map(site => site.file));
  const unlisted = [];
  for (const [file, text] of files) {
    if (isChildSide(file) || listed.has(file)) continue;
    const found = receivingPatterns(text);
    if (found.length) unlisted.push(`${file}: ${found.join(', ')}`);
  }
  return unlisted;
}

// The messages of the `parent:` and `both:` sections of an .ipdl text that carry a
// point or a rect: ["PBrowser::InvokeDragSession", ...].
function geometryMessages(protocol, ipdl) {
  const out = [];
  const parts = ipdl.split(/^[ \t]*(parent|child|both)[ \t]*:/m);
  for (let i = 1; i < parts.length; i += 2) {
    if (parts[i] === 'child') continue;
    for (const m of parts[i + 1].matchAll(/\b(?:async|sync|intr)\s+(\w+)\s*\(([^)]*)\)/g)) {
      if (GEOMETRY_TYPES.test(m[2])) out.push(`${protocol}::${m[1]}`);
    }
  }
  return out;
}

function ipdlFiles(dir, out = []) {
  for (const entry of fs.readdirSync(path.join(TREE, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      if (!['node_modules', 'third_party', 'test', 'tests', 'testing', 'obj'].includes(entry.name) && !entry.name.startsWith('.')) ipdlFiles(rel, out);
    } else if (/\.ipdl$/.test(entry.name)) {
      out.push(rel);
    }
  }
  return out;
}

const IPDL_ROOTS = ['dom', 'gfx', 'accessible', 'widget', 'netwerk', 'ipc', 'toolkit', 'layout', 'docshell', 'media'].filter(exists);
function allGeometryMessages(extra = new Map()) {
  const messages = [];
  const files = IPDL_ROOTS.flatMap(dir => ipdlFiles(dir));
  for (const file of files) messages.push(...geometryMessages(path.basename(file, '.ipdl'), read(file)));
  for (const [protocol, text] of extra) messages.push(...geometryMessages(protocol, text));
  return messages;
}

// --- the tests ----------------------------------------------------------------

test('every site of the list passes the value through the map', () => {
  assert.ok(JS_SITES.length >= 9 && CPP_SITES.length >= 3, 'the list was not emptied');
  for (const site of [...JS_SITES, ...CPP_SITES]) {
    assert.ok(exists(site.file), `${site.file} exists`);
    assert.deepEqual(problemsOf(site, read(site.file)), [], `${site.file}: ${site.what}`);
  }
});

test('negative control: a copy of each site with its map call removed fails', () => {
  for (const site of [...JS_SITES, ...CPP_SITES]) {
    if (site.kind === 'absent') continue;
    const text = read(site.file);
    const stripped = withoutMap(site, text);
    assert.notEqual(stripped, text, `${site.file}: the copy differs`);
    assert.notDeepEqual(problemsOf(site, stripped), [], `${site.file}: ${site.what}: the copy without the map must fail`);
  }
});

test('negative control: a copy with a raw send of the matrix fails', () => {
  const site = CPP_SITES.find(s => s.kind === 'absent');
  const text = read(site.file);
  const raw = text.replace('StealthSendChildToParentMatrix(this, ', 'SendChildToParentMatrix(');
  assert.notEqual(raw, text, 'the copy differs');
  assert.notDeepEqual(problemsOf(site, raw), []);
});

test('negative control: a copy with the map after the use fails', () => {
  const sites = [...JS_SITES, ...CPP_SITES].filter(site => site.kind === 'before' || site.kind === 'after');
  assert.ok(sites.length >= 7);
  for (const site of sites) {
    const text = read(site.file);
    const moved = withMapAfterTheUse(site, text);
    assert.notEqual(moved, text, `${site.file}: the copy differs`);
    assert.notDeepEqual(problemsOf(site, moved), [], `${site.file}: the copy with the map after the use must fail`);
  }
});

test('every exemption still has its code, and a reason', () => {
  for (const entry of NEEDS_NO_MAP) {
    assert.ok(exists(entry.file), `${entry.file} exists`);
    assert.match(read(entry.file), entry.pattern, `${entry.file}: the code that the exemption names is still there`);
    assert.ok(entry.why.length >= 8, `${entry.file}: has a reason`);
  }
  for (const [message, why] of Object.entries(IPDL_MESSAGES)) assert.ok(why.length >= 8, `${message}: has a reason`);
});

test('no parent-side JS file of browser/ and toolkit/ receives a screen coordinate and is not in the list', () => {
  const files = new Map();
  for (const file of [...jsFiles('browser'), ...jsFiles('toolkit')]) {
    if (!isChildSide(file)) files.set(file, read(file));
  }
  assert.ok(files.size > 1000, 'the scan reaches the parent-side JS');
  assert.deepEqual(unlistedJsSites(files), [], 'a parent-side file with a receiving pattern is a site: map it and list it in JS_SITES, or list it in NEEDS_NO_MAP with the reason');
});

test('negative control: a new parent actor that opens a popup at a screen value is found', () => {
  const fake = new Map([
    ['browser/actors/NewThingParent.sys.mjs', 'export class NewThingParent extends JSWindowActorParent {\n  receiveMessage(m) { this.panel.openPopupAtScreenRect("after_start", m.data.x, m.data.y, 1, 1); }\n}\n'],
    ['browser/components/new/NewPanel.sys.mjs', 'let x = data.screenXDevPx / devicePixelRatio;\n'],
    ['toolkit/modules/NewRect.sys.mjs', 'let r = aPanelData.screenRect;\n'],
    ['browser/actors/NewThingChild.sys.mjs', 'sendAsyncMessage("x", { screenXDevPx: event.screenX });\n'],
  ]);
  const found = unlistedJsSites(fake);
  assert.equal(found.length, 3, found.join('\n'));
  assert.ok(found.some(f => f.startsWith('browser/actors/NewThingParent.sys.mjs')));
  assert.ok(found.some(f => f.startsWith('browser/components/new/NewPanel.sys.mjs')));
  assert.ok(found.some(f => f.startsWith('toolkit/modules/NewRect.sys.mjs')));
  assert.ok(!found.some(f => f.includes('NewThingChild')), 'the child side sends the value, it does not receive it');
});

test('every message of a parent: section of an .ipdl file that carries a point or a rect is in the list', () => {
  const messages = allGeometryMessages();
  assert.ok(messages.length >= 10, `the scan reaches the .ipdl files (${messages.length} messages)`);
  assert.deepEqual(messages.filter(m => !(m in IPDL_MESSAGES)), [], 'a message that carries a point or a rect from a child: map it and list it in IPDL_MESSAGES, or list it with the reason');
  assert.deepEqual(Object.keys(IPDL_MESSAGES).filter(m => !messages.includes(m)), [], 'a message of the list that is gone: delete its row');
});

test('negative control: a new message with a rect in a parent: section is found, one in a child: section is not', () => {
  const fake = new Map([
    ['PNewThing', 'protocol PNewThing {\nparent:\n  async ShowThing(nsString aText, LayoutDeviceIntRect aRect);\n  async Other(int aX);\nchild:\n  async Moved(LayoutDeviceIntPoint aPoint);\n};\n'],
  ]);
  const found = allGeometryMessages(fake).filter(m => m.startsWith('PNewThing::'));
  assert.deepEqual(found, ['PNewThing::ShowThing']);
});
