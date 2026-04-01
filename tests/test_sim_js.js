'use strict';
/**
 * test_sim_js.js — Regression tests for web/sim.html game logic.
 *
 * Since sim.html is a monolithic browser file, this test extracts key
 * functions and state into a controlled environment with minimal mocks.
 *
 * Bugs covered:
 *   1. Ping/pong: handleRelayMsg must respond to ping with pong
 *   2. AI gating: beginTurn must not launch AI for the remote team's turn
 *   3. Color pick: HOST can only pick row 2, GUEST can only pick row 5
 *   4. Color render: renderColorPick dims unselected cells on the correct row
 *
 * Run:
 *   node tests/test_sim_js.js
 *   node tests/test_sim_js.js --verbose
 */

const fs   = require('fs');
const path = require('path');
const vm   = require('vm');

const VERBOSE = process.argv.includes('--verbose');

// ── Minimal test harness (same pattern as test_chessmatrix_js.js) ──────────
let passed = 0, failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    if (VERBOSE) console.log(`  ✓ ${name}`);
    passed++;
  } catch (e) {
    console.log(`  ✗ ${name}: ${e.message}`);
    failures.push(name);
    failed++;
  }
}

function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function assertEqual(a, b) {
  if (a !== b) throw new Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
}

// ── Extract scripts from sim.html ──────────────────────────────────────────
const simHtml = fs.readFileSync(path.join(__dirname, '..', 'web', 'sim.html'), 'utf-8');

// Extract the chess-engine script (between <script id="chess-engine"> and </script>)
const engineMatch = simHtml.match(/<script id="chess-engine">([\s\S]*?)<\/script>/);
if (!engineMatch) throw new Error('Could not find chess-engine script in sim.html');
const engineSrc = engineMatch[1];

// Extract the game-logic script (the second <script> block after the engine)
const gameMatch = simHtml.match(/<\/script>\s*<script>\s*'use strict';([\s\S]*?)<\/script>/);
if (!gameMatch) throw new Error('Could not find game-logic script in sim.html');
const gameSrc = gameMatch[1];

// ── Build sandbox context ──────────────────────────────────────────────────
// Provide minimal mocks for browser APIs the scripts reference at parse time.

function buildSandbox() {
  const sentMessages = [];

  const sandbox = {
    // DOM mocks
    document: {
      getElementById: (id) => {
        if (id === 'chess-engine') return { textContent: '' };
        if (id === 'board') return {
          getContext: () => ({
            clearRect() {}, fillRect() {}, beginPath() {}, arc() {},
            fill() {}, createRadialGradient: () => ({addColorStop() {}}),
            set fillStyle(v) {},
          }),
          width: 640, height: 640,
          addEventListener() {},
        };
        if (id === 'panel-top') return { set innerHTML(v) {} };
        if (id === 'panel-log') return {
          set innerHTML(v) {},
          scrollTop: 0, scrollHeight: 0,
          querySelectorAll: () => [],
        };
        return { style: {}, set innerHTML(v) {}, addEventListener() {} };
      },
      addEventListener() {},
      querySelectorAll: () => [],
    },
    window: { requestAnimationFrame() {} },
    requestAnimationFrame() {},
    navigator: { userAgent: 'node-test' },
    console,
    WebSocket: class { send() {} close() {} },
    Worker: class { postMessage() {} terminate() {} set onmessage(v) {} },
    URL: { createObjectURL: () => 'blob:test' },
    Blob: class { constructor() {} },
    Math,
    performance: { now: () => Date.now() },
    setTimeout,
    setInterval,
    parseInt,
    JSON,
    Uint8Array,
    Array,
    Error,
    Object,

    // Capture sent messages
    _testSent: sentMessages,
  };

  // Create the VM context
  const ctx = vm.createContext(sandbox);

  // Run the engine script first (defines classes like Pawn, King, etc.)
  vm.runInContext(engineSrc, ctx, { filename: 'chess-engine' });

  // Run the game logic (defines all game state and functions)
  vm.runInContext(gameSrc, ctx, { filename: 'game-logic' });

  // Patch AFTER game logic loads so we override the hoisted function declarations.
  // We use Object.defineProperty-style reassignment via simple var assignment.
  vm.runInContext(`
    // Override netSend to capture messages instead of touching WebSocket
    netSend = function(obj) { _testSent.push(obj); };
    // Stub addLog since it touches DOM
    addLog = function(msg) {};
    // Stub flip since it touches canvas
    flip = function() {};
    // Stub renderPanel since it touches DOM
    renderPanel = function() {};
  `, ctx);

  return { ctx, sentMessages };
}

// ── Tests ──────────────────────────────────────────────────────────────────

console.log('\nPing/pong handling');

