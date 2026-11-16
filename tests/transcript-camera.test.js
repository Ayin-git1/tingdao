const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const html=fs.readFileSync('index.html','utf8');

test('transcript camera requests direct capture and inserts at the clicked paragraph',async()=>{
  for(const switchDocument of [false,true]){
    const inserted=[],cameraFrame={},cameraButton={hidden:false,getBoundingClientRect:()=>({left:20,width:80,top:50})};
    const ctx=vm.createContext({cameraFrame,transcriptCameraTarget:null,view:{id:'original'},state:'idle',
      transcriptNoteTargetTime:42.5,transcriptNoteTargetRow:{isConnected:true,dataset:{rowId:'line-7'}},
      $:()=>cameraButton,hideTranscriptNoteMenu(){},setCameraWaiting(){},toast(){},fmt:String,
      fetch:async()=>({blob:async()=>({})}),File:class {},
      insertTranscriptImageFiles:async(files,target)=>inserted.push(target)});
    const start=html.indexOf('async function insertCameraPhoto(');
    const end=html.indexOf("$('btnCamTool').onclick=",start);
    vm.runInContext(html.slice(start,end),ctx);
    const click=html.indexOf("$('transcriptNoteCamera').onclick=");
    assert.ok(click>=0,'transcript camera menu action exists');
    vm.runInContext(html.slice(click,html.indexOf('\n};',click)+3),ctx);
    cameraButton.onclick();
    assert.equal(new URL(cameraFrame.src).searchParams.get('direct'),'1');
    if(switchDocument)ctx.view={id:'other'};
    await ctx.insertCameraPhoto({mime:'image/jpeg',data:''});
    assert.equal(inserted.length,switchDocument?0:1);
    if(!switchDocument){
      assert.equal(inserted[0].time,42.5);
      assert.equal(inserted[0].intent.rowId,'line-7');
      assert.equal(inserted[0].intent.position,'after');
    }
  }
});
