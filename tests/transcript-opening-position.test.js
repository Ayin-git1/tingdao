const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const opening = html.slice(html.indexOf('  const openingPosition ='), html.indexOf('  // 若该项目正在后台精修'));
const lookup = html.match(/function curHit\([^)]*\)\{[\s\S]*?\n\}/)[0];

test('opening scrolls to saved playback paragraph without changing or starting audio', () => {
  let frame;
  const calls = [];
  const player = {currentTime:0, play(){throw Error('unexpected autoplay');}};
  const context = vm.createContext({d:{last_pos:12}, generation:1, transcriptViewGeneration:1,
    player, segTimes:[0, 5, 10, 20], requestAnimationFrame(fn){frame=fn;},
    followTo(...args){calls.push(args);}});
  vm.runInContext(lookup + opening, context);
  frame();
  assert.deepEqual(calls, [[2, 'instant']]);
  assert.equal(player.currentTime, 0);
});

test('new projects stay at top and stale opening callbacks cannot move another project', () => {
  for(const position of [0, 12]){
    let frame;
    const calls = [];
    const context = vm.createContext({d:{last_pos:position}, generation:1, transcriptViewGeneration:1,
      player:{currentTime:0}, segTimes:[0, 10], requestAnimationFrame(fn){frame=fn;},
      followTo(...args){calls.push(args);}});
    vm.runInContext(lookup + opening, context);
    context.transcriptViewGeneration=2;
    if(frame)frame();
    assert.deepEqual(calls, []);
  }
});