test('handleRelayMsg responds to ping with pong', () => {
  const { ctx, sentMessages } = buildSandbox();
  sentMessages.length = 0;

  // Set up a connected state (ws must be truthy for netSend)
  vm.runInContext(`
    ws = { readyState: 1, send(s) {} };
    wsRole = 'host';
    handleRelayMsg({type: 'ping', seq: 42});
  `, ctx);

  const pongs = sentMessages.filter(m => m.type === 'pong');
  assertEqual(pongs.length, 1);
  assertEqual(pongs[0].seq, 42);
});

test('handleRelayMsg responds to ping with seq=0 when seq missing', () => {
  const { ctx, sentMessages } = buildSandbox();
  sentMessages.length = 0;

  vm.runInContext(`
    ws = { readyState: 1, send(s) {} };
    wsRole = 'host';
    handleRelayMsg({type: 'ping'});
  `, ctx);

  const pongs = sentMessages.filter(m => m.type === 'pong');
  assertEqual(pongs.length, 1);
  assertEqual(pongs[0].seq, 0);
});

console.log('\nAI gating in networked play');

test('beginTurn does not launch AI when not my turn (HOST, team_l turn)', () => {
  const { ctx } = buildSandbox();

  vm.runInContext(`
    wsRole = 'host';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1; // BUG-02 lock-in
    computerR = false;
    computerL = true; // remote team is AI
    currentTeam = teamL; // it's team_l's turn (remote for HOST)
    initBoard();
    phase = Phase.PLAYING;
  `, ctx);

  // beginTurn should NOT set aiThinking since it's not our turn
  vm.runInContext(`beginTurn(teamL);`, ctx);

  const aiThinking = vm.runInContext(`aiThinking`, ctx);
  assertEqual(aiThinking, false);
});

test('beginTurn launches AI when it IS my turn (HOST, team_r turn, AI)', () => {
  const { ctx } = buildSandbox();

  vm.runInContext(`
    wsRole = 'host';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    computerR = true; // our team is AI
    computerL = false;
    currentTeam = teamR;
    initBoard();
    phase = Phase.PLAYING;
    // Stub launchAI to avoid Worker creation
    launchAI = function() { _testAILaunched = true; };
    var _testAILaunched = false;
  `, ctx);

  vm.runInContext(`beginTurn(teamR);`, ctx);

  const aiThinking = vm.runInContext(`aiThinking`, ctx);
  const aiLaunchedResult = vm.runInContext(`_testAILaunched`, ctx);
  assertEqual(aiThinking, true);
  assertEqual(aiLaunchedResult, true);
});

test('beginTurn launches AI in local mode regardless of team', () => {
  const { ctx } = buildSandbox();

  vm.runInContext(`
    wsRole = 'local';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    computerR = false;
    computerL = true;
    currentTeam = teamL;
    initBoard();
    phase = Phase.PLAYING;
    launchAI = function() { _testAILaunched = true; };
    var _testAILaunched = false;
  `, ctx);

  vm.runInContext(`beginTurn(teamL);`, ctx);

  const aiThinking = vm.runInContext(`aiThinking`, ctx);
  assertEqual(aiThinking, true);
});

console.log('\nColor pick guards');

test('HOST cannot pick row 5 (team_l color)', () => {
  const { ctx, sentMessages } = buildSandbox();

  vm.runInContext(`
    wsRole = 'host';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    selectedRIdx = null; selectedLIdx = null;
    phase = Phase.COLOR_PICK;
  `, ctx);
  sentMessages.length = 0;

  vm.runInContext(`handleColorPickClick([5, 3]);`, ctx);

  const selectedL = vm.runInContext(`selectedLIdx`, ctx);
  assertEqual(selectedL, null);
  const colorMsgs = sentMessages.filter(m => m.type === 'color_chosen');
  assertEqual(colorMsgs.length, 0);
});

test('GUEST cannot pick row 2 (team_r color)', () => {
  const { ctx, sentMessages } = buildSandbox();

  vm.runInContext(`
    wsRole = 'guest';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    selectedRIdx = null; selectedLIdx = null;
    phase = Phase.COLOR_PICK;
  `, ctx);
  sentMessages.length = 0;

  vm.runInContext(`handleColorPickClick([2, 3]);`, ctx);

  const selectedR = vm.runInContext(`selectedRIdx`, ctx);
  assertEqual(selectedR, null);
  const colorMsgs = sentMessages.filter(m => m.type === 'color_chosen');
  assertEqual(colorMsgs.length, 0);
});

