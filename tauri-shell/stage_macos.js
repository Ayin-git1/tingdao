const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..'),destination=path.join(__dirname,'program');
fs.mkdirSync(destination,{recursive:true});
for(const name of ['app.py','frontend_patch.py','index.html','whisper_worker.py','tingdao-mix','sounds','TingdaoMic.app','licenses']){
  fs.cpSync(path.join(root,name),path.join(destination,name),{recursive:true});
}
fs.mkdirSync(path.join(__dirname,'dist'),{recursive:true});
fs.writeFileSync(path.join(__dirname,'dist/index.html'),'<!doctype html><html><head><meta charset="utf-8"><title>听道</title></head><body></body></html>');
