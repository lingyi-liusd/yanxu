const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
function source(from, to) {
  const start = html.indexOf(from), end = html.indexOf(to, start + from.length);
  assert(start >= 0 && end > start, 'Current source boundaries must exist: ' + from);
  return html.slice(start, end);
}
const nodes = {}, listeners = {};
function node(id) {
  return nodes[id] ||= {innerHTML: '', classList: {add() {}, remove() {}, toggle() {}},
    parentElement: {classList: {add() {}, remove() {}, toggle() {}}},
    setAttribute() {}, addEventListener(type, handler) { (listeners[id + ':' + type] ||= []).push(handler); }};
}
const ctx = {
  $: node, document: {querySelector: () => node('app')},
  data: {projects: [{id: 'fixture-project', name: '测试项目'}], files: []},
  aiProjectId: 'fixture-project', aiView: 'artifacts', aiArtifacts: {artifacts: []},
  aiManagerStatus: null, aiInspectorOpen: false, pid: null, homeView: 'week', view: 'tasks',
  selectedTaskId: 'previous-task', selectedFileId: 'previous-file',
  noteMode: 'notes', noteSection: 'overview', selectedNoteId: null,
  esc: value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])),
  aiProjectPicker: () => '', aiRenderInspector() {}, rdArtifactTree: () => '',
  osSection: (overline, title, body) => body,
  noteRecords: () => [], noteRecord: () => null,
  noteOverviewMarkup: () => '<h2>笔记</h2>', noteNavigatorMarkup: () => '<aside>测试导航</aside>',
  bindNoteActions() {},
};
vm.createContext(ctx);
function evaluate(code) { vm.runInContext(code, ctx, {timeout: 1000}); }
evaluate(source('function renderContent() {', 'function render() {'));
ctx.aiOldRenderContent = ctx.renderContent;
ctx.aiOldRender = () => ctx.renderContent();
evaluate(source('renderContent = function () { if (aiView)', 'home = function () { aiView'));
evaluate(source('function aiOpenWorkspace(mode)', 'function aiOpenTask(id)'));
evaluate(source('function aiRenderContent() {', 'function aiTime(value)'));
evaluate(source('function osWorkspaceMarkup(', 'async function osWorkspaceSettings('));
evaluate(source('function osRenderArtifacts() {', "let rdTimelineMode="));
ctx.aiRenderArtifacts = ctx.osRenderArtifacts;
evaluate(source('function renderNotesView() {', 'function setNoteMode(mode)'));
evaluate(source('$("content").addEventListener("click", function (event) {\n  const button = event.target.closest("button[data-ai-action]");', '$("toolbar").addEventListener("click", function (event) {'));

ctx.render();
const toolbar = nodes.toolbar.innerHTML;
assert(toolbar.includes('data-os-view="artifacts"'), 'AI navigation must render the artifacts tab');
assert(!/笔记|notes|project-notes|data-(?:os|ai)-workspace/.test(toolbar), 'Top AI navigation must have no notes entry');
console.log('PASS: rendered top AI navigation has no notes entry');

const buttons = [...nodes.content.innerHTML.matchAll(/<button\b[^>]*data-ai-action="project-notes"[^>]*>[\s\S]*?<\/button>/g)];
assert.strictEqual(buttons.length, 1, 'Artifacts page must expose exactly one project notes button');
assert(buttons[0][0].includes('项目笔记'), 'Notes entry must be labeled 项目笔记');
assert(buttons[0][0].includes('type="button"'), 'Notes entry must be a button');
console.log('PASS: rendered artifacts page contains the project notes button');

const button = {dataset: {aiAction: buttons[0][0].match(/data-ai-action="([^"]+)"/)[1]}};
for (const handler of listeners['content:click']) {
  handler({target: {closest: selector => selector === 'button[data-ai-action]' ? button : null}});
}
assert.strictEqual(ctx.aiView, '', 'Click must leave AI mode');
assert.strictEqual(ctx.pid, 'fixture-project', 'Click must preserve the selected project');
assert.strictEqual(ctx.homeView, 'projects');
assert.strictEqual(ctx.view, 'notes', 'Click must select the original notes route');
assert.strictEqual(ctx.selectedTaskId, null);
assert.strictEqual(ctx.selectedFileId, null);
assert(nodes.content.innerHTML.includes('class="rd-note-workspace"'), 'Original renderContent must reach renderNotesView');
assert(nodes.content.innerHTML.includes('class="rd-note-center"'));
console.log('PASS: project notes click reaches the original notes workspace for the selected project');
console.log('Notes entry regression PASS (VM software flow; fixture DOM and note subviews; browser UX and independent verification NOT_RUN)');
