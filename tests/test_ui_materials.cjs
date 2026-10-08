const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../index.html'), 'utf8');
const match = html.match(/<style id="rd-material-workbench">([\s\S]*?)<\/style>/);
assert(match, 'Materials must be isolated in a display-only stylesheet');
const css = match[1];
const light = css.match(/^:root \{([\s\S]*?)^\}/m)[1];
const dark = css.match(/^:root\[data-theme="dark"\] \{([\s\S]*?)^\}/m)[1];
const token = (block, key) => block.match(new RegExp('--rd-' + key + ':\\s*(#[a-f0-9]{6})', 'i'))[1];
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255)
    .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}
for (const [theme, block] of [['light', light], ['dark', dark]]) {
  for (const foreground of ['text', 'secondary', 'tertiary', 'blue']) {
    for (const background of ['list', 'inspector']) {
      assert(contrast(token(block, foreground), token(block, background)) >= 4.5,
        `${theme}: ${foreground} must remain readable on ${background}`);
    }
  }
  for (const stop of ['material-primary-top', 'material-primary-bottom']) {
    assert(contrast('#ffffff', token(block, stop)) >= 4.5, `${theme}: primary label contrast`);
  }
}
assert(css.includes('.rd-list-pane { background: var(--rd-list); }'), 'Reading pane stays opaque');
assert(!/\.rd-(?:os-tree-row|state-leaf|task-row)[^{]*\{[^}]*backdrop-filter/.test(css), 'No glass on records');
assert(css.includes('pointer-events: none;'), 'Logo highlight cannot intercept clicks');
for (const guard of ['prefers-reduced-motion: reduce', 'prefers-reduced-transparency: reduce',
  'prefers-contrast: more', 'forced-colors: active', '@supports not', '@media print']) {
  assert(css.includes(guard), `Missing fallback: ${guard}`);
}
assert(css.includes('animation: none !important; transition: none !important;'));
assert(css.includes('.rd-today-primary:active, .rd-dialog-actions .rd-primary:active { transform: none; }'));
assert(css.includes('background: Highlight; color: HighlightText;'));
assert.equal((html.match(/<\/body>/g) || []).length, 1);
assert.equal((html.match(/data-ui-icon=/g)||[]).length,9,'Consistent SVG navigation, not font glyphs');
assert(html.includes('aria-label="续芽标志"'), 'Show the user-approved new brand');
assert.equal(require('crypto').createHash('sha256').update(fs.readFileSync(path.join(__dirname,'../assets/yanxu-logo.png'))).digest('hex'),
 '85d14b2173d8752195f4b4a785c1fbfc78b92140dff38bfe8c8680ce75f3aa9b','Logo pixels must not change');
assert(/class="rd-companion-silhouette" aria-hidden="true" focusable="false"/.test(html),'Decoration must not become content or a control');
assert(css.includes('.rd-app.is-os-mode .rd-companion-silhouette { display: none; }'));
assert(css.includes('.rd-today-focus .rd-os-section:has(.rd-today-primary)'),'Emphasize the one real next step, not a synthetic dashboard');
assert(css.includes('overflow-x: hidden;'),'Long project names cannot widen the sidebar');
assert(html.indexOf('</body>') > html.indexOf('id="rd-material-workbench"'));
for (const script of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
console.log('Material UI PASS: light/dark contrast >= 4.5, opaque records, original Logo hash, 9 accessible SVG icons, non-interactive decoration, one real next step, responsive/fallback/print guards, scripts parse');
