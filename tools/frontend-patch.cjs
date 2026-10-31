#!/usr/bin/env node
// Local signing only. This tool never publishes a GitHub Release.
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {parseArgs}=require('node:util');
const publicHex=key=>Buffer.from(crypto.createPublicKey(key).export({format:'jwk'}).x,'base64url').toString('hex');

try{
  const [command,...args]=process.argv.slice(2);
  if(command==='keygen'){
    if(args.length!==2)throw Error('keygen PRIVATE_PEM PUBLIC_HEX');
    const [privatePath,publicPath]=args;
    if(fs.existsSync(privatePath)||fs.existsSync(publicPath))throw Error('拒绝覆盖已有密钥');
    const {privateKey}=crypto.generateKeyPairSync('ed25519');
    for(const file of args)fs.mkdirSync(path.dirname(path.resolve(file)),{recursive:true});
    fs.writeFileSync(privatePath,privateKey.export({format:'pem',type:'pkcs8'}),{flag:'wx',mode:0o600});
    fs.writeFileSync(publicPath,publicHex(privateKey)+'\n',{flag:'wx'});
    console.log('密钥已生成；私钥须备份，禁止上传或放入安装包。');
  }else if(command==='build'){
    const {values:v}=parseArgs({args,options:{key:{type:'string'},'public-key':{type:'string'},
      'base-version':{type:'string'},revision:{type:'string'},html:{type:'string'},
      out:{type:'string'},notes:{type:'string'},rollback:{type:'boolean',default:false}}});
    if(!v.key||!v.out||!/^\d+\.\d+\.\d+(\.\d+)?$/.test(v['base-version']||'')
       ||!/^\d+$/.test(v.revision||'')||!Number.isSafeInteger(Number(v.revision))||Number(v.revision)<=0)
      throw Error('build --key PRIVATE_PEM --base-version 3.1.9 --revision 1 --html index.html --out DIR [--notes NOTES.md] [--rollback]');
    const key=crypto.createPrivateKey(fs.readFileSync(v.key));
    const pub=v['public-key']||path.resolve(__dirname,'../frontend-patch-public-key.hex');
    if(key.asymmetricKeyType!=='ed25519'||publicHex(key)!==fs.readFileSync(pub,'utf8').trim())
      throw Error('私钥与基础版公钥不匹配');
    const manifest={schema:1,base_version:v['base-version'],revision:Number(v.revision),action:v.rollback?'builtin':'apply'};
    // 更新说明写进签名标签: 客户端在「更新」提示里原样展示，篡改即验签失败。
    if(v.notes){
      const notes=fs.readFileSync(v.notes,'utf8').trim();
      if(!notes||notes.length>8000)throw Error('更新说明为空或超过 8000 字');
      manifest.notes=notes;
    }
    let html;
    if(!v.rollback){
      html=fs.readFileSync(v.html);
      if(!html.length||html.length>10*1024*1024)throw Error('前端文件超过大小限制');
      new TextDecoder('utf-8',{fatal:true}).decode(html);
      Object.assign(manifest,{asset:`index-${manifest.base_version}-p${manifest.revision}.html`,
        size:html.length,sha256:crypto.createHash('sha256').update(html).digest('hex')});
    }
    const raw=Buffer.from(JSON.stringify(manifest,null,2)+'\n');
    const names=['tingdao-patch.json','tingdao-patch.sig',...(html?[manifest.asset]:[])];
    if(names.some(name=>fs.existsSync(path.join(v.out,name))))throw Error('拒绝覆盖已有补丁资产');
    fs.mkdirSync(v.out,{recursive:true});
    if(html)fs.writeFileSync(path.join(v.out,manifest.asset),html,{flag:'wx'});
    fs.writeFileSync(path.join(v.out,'tingdao-patch.sig'),crypto.sign(null,raw,key),{flag:'wx'});
    fs.writeFileSync(path.join(v.out,'tingdao-patch.json'),raw,{flag:'wx'});
    console.log(`已生成 ${manifest.base_version} 补丁 #${manifest.revision} (${manifest.action})`);
  }else throw Error('Commands: keygen, build');
}catch(error){console.error(error.message);process.exitCode=1;}
