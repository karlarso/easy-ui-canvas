// SPDX-License-Identifier: Apache-2.0
// node tests/device_class.test.js
const fs = require('fs'), assert = require('assert'), path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'assets', 'canvas.js'), 'utf8');
const block = src.match(/\/\/ <device-class>[\s\S]*?\/\/ <\/device-class>/);
assert(block, 'device-class block missing');
const api = new Function(block[0] + '\n;return{uicDeviceClass,uicIsPhone,exportMobileHref}')();
let n = 0, fail = 0;
const t = (name, fn) => { try { fn(); n++; console.log('PASS', name); } catch (e) { fail++; console.log('FAIL', name, e.message); } };

t('a phone is a phone even in a wide window', () => {
  assert.strictEqual(api.uicDeviceClass('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 0), 'phone');
  assert.strictEqual(api.uicIsPhone('Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile', 5), true);
});
t('a tablet and a desktop are not phones', () => {
  assert.strictEqual(api.uicDeviceClass('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', 0), 'tablet');
  assert.strictEqual(api.uicDeviceClass('Mozilla/5.0 (Linux; Android 14; SM-T870)', 5), 'tablet');
  assert.strictEqual(api.uicDeviceClass('Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit', 5), 'tablet');
  assert.strictEqual(api.uicIsPhone('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0', 0), false);
});
t('the static phone page keeps start and drops a server rev', () => {
  const href = api.exportMobileHref('https://cdn.example/pkg/index.html?rev=r7&start=hub');
  assert.strictEqual(href, 'https://cdn.example/pkg/m/index.html?start=hub');
  assert.strictEqual(api.exportMobileHref('https://cdn.example/index.html'), 'https://cdn.example/m/index.html');
  assert.strictEqual(api.exportMobileHref('file:///tmp/hand/index.html?start=home'), 'file:///tmp/hand/m/index.html?start=home');
  assert.strictEqual(api.exportMobileHref('https://cdn.example/pkg/index.html?start=hub', 'detail'), 'https://cdn.example/pkg/m/index.html?start=detail');
  assert.strictEqual(api.exportMobileHref('file:///tmp/hand/index.html', 'home'), 'file:///tmp/hand/m/index.html?start=home');
});

if (fail) process.exit(1);
console.log(n + ' passed');
