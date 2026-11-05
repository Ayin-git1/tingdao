// 由桌面壳注入；复用页面动作，不依赖补丁修改 index.html。
(() => {
  if (location.hostname !== '127.0.0.1' || !location.port) return;
  const el = id => document.getElementById(id);
  const click = id => el(id)?.click();
  const available = id => {
    const node = el(id);
    return !!node && !node.hidden && !node.disabled && node.style.display !== 'none';
  };
  function snapshot() {
    const idle = state === 'idle' && !recordLoadingBusy;
    const recording = ['recording', 'paused'].includes(state) && !recordLoadingBusy;
    const modal = !!document.querySelector('.modal.show,#transcriptNoteLayer:not([hidden])');
    const typing = typingHere({target:document.activeElement});
    const locksProject = job => !!job && ['run','wait'].includes(job.state) && ['refine','import','cloud'].includes(job.kind);
    const project = idle && !!view && !locksProject(jobs[view.id]);
    const audio = project && !!player.getAttribute('src');
    const busy = !!(view && jobs[view.id]);
    const item = view && lastHistRaw.find(item => item.id === view.id);
    const hasNote = project && !!view.hasNote;
    const entry = (enabled = true, text, checked) => ({enabled:!!enabled && !modal, ...(text ? {text} : {}), ...(checked === undefined ? {} : {checked:!!checked})});
    const result = {
      about:entry(), settings:entry(), update:entry(),
      'import-media':entry(idle), 'import-note':entry(idle), rename:entry(project),
      favorite:entry(project, item?.favorite ? '取消收藏' : '收藏'),
      'group-choose':entry(project), 'group-remove':entry(project),
      'export-bundle':entry((selected.size ? [...selected].every(id=>!locksProject(jobs[id])) : project) && idle && !exportBusy,
        selected.size ? '导出选中项目的完整笔记…' : '导出完整笔记…'),
      'copy-md':entry(project), 'copy-plain':entry(project), reveal:entry(project), archive:entry(project),
      search:entry(idle), find:entry(project), replace:entry(project),
      'cloud-transcribe':entry(project && !busy && cloudOK && available('btnCloud')),
      'cloud-refine':entry(project && !busy && cloudOK && available('btnCloud')),
      summary:entry(project && !busy && cloudOK, view?.summary ? '重新生成摘要目录…' : '生成摘要目录…'),
      silence:entry(project && !busy && available('btnSilence')),
      home:entry(idle), 'show-favorites':entry(idle), 'show-archive':entry(idle),
      sidebar:entry(idle, document.body.classList.contains('sidehide') ? '显示项目栏' : '隐藏项目栏'),
      drawer:entry(hasNote, drawerOpen() ? '隐藏课后笔记' : '显示课后笔记'),
      'all-notes':entry(project && available('btnAllNotes')),
      music:entry(available('musicBookmark')), review:entry(available('reviewBookmark')),
      'record-start':entry(idle && !typing), 'record-pause':entry(recording, state === 'paused' ? '继续录音' : '暂停录音'),
      'record-stop':entry(recording), microphone_modes:entry(recording), hotwords:entry(),
      play:entry(audio, player.paused ? '播放' : '暂停'), previous:entry(audio), next:entry(audio),
      'note-add':entry((project && view.segments?.some(segment=>segment.text)) || recording), 'note-photo':entry(recording && available('btnCamTool') && !recordingImageStopping),
      'note-generate':entry(project && !busy && cloudOK && !hasNote),
      'note-regenerate':entry(hasNote && !busy && cloudOK), 'note-copy':entry(hasNote && !busy), keys:entry(),
    };
    for (const source of ['system','mic','mix']) result['source-'+source] = entry((idle || recording) && !sourcePending, null, (recording ? recMode : mode) === source);
    RATES.forEach((rate,index) => { result['rate-'+index] = entry(audio, null, rateIdx === index); });
    // 录音快捷键可在设置里修改，原生菜单跟随保存值。
    result['record-start'].accelerator = `CmdOrCtrl+${recordStartShortcut.shift ? 'Shift+' : ''}${recordStartShortcut.key.toUpperCase()}`;
    return result;
  }
  function openSettings(section) {
    if (!el('setpop').classList.contains('show')) click('btnSet');
    if (section) gotoSec(section);
  }
  function chooseGroup() {
    openItemMenu(view.id, null, el('nameInput'));
    showMv();
    el('mvQuery').focus();
  }
  const actions = {
    about:()=>openSettings('about'), settings:()=>openSettings(), update:()=>{openSettings('about');checkForUpdate(true);},
    'import-media':()=>click('btnImport'), 'import-note':()=>click('btnImportNote'),
    rename:()=>{ el('nameInput').focus(); el('nameInput').select(); },
    favorite:()=>setSessionFlags([view.id], {favorite:!lastHistRaw.find(item=>item.id===view.id)?.favorite}),
    'group-choose':chooseGroup, 'group-remove':()=>{menuCtx={id:view.id};moveToGroup('');},
    'export-bundle':()=>exportSessions(selected.size ? [...selected] : [view.id]),
    'copy-md':()=>copyAs('md'), 'copy-plain':()=>copyPlain(), reveal:()=>click('btnReveal'), archive:()=>click('btnDel'),
    search:()=>click('btnHistSearch'), find:()=>{if(!findOpen())click('btnFind');else el('findInput').focus();},
    replace:()=>{if(!findOpen())click('btnFind');if(el('findRepRow').hidden)click('findReplToggle');else el('replaceInput').focus();},
    // 先展示既有确认界面，用户确认后才上传录音或发起处理。
    'cloud-transcribe':()=>{click('btnCloud');el('clGo').focus();}, 'cloud-refine':()=>{click('btnCloud');el('clRefine').focus();},
    summary:()=>generateSummary(view.id, !!view.summary), silence:()=>click('btnSilence'),
    home:()=>click('btnHome'), 'show-favorites':()=>navigateToSection('favorites'), 'show-archive':()=>navigateToSection('archive'),
    sidebar:()=>click('btnSide'), drawer:()=>openDrawer(!drawerOpen()), 'all-notes':()=>openAllNotes(),
    music:()=>musicSetOpen(true), review:()=>reviewSetOpen(true),
    'record-start':()=>click('fab'), 'record-pause':()=>click('btnPause'), 'record-stop':()=>click('fab'),
    hotwords:()=>openSettings('hw'), play:()=>click('btnPlay'), previous:()=>jumpLine(-1), next:()=>jumpLine(1),
    'note-add':()=>{
      if(state !== 'idle'){click('btnNoteTool');return;}
      const rows=[...el('feed').querySelectorAll('.seg[data-t]')].filter(row=>!row.classList.contains('note'));
      const row=rows.filter(row=>Number(row.dataset.t)<=(player.currentTime||0)).pop() || rows[0];
      if(row){transcriptNoteTargetRow=row;openTranscriptNote(Number(row.dataset.t));}
    },
    'note-photo':()=>openIphoneCamera(true),
    'note-generate':()=>openTplPop('gen',el('nameInput')), 'note-regenerate':()=>openTplPop('gen',el('nameInput')),
    'note-copy':()=>click('noteCopy'), keys:()=>openKeyCard(),
  };
  for (const source of ['system','mic','mix']) actions['source-'+source] = ()=>{
    const selector = state === 'idle' ? `#setMode button[data-v="${source}"]` : `#srcfan [data-src="${source}"]`;
    document.querySelector(selector)?.click();
  };
  [0,1,2,3,4].forEach(index=>{actions['rate-'+index]=()=>document.querySelector(`#ratefan [data-v="${RATES[index]}"]`)?.click();});
  function dispatch(id) {
    if (!snapshot()[id]?.enabled || !actions[id]) return;
    actions[id]();
    previous = ''; // 原生勾选项会先自行翻转，即使仍选同一档也要校正。
    sync();
  }
  let previous = '', frame;
  function sync() {
    try {
      const current = JSON.stringify(snapshot());
      if (current === previous) return;
      if (!frame) { frame=document.createElement('iframe');frame.hidden=true;document.body.appendChild(frame); }
      frame.src='tingdao-menu://state?data='+encodeURIComponent(current);
      previous=current;
    } catch (_) { /* 页面加载期间全局状态尚未初始化，下一轮再同步。 */ }
  }
  window.tingdaoNativeMenu = {snapshot,dispatch};
  // 原生菜单通常会消费快捷键；若 WebView 仍收到事件，则在捕获阶段统一分发。
  document.addEventListener('keydown', event => {
    if (!event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
    const key = event.key.toLowerCase();
    let id;
    if (key === recordStartShortcut.key && event.shiftKey === recordStartShortcut.shift) {
      if (typingHere(event)) return;
      id = 'record-start';
    } else {
      const shortcuts = event.shiftKey ? {b:'drawer',p:'note-photo'}
        : {',':'settings',k:'search',f:'find',b:'sidebar',n:'note-add',e:'copy-plain','/':'keys'};
      id = shortcuts[key];
      if (id === 'sidebar' && typingHere(event)) return;
    }
    if (!id) return;
    if (id === 'keys' && el('keymodal').classList.contains('show')) return;
    // 原生项目置灰时仍可能收到 DOM 按键；不能让旧页面监听绕过状态保护。
    event.preventDefault(); event.stopImmediatePropagation();
    if (!event.repeat && snapshot()[id]?.enabled) dispatch(id);
  }, true);
  function ready() {
    sync();
    setInterval(sync, 300);
    window.addEventListener('focus',sync);
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded',ready,{once:true});
  else ready();
})();
