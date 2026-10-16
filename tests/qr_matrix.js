// SPDX-License-Identifier: Apache-2.0
// usage: node qr_matrix.js <canvas.js> <inputs.json> <out.json>  -> loads the <qr-encoder> block verbatim and encodes every text
const fs=require('fs'),vm=require('vm');
const src=fs.readFileSync(process.argv[2],'utf8');
const m=src.match(/\/\/ <qr-encoder>[\s\S]*?\/\/ <\/qr-encoder>/);if(!m)throw new Error('no qr-encoder block');
const ctx={TextEncoder,document:null};vm.createContext(ctx);vm.runInContext(m[0].replace(/function qrSvg[\s\S]*?\n}\n/,''),ctx);
const inputs=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
fs.writeFileSync(process.argv[4],JSON.stringify(inputs.map(t=>{const q=ctx.qrEncode(t);return q?{text:t,version:q.version,mask:q.mask,size:q.size,modules:q.modules.map(r=>r.map(v=>v?1:0).join(''))}:{text:t,version:null}})));
