const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function anchorSlices() {
  const match = html.match(/function transcriptAnchorSlices\(duration\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor slice helper must exist');
  return Function(`${match[0]}; return transcriptAnchorSlices;`)();
}

function activeAnchorIndex() {
  const match = html.match(/function transcriptAnchorIndex\(time,slices\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the active transcript anchor helper must exist');
  return Function(`${match[0]}; return transcriptAnchorIndex;`)();
}

function outlineAnchors() {
  const slicesMatch = html.match(/function transcriptAnchorSlices\(duration\)\{[\s\S]*?\n\}/);
  const match = html.match(/function transcriptOutlineAnchors\(duration,summary,outline\)\{[\s\S]*?\n\}/);
  assert.ok(slicesMatch, 'the transcript anchor slice helper must exist');
  assert.ok(match, 'the transcript outline anchor helper must exist');
  return Function(`${slicesMatch[0]};${match[0]}; return transcriptOutlineAnchors;`)();
}

function outlineNavigationItems() {
  const match = html.match(/function transcriptOutlineNavigationItems\(outline\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript outline navigation helper must exist');
  return Function(`${match[0]}; return transcriptOutlineNavigationItems;`)();
}

function contentItems() {
  const match = html.match(/function transcriptContentItems\(segments,notes,outline\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript content ordering helper must exist');
  return Function(`${match[0]}; return transcriptContentItems;`)();
}

function anchorHoverWidth() {
  const match = html.match(/function transcriptAnchorHoverWidth\(distance\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor hover width helper must exist');
  return Function(`${match[0]}; return transcriptAnchorHoverWidth;`)();
}

function anchorHoverLift() {
  const match = html.match(/function transcriptAnchorHoverLift\(distance\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor hover lift helper must exist');
  return Function(`${match[0]}; return transcriptAnchorHoverLift;`)();
}

function anchorDisplayWidth() {
  const hoverMatch = html.match(/function transcriptAnchorHoverWidth\(distance\)\{[\s\S]*?\n\}/);
  const match = html.match(/function transcriptAnchorDisplayWidth\(index,active,raised\)\{[\s\S]*?\n\}/);
  assert.ok(hoverMatch, 'the transcript anchor hover width helper must exist');
  assert.ok(match, 'the transcript anchor display width helper must exist');
  return Function(`${hoverMatch[0]};${match[0]}; return transcriptAnchorDisplayWidth;`)();
}

function anchorScrollIndex() {
  const indexMatch = html.match(/function transcriptAnchorIndex\(time,slices\)\{[\s\S]*?\n\}/);
  const match = html.match(/function transcriptAnchorScrollIndex\(targetY,segments,slices\)\{[\s\S]*?\n\}/);
  assert.ok(indexMatch, 'the transcript anchor index helper must exist');
  assert.ok(match, 'the transcript anchor scroll helper must exist');
  return Function(`${indexMatch[0]};${match[0]}; return transcriptAnchorScrollIndex;`)();
}

function anchorCanFollowScroll() {
  const match = html.match(/function transcriptAnchorCanFollowScroll\(paused,ended\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor scroll ownership helper must exist');
  return Function(`${match[0]}; return transcriptAnchorCanFollowScroll;`)();
}

function visibleAnchorItems() {
  const match = html.match(/function transcriptAnchorVisibleItems\(anchors,active,nearby\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor visibility helper must exist');
  return Function(`${match[0]}; return transcriptAnchorVisibleItems;`)();
}

function syncAnchorRecording() {
  const match = html.match(/function syncTranscriptAnchorRecording\(rec\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor recording sync helper must exist');
  const rail = {
    classList: {
      values: new Set(),
      toggle(name, force) {
        if (force) this.values.add(name);
        else this.values.delete(name);
      },
      contains(name) {
        return this.values.has(name);
      },
    },
  };
  global.$ = id => {
    assert.equal(id, 'transcriptAnchors');
    return rail;
  };
  const sync = Function(`${match[0]}; return syncTranscriptAnchorRecording;`)();
  return {rail, sync};
}

function functionSource(signature) {
  const start = html.indexOf(signature);
  assert.notEqual(start, -1, `${signature} should exist`);
  const bodyStart = html.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < html.length; index += 1) {
    if (html[index] === '{') depth += 1;
    if (html[index] === '}' && --depth === 0) return html.slice(start, index + 1);
  }
  assert.fail(`${signature} should be complete`);
}

test('anchors appear only after five minutes and divide the recording into five-minute slices', () => {
  // A wrong threshold, a missing last partial slice, or an incorrect slice edge must fail this test.
  const slices = anchorSlices();

  assert.deepEqual(slices(300), []);
  assert.deepEqual(slices(301), [
    {start: 0, end: 300},
    {start: 300, end: 301},
  ]);
  assert.deepEqual(slices(901), [
    {start: 0, end: 300},
    {start: 300, end: 600},
    {start: 600, end: 900},
    {start: 900, end: 901},
  ]);
});

test('the active anchor follows the slice containing the current playback time', () => {
  const slices = anchorSlices()(901);
  const active = activeAnchorIndex();

  assert.equal(active(0, slices), 0);
  assert.equal(active(299.9, slices), 0);
  assert.equal(active(300, slices), 1);
  assert.equal(active(900.9, slices), 3);
});

test('a summarized transcript uses L1 and L2 but not directory-only L3 as anchors', () => {
  // Letting L3 reach the narrow anchor rail would reintroduce the overflow this hierarchy prevents.
  const anchors = outlineAnchors();
  const outline = [
    {t: 0, level: 1, title: '问题全景'},
    {t: 42.4, level: 2, title: '形成原因'},
    {t: 95, level: 3, title: '解决路径'},
  ];

  assert.deepEqual(anchors(180, '# 摘要', outline), [
    {start: 0, end: 42.4, level: 1, title: '问题全景'},
    {start: 42.4, end: 180, level: 2, title: '形成原因'},
  ]);
  assert.deepEqual(anchors(180, '', outline), []);
  assert.deepEqual(anchors(301, '', outline), [
    {start: 0, end: 300},
    {start: 300, end: 301},
  ]);
  assert.match(
    html,
    /renderTranscriptAnchors\(player\.duration,view\.segments,view\.summary,view\.outline\)/,
  );
});

test('outline navigation preserves all three levels and jump times', () => {
  const items = outlineNavigationItems();

  assert.deepEqual(items([
    {t: 0, level: 1, title: '第一章'},
    {t: 42.4, level: 2, title: '第一节'},
    {t: 95, level: 3, title: '案例'},
  ]), [
    {index: 0, start: 0, level: 1, title: '第一章'},
    {index: 1, start: 42.4, level: 2, title: '第一节'},
    {index: 2, start: 95, level: 3, title: '案例'},
  ]);
});

test('chapter anchors expose one shared clickable outline information card', () => {
  const render = html.match(/function renderTranscriptOutlineCard\(rail,items\)\{[\s\S]*?\n\}/);
  assert.ok(render, 'the transcript outline card renderer must exist');
  assert.match(html, /class="brand-info-card info-card"/);
  assert.match(render[0], /className='transcript-outline-card'/);
  assert.doesNotMatch(render[0], /transcript-outline-card info-card/);
  assert.match(render[0], /className='transcript-outline-backdrop'/);
  assert.match(render[0], /card\.append\(backdrop,scroll\)/);
  assert.match(render[0], /className=`transcript-outline-item level-\$\{item\.level\}`/);
  assert.match(render[0], /button\.dataset\.anchorStart=item\.start/);
  assert.match(render[0], /jumpToTranscriptAnchor\(item\.start\)/);
});

test('outline hierarchy indents L2 and L3 while L1 keeps the transcript heading color', () => {
  assert.match(html, /\.transcript-outline-item\.level-1\{[^}]*color:var\(--theme-text\);/);
  assert.match(html, /\.transcript-outline-item\.level-2\{[^}]*padding-left:[^;}]+;/);
  assert.match(html, /\.transcript-outline-item\.level-3\{[^}]*padding-left:[^;}]+;/);
});

test('chapter outline card stays above reading tools but below global popup windows', () => {
  assert.match(html, /\.feedzone\{[^}]*--reading-edge-gap:26px;/);
  assert.match(html, /\.feedwrap\{[^}]*padding:16px var\(--reading-edge-gap\) 20px;/);
  assert.match(html, /\.transcript-anchors\{[^}]*right:14px;/);
  assert.match(html, /\.transcript-outline-card\{[^}]*right:calc\(var\(--reading-edge-gap\) - 14px\);[^}]*width:min\(260px,/);
  assert.match(html, /\.transcript-outline-card\{[^}]*max-height:min\(420px,/);
  assert.match(html, /\.transcript-anchors\.has-outline\{[^}]*z-index:var\(--z-float\);/);
  assert.match(html, /--z-selbar:46;/);
  assert.match(html, /--z-float:50;/);
  assert.match(html, /--z-setpop:55;/);
  assert.match(html, /--z-pop-lift:57;/);
});

test('chapter outline card uses the shared neutral material surface', () => {
  const card = html.match(/\.transcript-outline-card\{[^}]*\}/);
  assert.ok(card, 'the outline card style must exist');
  const scroll = html.match(/\.transcript-outline-scroll\{[^}]*\}/);
  assert.ok(scroll, 'the outline card scroll surface must exist');
  assert.match(scroll[0], /background:var\(--material-rest-background\)/);
  assert.match(scroll[0], /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(scroll[0], /-webkit-backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(scroll[0], /box-shadow:var\(--material-shadow-level-2\)/);
  assert.doesNotMatch(scroll[0], /background:rgba\(/);
  assert.match(card[0], /pointer-events:none/);
});

test('chapter outline backdrop is a standalone card layer and reaches the app shell edge', () => {
  const backdrop = html.match(/\.transcript-outline-backdrop\{[^}]*\}/);
  assert.ok(backdrop, 'the standalone outline backdrop must exist');
  assert.match(backdrop[0], /position:absolute/);
  assert.match(backdrop[0], /z-index:0/);
  // Extend past the viewport top without clipping at the feed boundary.
  assert.match(html, /\.feedzone\.has-transcript-anchors\{overflow:visible;\}/);
  assert.match(html, /\.topbar\{[^}]*z-index:var\(--z-topbar\)/);
  assert.match(html, /--z-topbar:53;/);
  // The 46px backdrop extension covers the 26px gap (14px rail inset + 12px card inset).
  assert.match(backdrop[0], /inset:-100vh -46px -84px -260px/);
  assert.match(backdrop[0], /pointer-events:none/);
  assert.match(backdrop[0], /background:rgba\(255,255,255,\.08\)/);
  assert.match(backdrop[0], /backdrop-filter:blur\(18px\) saturate\(\.82\)/);
  assert.match(backdrop[0], /-webkit-backdrop-filter:blur\(18px\) saturate\(\.82\)/);
  const scroll = html.match(/\.transcript-outline-scroll\{[^}]*\}/);
  assert.ok(scroll, 'the outline content layer must exist');
  assert.match(scroll[0], /position:relative/);
  assert.match(scroll[0], /z-index:1/);
});

test('chapter outline backdrop fades from the shell right toward a longer transparent left edge', () => {
  const backdrop = html.match(/\.transcript-outline-backdrop\{[^}]*\}/);
  assert.ok(backdrop, 'the standalone outline backdrop must exist');
  assert.match(backdrop[0], /mask-image:linear-gradient\(to left,#000 0%,#000 30%,rgba\(0,0,0,\.28\) 65%,transparent 100%\)/);
  assert.match(backdrop[0], /-webkit-mask-image:linear-gradient\(to left,#000 0%,#000 30%,rgba\(0,0,0,\.28\) 65%,transparent 100%\)/);
  assert.doesNotMatch(html, /\.transcript-anchors\.has-outline::before/);
});

test('dark mode keeps chapter outline backdrop and shadow black', () => {
  const backdrop = html.match(/html\[data-appearance="dark"\] \.transcript-outline-backdrop\{[^}]*\}/);
  const scroll = html.match(/html\[data-appearance="dark"\] \.transcript-outline-scroll\{[^}]*\}/);
  assert.ok(backdrop, 'dark outline backdrop override must exist');
  assert.ok(scroll, 'dark outline scroll override must exist');
  assert.match(backdrop[0], /background:rgba\(0,0,0,\.28\)/);
  assert.match(scroll[0], /box-shadow:var\(--material-shadow-level-2\)/);
});

test('chapter outline backdrop fades first and faster than the directory surface', () => {
  const card = html.match(/\.transcript-outline-card\{[^}]*\}/);
  const backdrop = html.match(/\.transcript-outline-backdrop\{[^}]*\}/);
  const scroll = html.match(/\.transcript-outline-scroll\{[^}]*\}/);
  const backdropOpen = html.match(/\.transcript-anchors\.has-outline:hover \.transcript-outline-backdrop,[\s\S]*?\{[^}]*\}/);
  const scrollOpen = html.match(/\.transcript-anchors\.has-outline:hover \.transcript-outline-scroll,[\s\S]*?\{[^}]*\}/);
  assert.ok(card && backdrop && scroll && backdropOpen && scrollOpen, 'all outline animation layers must exist');
  assert.doesNotMatch(card[0], /opacity:|visibility:|transition:/);
  assert.match(backdrop[0], /opacity:0/);
  assert.match(backdrop[0], /transition:opacity \.08s ease-in/);
  assert.match(backdropOpen[0], /opacity:1/);
  assert.match(backdropOpen[0], /transition-duration:\.06s/);
  assert.match(scroll[0], /opacity:0/);
  assert.match(scroll[0], /visibility:hidden/);
  assert.match(scrollOpen[0], /opacity:1/);
  assert.match(scrollOpen[0], /transition-delay:\.025s,\.025s,0s/);
});

test('chapter outline does not install a reading-area or full-page fog element', () => {
  assert.doesNotMatch(html, /id="transcriptOutlineBackdrop"/);
  assert.doesNotMatch(html, /body\.transcript-outline-open/);
});

test('the playing anchor also marks the matching outline title', () => {
  const active = functionSource('function setTranscriptAnchorActiveIndex(');
  assert.match(active, /updateTranscriptOutlineActive\(time\)/);
});

test('directory position follows third-level timestamps independently of chapter anchors', () => {
  const items = [0, 30, 45, 60, 100].map(start => ({
    dataset: {anchorStart:String(start)}, active:false,
    classList:{toggle(name,value){ items.find(item=>item.classList===this).active=value; }},
    setAttribute(name,value){ this[name]=value; },
  }));
  const update = Function('document', `${functionSource('function updateTranscriptOutlineActive(')}; return updateTranscriptOutlineActive;`)({querySelectorAll(){return items;}});
  for(const [time,index] of [[0,0],[30,1],[45,2],[59,2],[60,3],[105,4],[35,1]]){
    update(time);
    assert.deepEqual(items.map(item=>item.active), items.map((_,i)=>i===index));
    assert.equal(items[index]['aria-current'],'true');
  }
});

test('scrolling updates directory position even within the same chapter anchor', () => {
  const harness = Function(`
    const transcriptAnchorState=[{start:0,end:100}], transcriptAnchorActiveIndex=0;
    const player={paused:true,ended:false};
    const segEls=[{dataset:{t:'0'},getBoundingClientRect(){return {top:0};}},
      {dataset:{t:'45'},getBoundingClientRect(){return {top:80};}}];
    function $(){return {clientHeight:250,getBoundingClientRect(){return {top:0};}};}
    let position=-1;
    function updateTranscriptOutlineActive(time){position=time;}
    function setTranscriptAnchorActiveIndex(){throw new Error('chapter anchor did not change');}
    ${functionSource('function transcriptAnchorCanFollowScroll(')}
    ${functionSource('function transcriptAnchorIndex(')}
    ${functionSource('function transcriptAnchorScrollIndex(')}
    ${functionSource('function updateTranscriptAnchorFromScroll(')}
    return {update:updateTranscriptAnchorFromScroll,position:()=>position};
  `)();
  harness.update();
  assert.equal(harness.position(),45);
});

test('current directory title uses an inset theme dot without an active background', () => {
  assert.doesNotMatch(html, /\.transcript-outline-item\.active\{[^}]*background:/);
  assert.match(html, /\.transcript-outline-item\.active::before\{[^}]*width:6px;[^}]*border-radius:50%;[^}]*background:var\(--g\);/);
  assert.match(html, /\.transcript-outline-item\.level-3\.active::before\{left:36px;/);
});

test('only L1 and L2 headings are inserted before transcript text at the same timestamp', () => {
  const items = contentItems();
  const ordered = items(
    [{t: 0, text: '开场'}, {t: 42.4, text: '正文'}],
    [{t: 42.4, text: '笔记'}],
    [
      {t: 0, level: 1, title: '第一章'},
      {t: 42.4, level: 2, title: '第一节'},
      {t: 42.4, level: 3, title: '仅目录案例'},
    ],
  );

  assert.deepEqual(ordered.map(item => [item.type, item.t]), [
    ['heading', 0], ['seg', 0], ['heading', 42.4], ['seg', 42.4], ['note', 42.4],
  ]);
});

test('the normalized transcript renderer keeps L1 as H2 and L2 as H4', () => {
  const render = html.match(/function addTranscriptHeading\(heading\)\{[\s\S]*?\n\}/);
  assert.ok(render, 'the transcript heading renderer must exist');
  assert.match(render[0], /const level=Number\(heading\.level\)===1\?2:4;/);
});

test('transcript heading hierarchy, colors, and chapter preview follow the transcript type scale', () => {
  const h2 = html.match(/\.transcript-heading-h2 h2\{[^}]*font-size:calc\(var\(--transcript-font-size\) \+ (\d+)px\);[^}]*font-weight:700;/);
  const h4 = html.match(/\.transcript-heading-h4 h4\{[^}]*font-size:calc\(var\(--transcript-font-size\) \+ (\d+)px\);[^}]*font-weight:700;/);
  assert.ok(h2 && h4, 'both heading levels must scale from the transcript font and stay bold');
  assert.ok(Number(h2[1]) > Number(h4[1]) && Number(h4[1]) > 0);
  assert.match(html, /\.transcript-heading-h4 h4\{[^}]*color:var\(--heading-ink\);/);
  assert.match(html, /\.transcript-anchor\.is-chapter \.transcript-anchor-preview span\{[^}]*font-size:var\(--fs-body\);[^}]*font-weight:700;/);
});

test('H2 headings use a translucent theme-color marker across their lower third', () => {
  assert.match(html, /\.transcript-heading-h2 h2\{[^}]*position:relative;[^}]*width:fit-content;[^}]*isolation:isolate;/);
  assert.match(html, /\.transcript-heading-h2 h2::after\{[^}]*content:'';[^}]*position:absolute;[^}]*z-index:-1;[^}]*left:-\.06em;[^}]*right:-\.06em;[^}]*bottom:\.08em;[^}]*height:\.36em;/);
  const marker = html.match(/\.transcript-heading-h2 h2::after\{[^}]*\}/);
  assert.ok(marker, 'the H2 marker style must exist');
  assert.match(marker[0], /background:rgba\(var\(--g-rgb\),\.28\);/);
  assert.match(marker[0], /pointer-events:none;/);
  assert.doesNotMatch(marker[0], /border-radius|clip-path|transform:/);
});

