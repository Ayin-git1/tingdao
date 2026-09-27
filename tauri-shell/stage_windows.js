const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const destination = path.join(__dirname, 'program-windows');
const files = ['app.py', 'index.html', 'whisper_worker.py', 'whisper_worker_windows.py'];

fs.mkdirSync(path.join(destination, 'sounds'), { recursive: true });
for (const file of files) {
  fs.copyFileSync(path.join(root, file), path.join(destination, file));
}
for (const file of fs.readdirSync(path.join(root, 'sounds'))) {
  if (file.endsWith('.mp3')) {
    fs.copyFileSync(path.join(root, 'sounds', file), path.join(destination, 'sounds', file));
  }
}