test('HOST can pick row 2 and sends color_chosen', () => {
  const { ctx, sentMessages } = buildSandbox();

  vm.runInContext(`
    wsRole = 'host';
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    selectedRIdx = null; selectedLIdx = null;
    localColorSent = false; remoteColorReceived = false;
    phase = Phase.COLOR_PICK;
  `, ctx);
  sentMessages.length = 0;

  vm.runInContext(`handleColorPickClick([2, 5]);`, ctx);

  const selectedR = vm.runInContext(`selectedRIdx`, ctx);
  assertEqual(selectedR, 5);
  const colorMsgs = sentMessages.filter(m => m.type === 'color_chosen');
  assertEqual(colorMsgs.length, 1);
  assertEqual(colorMsgs[0].team_key, 'r');
  assertEqual(colorMsgs[0].color_idx, 5);
});

console.log('\nColor pick rendering (dimming logic)');

test('renderColorPick dims unselected cells on the selected row', () => {
  const { ctx } = buildSandbox();

  // Track lightCell calls
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    selectedRIdx = 3; // team_r picked col 3
    selectedLIdx = null; // team_l hasn't picked yet
    var _lightCalls = [];
    lightCell = function(row,col,r,g,b) { _lightCalls.push({row,col,r,g,b}); };
    phase = Phase.COLOR_PICK;
  `, ctx);

  vm.runInContext(`renderColorPick(0);`, ctx);

  const calls = vm.runInContext(`_lightCalls`, ctx);

  // Row 2 cells: col 3 should be full brightness, others dimmed (quarter)
  const row2calls = calls.filter(c => c.row === 2);
  assert(row2calls.length === 8, `Expected 8 row-2 calls, got ${row2calls.length}`);

  // The selected cell (col 3) should have full palette color
  const selCell = row2calls.find(c => c.col === 3);
  const palette3 = [250, 125, 125]; // Pink
  assertEqual(selCell.r, palette3[0]);
  assertEqual(selCell.g, palette3[1]);
  assertEqual(selCell.b, palette3[2]);

  // An unselected cell (col 0) should be dimmed to quarter brightness
  const unselCell = row2calls.find(c => c.col === 0);
  const palette0 = [64, 180, 232]; // Blue
  assertEqual(unselCell.r, Math.floor(palette0[0] * 0.25));
  assertEqual(unselCell.g, Math.floor(palette0[1] * 0.25));
  assertEqual(unselCell.b, Math.floor(palette0[2] * 0.25));

  // Row 5 cells: none selected, so all should be full brightness
  const row5calls = calls.filter(c => c.row === 5);
  const row5col0 = row5calls.find(c => c.col === 0);
  assertEqual(row5col0.r, palette0[0]);
  assertEqual(row5col0.g, palette0[1]);
  assertEqual(row5col0.b, palette0[2]);
});

// ── Eval bar ──────────────────────────────────────────────────────────────────

console.log('\nEval bar');

test('calcEval returns 0 on starting position (equal material)', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
  `, ctx);
  const ev = vm.runInContext(`calcEval()`, ctx);
  assertEqual(ev, 0);
});

test('calcEval returns correct delta after removing a piece', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
    // Remove teamL queen (value 9) → teamR should lead by 9
    grid[7][3] = null;
  `, ctx);
  const ev = vm.runInContext(`calcEval()`, ctx);
  assertEqual(ev, 9);
});

test('calcEval returns negative when teamR loses a queen', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
    grid[0][3] = null; // remove teamR queen
  `, ctx);
  const ev = vm.runInContext(`calcEval()`, ctx);
  assertEqual(ev, -9);
});

// ── Board themes ──────────────────────────────────────────────────────────────

console.log('\nBoard themes');

test('THEMES object has 5 distinct named themes', () => {
  const { ctx } = buildSandbox();
  const n = vm.runInContext(`Object.keys(THEMES).length`, ctx);
  assertEqual(n, 5);
  const names = vm.runInContext(`Object.values(THEMES).map(t=>t.name).join(',')`, ctx);
  assert(names.includes('Inferno'), 'Missing Inferno theme');
  assert(names.includes('Void'),    'Missing Void theme');
  assert(names.includes('Jade'),    'Missing Jade theme');
  assert(names.includes('Frost'),   'Missing Frost theme');
});

test('Inferno and Default themes have different dark square colors', () => {
  const { ctx } = buildSandbox();
  const diff = vm.runInContext(`THEMES.inferno.dark3d !== THEMES.default.dark3d`, ctx);
  assert(diff, 'Inferno and Default share the same dark3d color');
});

test('applyTheme cycles currentTheme', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`applyTheme('inferno');`, ctx);
  const name = vm.runInContext(`currentThemeObj.name`, ctx);
  assertEqual(name, 'Inferno');
});

// ── Move trails ───────────────────────────────────────────────────────────────

