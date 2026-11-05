const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function setup(){
  let focused=true,next=0;const frames=new Map(),timers=new Map(),nodes=new Map(),events={};
  function node(){const classes=new Set();return {hidden:false,style:{},inert:false,events:{},classList:{contains:c=>classes.has(c),add:c=>classes.add(c),remove:c=>classes.delete(c),toggle(c,v){v?classes.add(c):classes.delete(c);}},setAttribute(){},matches(){return false;},querySelector(){return null;},addEventListener(t,f){this.events[t]=f;}};}
  const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const document={body:node(),hasFocus:()=>focused,addEventListener(t,f){events['document:'+t]=f;}};
  const c=vm.createContext({$,document,window:{addEventListener(t,f){events['window:'+t]=f;}},musicImporting:false,musicDrag:null,musicCloseTimer:0,musicOpenFrame:0,musicPlace(){},musicVolumeOpen(){},requestAnimationFrame(f){frames.set(++next,f);return next;},cancelAnimationFrame(id){frames.delete(id);},setTimeout(f){timers.set(++next,f);return next;},clearTimeout(id){timers.delete(id);}});
  vm.runInContext(html.slice(html.indexOf('function musicSetOpen('),html.indexOf('function musicSyncFollow(')),c);
  vm.runInContext(html.slice(html.indexOf('(function wireMusic(){'),html.indexOf('  new ResizeObserver',html.indexOf('(function wireMusic(){')))+'})();',c);
  return {c,$,events,focus(v){focused=v;},flush(){for(const [id,f] of [...frames]){frames.delete(id);f();}},timers(){for(const [id,f] of [...timers]){timers.delete(id);f();}}};
}
test('closing before the opening frame cannot reopen the panel',()=>{const h=setup();h.c.musicSetOpen(true);h.c.musicSetOpen(false);h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),false);});
test('window blur closes the floating panel and ignores synthetic hover until focused',()=>{const h=setup();h.c.musicSetOpen(true);h.flush();h.focus(false);h.events['window:blur']?.();h.$('musicPanel').events.pointerenter();h.$('musicBookmark').events.pointermove();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),false);h.focus(true);h.$('musicBookmark').events.pointermove();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),true);});
test('leaving the document closes the panel even with stale hover state',()=>{const h=setup();h.c.musicSetOpen(true);h.flush();h.$('musicPanel').matches=()=>true;h.events['document:pointerleave']?.();h.timers();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),false);});
test('music panel colors use theme variables',()=>{const css=html.slice(html.indexOf('#musicPanel .spread{'),html.indexOf('#musicBookmark{'));assert.equal(/#[0-9a-f]{3,8}\b/i.test(css),false,'hardcoded colors remain in the player');});
test('importing and dragging keep the panel open while native interactions finish',()=>{for(const field of ['musicImporting','musicDrag']){const h=setup();h.c.musicSetOpen(true);h.flush();h.c[field]=true;h.focus(false);h.events['window:blur']();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),true);}});
test('returning before the close delay keeps the panel open',()=>{const h=setup();h.c.musicSetOpen(true);h.flush();h.$('musicPanel').events.pointerleave();h.$('musicPanel').events.pointerenter();h.timers();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),true);});

test('layout-generated pointerenter cannot reopen a closing panel',()=>{const h=setup();h.c.musicSetOpen(true);h.flush();h.c.musicSetOpen(false);for(let i=0;i<5;i++){h.$('musicBookmark').events.pointerenter?.();h.$('musicPanel').events.pointerenter();h.flush();h.timers();assert.equal(h.$('musicPanel').classList.contains('open'),false);}h.$('musicBookmark').events.pointermove?.();h.flush();assert.equal(h.$('musicPanel').classList.contains('open'),true);});
test('expanded music bookmark retains its hover hit area',()=>{assert.doesNotMatch(html,/#musicBookmark\[aria-expanded="true"\]\{pointer-events:none;/);});
