const fs = require('node:fs');
const crypto = require('node:crypto');
const https = require('node:https');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { pipeline } = require('node:stream/promises');

const root = path.resolve(__dirname, '..');
const destination = path.join(__dirname, 'program-windows');
const files = ['app.py', 'index.html', 'whisper_worker.py', 'whisper_worker_windows.py'];

// 干净检出也必须有可嵌入的启动页；实际 UI 待后端就绪后导航加载。
fs.mkdirSync(path.join(__dirname, 'dist'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'dist', 'index.html'),
  '<!DOCTYPE html><html><head><meta charset="utf-8"><title>听道</title></head><body style="background:transparent"></body></html>', 'utf8');
fs.mkdirSync(path.join(destination, 'assets'), { recursive: true });
fs.copyFileSync(path.join(root, 'assets', 'material-preview-lakeside.png'),
  path.join(destination, 'assets', 'material-preview-lakeside.png'));

fs.mkdirSync(path.join(destination, 'sounds'), { recursive: true });
for (const file of files) {
  fs.copyFileSync(path.join(root, file), path.join(destination, file));
}
// 简繁转换库随包分发，放在 app.py 旁边即可被直接导入，不依赖用户 venv。
fs.cpSync(path.join(root, 'opencc'), path.join(destination, 'opencc'), { recursive: true });
for (const file of fs.readdirSync(path.join(root, 'sounds'))) {
  if (file.endsWith('.mp3')) {
    fs.copyFileSync(path.join(root, 'sounds', file), path.join(destination, 'sounds', file));
  }
}

// 固定 LGPL 共享构建与校验和，避免打包时静默换成不同来源或许可的二进制。
// 月末构建由上游保留两年；普通每日构建会被清理，旧的 09-25 链接已经失效。
const ffmpegZip = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-shared-9.0.zip';
const ffmpegSha256 = '7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646';
const ffmpegLicense = 'https://raw.githubusercontent.com/FFmpeg/FFmpeg/2a571b6068/COPYING.LGPLv2.1';
const ffmpegLicenseSha256 = '246041b6ecf9bc32d718a62c57877c78b5eb397b6467e74ed7ae2626ab189c30';

function download(url, destination, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 5) return reject(new Error('FFmpeg 下载重定向过多'));
    https.get(url, response => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        return download(new URL(response.headers.location, url), destination, redirects + 1)
          .then(resolve, reject);
      }
      if (response.statusCode !== 200) {
        response.resume();
        return reject(new Error(`FFmpeg 下载失败: HTTP ${response.statusCode}`));
      }
      pipeline(response, fs.createWriteStream(destination)).then(resolve, reject);
    }).on('error', reject);
  });
}

async function stageFfmpeg() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'tingdao-ffmpeg-'));
  const archive = path.join(temp, 'ffmpeg.zip');
  const extracted = path.join(temp, 'extracted');
  const destination = path.join(__dirname, 'program-windows', 'ffmpeg');
  try {
    await download(ffmpegZip, archive);
    const digest = crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex');
    if (digest !== ffmpegSha256) throw new Error(`FFmpeg SHA-256 不匹配: ${digest}`);
    const license = path.join(temp, 'COPYING.LGPLv2.1');
    await download(ffmpegLicense, license);
    const licenseDigest = crypto.createHash('sha256').update(fs.readFileSync(license)).digest('hex');
    if (licenseDigest !== ffmpegLicenseSha256) throw new Error(`FFmpeg 许可 SHA-256 不匹配: ${licenseDigest}`);
    fs.mkdirSync(extracted);
    // Windows 10/11 自带 bsdtar；不依赖 PowerShell 脚本模块或执行策略。
    const command = process.platform === 'win32' ? 'tar.exe' : 'unzip';
    const args = process.platform === 'win32'
      ? ['-xf', archive, '-C', extracted]
      : ['-q', archive, '-d', extracted];
    const result = spawnSync(command, args, { stdio: 'inherit' });
    if (result.error || result.status !== 0) throw result.error || new Error('FFmpeg 压缩包解压失败');
    const packageDir = fs.readdirSync(extracted)
      .map(name => path.join(extracted, name))
      .find(name => fs.statSync(name).isDirectory());
    const bin = path.join(packageDir || '', 'bin');
    const entries = fs.readdirSync(bin);
    if (!entries.includes('ffmpeg.exe') || !entries.includes('ffprobe.exe')) {
      throw new Error('FFmpeg 压缩包缺少 ffmpeg.exe 或 ffprobe.exe');
    }
    fs.rmSync(destination, { recursive: true, force: true });
    fs.mkdirSync(destination, { recursive: true });
    for (const file of entries) {
      if (/^(ffmpeg|ffprobe)\.exe$/i.test(file) || /\.dll$/i.test(file)) {
        fs.copyFileSync(path.join(bin, file), path.join(destination, file));
      }
    }
    fs.copyFileSync(license, path.join(destination, 'COPYING.LGPLv2.1'));
    const licenseDir = path.join(packageDir, 'licenses');
    if (fs.existsSync(licenseDir)) {
      fs.cpSync(licenseDir, path.join(destination, 'licenses'), { recursive: true });
    }
    fs.writeFileSync(path.join(destination, 'FFmpeg-Build.txt'),
      `BtbN FFmpeg LGPL shared build\n${ffmpegZip}\nSHA-256: ${ffmpegSha256}\n` +
      'FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/2a571b6068\n' +
      'Build source: https://github.com/BtbN/FFmpeg-Builds\n', 'utf8');
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

stageFfmpeg().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