console.log('\nMove trails');

test('addMoveTrail adds from-cell to moveTrails', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    addMoveTrail(3, 2, 3, 5, teamR);
  `, ctx);
  const len = vm.runInContext(`moveTrails.length`, ctx);
  assertEqual(len, 1);
  const hasFrom = vm.runInContext(`moveTrails[0].cells.some(c => c.r === 3 && c.c === 2)`, ctx);
  assert(hasFrom, 'Trail missing from-cell');
});

test('addMoveTrail includes intermediate squares for rook-like moves', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    addMoveTrail(3, 0, 3, 7, teamR); // rook moves across rank
  `, ctx);
  // from (3,0) to (3,7): should include (3,1)...(3,6) as intermediates
  const cellCount = vm.runInContext(`moveTrails[0].cells.length`, ctx);
  assert(cellCount > 2, `Expected >2 cells for 7-square rook move, got ${cellCount}`);
});

test('addMoveTrail for knight (non-sliding) only includes from-cell', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    addMoveTrail(0, 1, 2, 2, teamR); // knight jump
  `, ctx);
  const cellCount = vm.runInContext(`moveTrails[0].cells.length`, ctx);
  assertEqual(cellCount, 1);
});

// ── AI kibitzer ───────────────────────────────────────────────────────────────

console.log('\nAI kibitzer');

test('kibitzer logs capture comment when _pendingKibitz has capture', () => {
  const { ctx } = buildSandbox();
  const logs = [];
  vm.runInContext(`addLog = function(m) { _testSent.push({_log: m}); };`, ctx);

  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
    currentTeam = teamR;
    kibOn = true;
    // Simulate a pawn capture
    _pendingKibitz = {
      piece: grid[1][0],    // teamR pawn
      capture: grid[7][0],  // teamL rook
      fr: 1, fc: 0, tr: 7, tc: 0,
      team: teamR
    };
    _doKibitz(false);
  `, ctx);

  const kibMsgs = sandbox => vm.runInContext(`_testSent`, ctx)
    .filter(m => m._log && m._log.includes('💡'));
  const msgs = vm.runInContext(`_testSent`, ctx).filter(m => m._log && m._log.includes('💡'));
  assert(msgs.length > 0, 'Expected a kibitzer log message for capture');
});

test('kibitzer logs check comment when isCheck=true', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`addLog = function(m) { _testSent.push({_log: m}); };`, ctx);

  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
    currentTeam = teamR;
    kibOn = true;
    _pendingKibitz = {
      piece: grid[0][3],  // queen
      capture: null,
      fr: 0, fc: 3, tr: 4, tc: 3,
      team: teamR
    };
    _doKibitz(true);  // isCheck = true
  `, ctx);

  const msgs = vm.runInContext(`_testSent`, ctx).filter(m => m._log && m._log.includes('Check'));
  assert(msgs.length > 0, 'Expected a Check kibitzer message');
});

test('kibitzer OFF: no comment logged', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`addLog = function(m) { _testSent.push({_log: m}); };`, ctx);

  vm.runInContext(`
    teamR = new Team(64,180,232,'Blue');
    teamL = new Team(190,25,255,'Purple');
    teamR.r += 1;
    initBoard();
    currentTeam = teamR;
    kibOn = false;
    _pendingKibitz = {piece: grid[1][0], capture: grid[7][0], fr:1,fc:0,tr:7,tc:0, team: teamR};
    _doKibitz(false);
  `, ctx);

  const msgs = vm.runInContext(`_testSent`, ctx).filter(m => m._log && m._log.includes('💡'));
  assertEqual(msgs.length, 0);
});

// ── Spectator reactions ───────────────────────────────────────────────────────

console.log('\nSpectator reactions');

test('handleRelayMsg spawns a reaction on reaction message', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    reactions = [];
    handleRelayMsg({type: 'reaction', emoji: '🔥'});
  `, ctx);
  const len = vm.runInContext(`reactions.length`, ctx);
  assertEqual(len, 1);
  const emoji = vm.runInContext(`reactions[0].emoji`, ctx);
  assertEqual(emoji, '🔥');
});

test('spawnReaction uses default emoji when emoji missing', () => {
  const { ctx } = buildSandbox();
  vm.runInContext(`
    reactions = [];
    handleRelayMsg({type: 'reaction'});
  `, ctx);
  const emoji = vm.runInContext(`reactions[0].emoji`, ctx);
  assertEqual(emoji, '🔥');
});

// ── Summary ────────────────────────────────────────────────────────────────
const total = passed + failed;
console.log(`\n${total} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) {
  console.log('Failed tests:');
  failures.forEach(f => console.log(`  - ${f}`));
  process.exit(1);
}