test('transcript headings hide their timestamp and use the full transcript width', () => {
  const render = html.match(/function addTranscriptHeading\(heading\)\{[\s\S]*?\n\}/);
  assert.ok(render, 'the transcript heading renderer must exist');
  assert.doesNotMatch(render[0], /class="ts"/);
  assert.match(html, /\.transcript-heading\{[^}]*display:block;/);
  assert.match(html, /--theme-text:/);
  assert.match(html, /'--theme-text':hsl\(/);
  assert.match(html, /\.transcript-heading\{[^}]*color:var\(--theme-text\);/);
  assert.doesNotMatch(html, /\.transcript-heading h2,\.transcript-heading h4\{[^}]*grid-column:2;/);
});

test('anchor previews put the content line above the time label', () => {
  const render = html.match(/function renderTranscriptAnchors\(duration,segments,summary,outline,activeOverride\)\{[\s\S]*?\n\}/);
  assert.ok(render, 'the transcript anchor renderer must exist');
  assert.match(
    render[0],
    /transcript-anchor-preview"><span>\$\{esc\([\s\S]*?<\/span><b>\$\{label\}<\/b>/,
  );
});

test('hovering one anchor pulls nearby anchors into a rounded symmetric shape', () => {
  const width = anchorHoverWidth();
  const lift = anchorHoverLift();

  assert.deepEqual([0, 1, 2, 3, 4].map(width), [24, 22.9, 19.6, 14.7, 9]);
  assert.deepEqual([0, 1, 2, 3, 4].map(lift), [1.5, 1.39, 1.06, 0.57, 0]);
  assert.equal(width(-1), width(1));
  assert.equal(lift(-1), lift(1));
  assert.equal(width(5), 9);
  assert.equal(lift(5), 0);
  assert.match(html, /anchor\.style\.setProperty\('--anchor-offset',`\$\{-lift\}px`\)/);
  assert.match(html, /\.transcript-anchor\.active::before\{background:var\(--g\); opacity:1;/);
});

test('the playback anchor keeps its width while the hover center moves', () => {
  const width = anchorDisplayWidth();

  assert.deepEqual([0, 1, 2, 3, 4].map(raised => width(2, 2, raised)), [20, 20, 20, 20, 20]);
  assert.equal(width(0, 2, 0), 24);
  assert.equal(width(1, 2, -1), 8);
});

test('anchor hit targets cover the visual spacing without gaps', () => {
  assert.match(html, /\.transcript-anchors\{[^}]*gap:0;/);
  assert.match(html, /\.transcript-anchor\{[^}]*height:11px;/);
});

test('hover lift moves only the line and not its pointer hit target', () => {
  assert.doesNotMatch(html, /\.transcript-anchor\{[^}]*transform:translateY\(var\(--anchor-offset,0px\)\)/);
  assert.match(html, /\.transcript-anchor::before\{[^}]*transform:translateY\(var\(--anchor-offset,0px\)\)/);
});

test('scrolling the transcript selects the anchor at the reading position', () => {
  const slices = anchorSlices()(901);
  const atScroll = anchorScrollIndex();
  const segments = [
    {top: 100, t: 0},
    {top: 220, t: 301},
    {top: 420, t: 605},
  ];

  assert.equal(atScroll(100, segments, slices), 0);
  assert.equal(atScroll(219, segments, slices), 0);
  assert.equal(atScroll(220, segments, slices), 1);
  assert.equal(atScroll(500, segments, slices), 2);
  assert.match(html, /\$\('feedwrap'\)\.addEventListener\('scroll',scrollFrameUpdate\(updateTranscriptAnchorFromScroll\)/);
});

test('scroll position cannot replace the playback anchor while audio is playing', () => {
  const canFollowScroll = anchorCanFollowScroll();

  assert.equal(canFollowScroll(false, false), false);
  assert.equal(canFollowScroll(true, false), true);
  assert.equal(canFollowScroll(false, true), true);
});

test('a crowded outline keeps nearby H1 anchors and expands only the current H1', () => {
  const visible = visibleAnchorItems();
  const anchors = [
    {level: 1, title: '一'}, {level: 2, title: '一甲'},
    {level: 1, title: '二'}, {level: 2, title: '二甲'},
    {level: 1, title: '三'}, {level: 2, title: '三甲'}, {level: 2, title: '三乙'},
    {level: 1, title: '四'}, {level: 2, title: '四甲'},
    {level: 1, title: '五'}, {level: 2, title: '五甲'},
    {level: 1, title: '六'},
    {level: 1, title: '七'},
  ];

  assert.deepEqual(visible(anchors, 7, 2), [
    {type: 'more', direction: 'before'},
    {type: 'anchor', index: 2}, {type: 'anchor', index: 4},
    {type: 'anchor', index: 7}, {type: 'anchor', index: 8},
    {type: 'anchor', index: 9}, {type: 'anchor', index: 11},
    {type: 'more', direction: 'after'},
  ]);
});

test('an H1 selection restores its own H2 anchors and has no overflow markers when all H1 fit', () => {
  const visible = visibleAnchorItems();
  const anchors = [
    {level: 1, title: '一'}, {level: 2, title: '一甲'},
    {level: 1, title: '二'}, {level: 2, title: '二甲'},
    {level: 1, title: '三'},
  ];

  assert.deepEqual(visible(anchors, 0, 2), [
    {type: 'anchor', index: 0}, {type: 'anchor', index: 1},
    {type: 'anchor', index: 2}, {type: 'anchor', index: 4},
  ]);
});

test('the current H1 remains selected when its H2 is the active anchor', () => {
  assert.match(html, /classList\.toggle\('active-h1',index===activeH1\)/);
  assert.match(html, /\.transcript-anchor\.active-h1:not\(\.active\)::before\{/);
});

test('recording moves transcript anchors out of the interactive layer and restores them afterward', () => {
  // A missing recording-state sync, a stale class, or a one-way toggle must fail this test.
  const {rail, sync} = syncAnchorRecording();

  sync(true);
  assert.equal(rail.classList.contains('recording'), true);

  sync(false);
  assert.equal(rail.classList.contains('recording'), false);
});

test('recording anchor styling disables pointer interaction in the lower layer', () => {
  assert.match(
    html,
    /\.transcript-anchors\.recording\{[^}]*z-index:var\(--z-inset\);[^}]*pointer-events:none;[^}]*visibility:hidden;/,
  );
});

test('exiting a manuscript clears the transcript anchor rail and its state', () => {
  const source = html.match(/function clearTranscriptAnchors\(\)\{[\s\S]*?\n\}/);
  assert.ok(source, 'the transcript anchor cleanup helper must exist');
  assert.match(functionSource('function exitView()'), /clearTranscriptAnchors\(\)/);
  const harness = Function(`
    let transcriptAnchorState = [{start: 0}];
    let transcriptAnchorActiveIndex = 2;
    let transcriptAnchorRenderArgs = [300];
    let transcriptAnchorHoverIndex = 1;
    let transcriptAnchorFocusIndex = 3;
    const rail = {
      hidden: false,
      replaced: false,
      removed: [],
      classList: {remove(...names){ this.removed = names; }},
      replaceChildren(){ this.replaced = true; },
      removeAttribute(name){ this.removedAttribute = name; },
    };
    const feedzone = {classList: {removed: [], remove(...names){ this.removed = names; }}};
    function $(id){ return id === 'transcriptAnchors' ? rail : feedzone; }
    ${source[0]}
    return {
      clear: clearTranscriptAnchors,
      rail,
      feedzone,
      state: () => ({transcriptAnchorState, transcriptAnchorActiveIndex,
        transcriptAnchorRenderArgs, transcriptAnchorHoverIndex, transcriptAnchorFocusIndex}),
    };
  `)();

  harness.clear();

  assert.equal(harness.rail.hidden, true);
  assert.equal(harness.rail.replaced, true);
  assert.deepEqual(harness.rail.classList.removed, ['has-outline', 'recording']);
  assert.equal(harness.rail.removedAttribute, 'data-anchor-window');
  assert.deepEqual(harness.feedzone.classList.removed, ['has-transcript-anchors']);
  assert.deepEqual(harness.state(), {
    transcriptAnchorState: [],
    transcriptAnchorActiveIndex: -1,
    transcriptAnchorRenderArgs: null,
    transcriptAnchorHoverIndex: -1,
    transcriptAnchorFocusIndex: -1,
  });
});

test('chapter navigation does not start stale audio for a manuscript without audio', () => {
  const source = functionSource('function jumpToTranscriptAnchor(');
  let played = 0;
  let currentTime = 17;
  global.view = {id: 'text-only', audioUrl: ''};
  global.player = {
    get currentTime() { return currentTime; },
    set currentTime(value) { currentTime = value; },
    getAttribute() { return '/audio/previous-project.wav'; },
    play() { played += 1; },
  };
  global.posDirty = false;
  global.hideResume = () => {};
  global.updateTranscriptAnchorActive = () => {};

  const jumpToTranscriptAnchor = Function(`${source}; return jumpToTranscriptAnchor;`)();
  jumpToTranscriptAnchor(120);

  assert.equal(played, 0);
  assert.equal(currentTime, 17);
});

test('clearing a project audio source unloads the previous media resource', () => {
  const source = functionSource('function clearPlayerSource(');
  const calls = [];
  global.stopPlaybackBoost = () => calls.push('stopBoost');
  global.syncPlayerUI = () => calls.push('syncUI');
  global.player = {
    pause() { calls.push('pause'); },
    removeAttribute(name) { calls.push(`remove:${name}`); },
    load() { calls.push('load'); },
  };

  const clearPlayerSource = Function(`${source}; return clearPlayerSource;`)();
  clearPlayerSource();

  assert.deepEqual(calls, ['stopBoost', 'pause', 'remove:src', 'load', 'syncUI']);
  assert.match(functionSource('async function loadSession(sid, keepList)'), /clearPlayerSource\(\)/);
  assert.match(functionSource('function exitView()'), /clearPlayerSource\(\)/);
});

test('paused media updates preserve reading navigation and playback immediately takes over', () => {
  const source = functionSource('function updateTranscriptAnchorActive(time)');
  const indexSource = functionSource('function transcriptAnchorIndex(time,slices)');
  const harness = Function(`
    const player = {paused:true, ended:false};
    const transcriptAnchorState = [{start:0,end:100},{start:100,end:200}];
    let active = -1;
    function setTranscriptAnchorActiveIndex(index){ active = index; }
    function updateTranscriptAnchorFromScroll(){ active = 0; }
    ${functionSource('function transcriptAnchorCanFollowScroll(')}
    ${indexSource}
    ${source}
    return {player, update:updateTranscriptAnchorActive, active:()=>active};
  `)();
  harness.update(150);
  assert.equal(harness.active(), 0);
  harness.player.paused = false;
  harness.update(150);
  assert.equal(harness.active(), 1);
  harness.player.ended = true;
  harness.update(200);
  assert.equal(harness.active(), 0);
});

test('play, pause and initial render synchronize directory navigation with their position source', () => {
  assert.match(html.match(/player.onplay = .*;/)[0], /updateTranscriptAnchorActive\(player.currentTime\)/);
  assert.match(html.match(/player.onpause = .*;/)[0], /updateTranscriptAnchorFromScroll\(\)/);
  const render = functionSource('function renderTranscriptAnchors(');
  assert.match(render, /if\(!Number.isInteger\(activeOverride\)\) updateTranscriptAnchorFromScroll\(\)/);
});

test('opening the outline centers the title for playback or the visible reading position', () => {
  const source = functionSource('function centerTranscriptOutline(');
  const buttons = [0, 100, 150].map(t => ({dataset:{anchorStart:String(t)}, offsetHeight:30,
    getBoundingClientRect(){return {top:300+t,height:30};}}));
  const scroll = {clientHeight:200, scrollHeight:500, offsetHeight:202, scrollTop:0, style:{},
    querySelectorAll(){return buttons;}, getBoundingClientRect(){return {top:200};}};
  const harness = Function('scroll','buttons', `
    const player={paused:false,ended:false,currentTime:160};
    const segEls=[{dataset:{t:'0'},getBoundingClientRect(){return {top:0};}},
      {dataset:{t:'110'},getBoundingClientRect(){return {top:100};}}];
    const wrap={clientHeight:500,getBoundingClientRect(){return {top:0};}};
    const rail={querySelector(){return scroll;}};
    function $(id){return id==='feedwrap'?wrap:rail;}
    function updateTranscriptAnchorActive(){}
    ${functionSource('function transcriptAnchorCanFollowScroll(')}
    ${source}
    return {player,center:centerTranscriptOutline};
  `)(scroll,buttons);
  harness.center();
  assert.equal(scroll.scrollTop,165);
  scroll.scrollTop=0;
  harness.player.paused=true;
  harness.center();
  assert.equal(scroll.scrollTop,115);
  harness.player.paused=false;
  harness.player.currentTime=0;
  buttons[0].getBoundingClientRect=()=>({top:210,height:30});
  scroll.scrollTop=0;
  harness.center();
  assert.equal(scroll.scrollTop,0, 'the first title stays at the natural top');
  harness.player.currentTime=160;
  scroll.scrollHeight=300;
  scroll.scrollTop=0;
  harness.center();
  assert.equal(scroll.scrollTop,100, 'the last title stops at the natural bottom');
  assert.deepEqual(scroll.style, {}, 'centering must not add height or artificial padding');
  assert.match(html, /addEventListener\('mouseenter',centerTranscriptOutline\)/);
  assert.match(html, /addEventListener\('focusin'/);
});
