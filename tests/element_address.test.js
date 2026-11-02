// SPDX-License-Identifier: Apache-2.0
// node tests for the <element-address> block of assets/canvas.js: the text behind "Copy element address"
// (run: node tests/element_address.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'..','assets','canvas.html'),'utf8');
const frame=src.match(/\/\/ <frame-ref>[\s\S]*?\/\/ <\/frame-ref>/);assert(frame,'frame-ref block missing');
const block=src.match(/\/\/ <element-address>[\s\S]*?\/\/ <\/element-address>/);assert(block,'block missing');
const {elementAddressText}=new Function(frame[0]+'\n'+block[0]+'\n;return{elementAddressText}')();
const dict=JSON.parse(fs.readFileSync(path.join(__dirname,'..','assets','i18n.json'),'utf8'));
const trFor=lang=>(key,params)=>{let text=dict[lang][key];assert(typeof text==='string','missing key '+key);return params?text.replace(/\{(\w+)\}/g,(m,n)=>(n in params?params[n]:m)):text};
const zh=trFor('zh'),en=trFor('en');
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const screen={origin:'http://192.168.1.20:4846',canvasId:'12',rev:'v3',frameId:'home',frameTitle:'Home',element:'Continue',target:'home--continue'};

t('a screen element names the canvas, the revision on screen, the frame and the comment target',()=>{
 assert.strictEqual(elementAddressText(screen,en),[
  'UI Canvas element address',
  'Canvas: http://192.168.1.20:4846/ (canvas id: #12)',
  'Revision: v3',
  'Frame: home (Home)',
  'Element: Continue',
  'Element ID: home--continue'].join('\n'));
});
t('the same element in Chinese uses the Chinese labels and the frame-reference canvas line',()=>{
 assert.strictEqual(elementAddressText(screen,zh),[
  'UI Canvas \u5143\u7d20\u5730\u5740',
  '\u753b\u5e03\uff1ahttp://192.168.1.20:4846/\uff08canvas id: #12\uff09',
  '\u7248\u672c\uff1av3',
  '\u753b\u9762\uff1ahome\uff08Home\uff09',
  '\u5143\u7d20\uff1aContinue',
  '\u5143\u7d20 ID\uff1ahome--continue'].join('\n'));
});
t('a history snapshot id is the revision line, unchanged',()=>{
 assert.strictEqual(elementAddressText({...screen,rev:'r61'},en).split('\n')[2],'Revision: r61');
});
t('no frame: the frame line is Canvas, and note, group and title ids are copied as stored',()=>{
 const note=elementAddressText({origin:'http://h:1',canvasId:'xdbtqx',rev:'v1',element:'Note heading',target:'~note~intro~heading'},en);
 assert.strictEqual(note.split('\n')[3],'Frame: Canvas');
 assert.strictEqual(note.split('\n')[5],'Element ID: ~note~intro~heading');
 assert.strictEqual(elementAddressText({origin:'http://h:1',canvasId:'#12',rev:'v1',element:'Group: Onboarding',target:'group~Onboarding~2~title'},en).split('\n')[5],'Element ID: group~Onboarding~2~title');
 assert.strictEqual(elementAddressText({...screen,element:'Title: Home',target:'home~title'},en).split('\n')[5],'Element ID: home~title');
 assert.strictEqual(elementAddressText({origin:'http://h:1',rev:'v1',element:'\u5206\u7ec4\uff1aOnboarding',target:'group~A%7E%25B~title'},zh).split('\n')[5],'\u5143\u7d20 ID\uff1agroup~A%7E%25B~title');
});
t('title equal to the id, or missing, omits the parenthesis; a 6-digit id is not hashed; a hash already present stays',()=>{
 assert.strictEqual(elementAddressText({...screen,frameTitle:'home'},en).split('\n')[3],'Frame: home');
 assert.strictEqual(elementAddressText({...screen,frameTitle:'  '},en).split('\n')[3],'Frame: home');
 assert.strictEqual(elementAddressText({...screen,canvasId:'234567'},en).split('\n')[1],'Canvas: http://192.168.1.20:4846/ (canvas id: 234567)');
 assert.strictEqual(elementAddressText({...screen,canvasId:'#12'},en).split('\n')[1],'Canvas: http://192.168.1.20:4846/ (canvas id: #12)');
 assert.strictEqual(elementAddressText({...screen,canvasId:'xdbtqx'},en).split('\n')[1],'Canvas: http://192.168.1.20:4846/ (canvas id: xdbtqx)');
});
t('canvas id unknown omits the parenthesis; an empty revision omits that line',()=>{
 const lines=elementAddressText({origin:'http://h:1/',canvasId:'',rev:'',frameId:'home',frameTitle:'Home',element:'Continue',target:'home--continue'},en).split('\n');
 assert.strictEqual(lines[1],'Canvas: http://h:1/');
 assert.strictEqual(lines.length,5);
 assert.strictEqual(lines[2],'Frame: home (Home)');
});
t('a newline in the label stays on that line; the target is copied exactly; no file path',()=>{
 const text=elementAddressText({...screen,element:'line one\nline two',target:'home--continue',path:'frames/home.html'},en);
 assert.strictEqual(text.split('\n')[4],'Element: line one line two');
 assert(!/frames\/|\.html|\/api\//.test(text),text);
 assert.strictEqual(elementAddressText({...screen,target:' home--b '},en).split('\n')[5],'Element ID:  home--b ');
});
t('the add-comment box wires the button to this text and the revision on screen',()=>{
 const editor=html.slice(html.indexOf('<dialog id="editor">'), html.indexOf('</dialog>', html.indexOf('<dialog id="editor">')));
 assert(editor.includes('id="copy-element-address"'),'button missing');
 assert(editor.includes('type="button" id="copy-element-address"'),'button must not submit the comment');
 assert(editor.indexOf('id="selection-label"')<editor.indexOf('id="copy-element-address"'),'button follows the element context');
 assert(editor.indexOf('id="copy-element-address"')<editor.indexOf('id="layer-picker"'),'button stays above the layer picker');
 assert(src.includes('elementAddressText({origin:location.origin,canvasId:refInfo.canvasId,rev:historyRev||revision'),'address uses the revision on screen, not the newest snapshot');
 assert(src.includes('target:el.id'),'address uses the comment target id');
 assert(src.includes("toast(ok?tr('c.addr.copied'):tr('c.copyFailed'))"),'successful copy must toast');
 assert(src.includes("btn.textContent=ok?tr('c.copied1'):tr('c.copyFailed')"),'the button itself confirms the copy');
 assert(src.includes("$('copy-element-address').onclick"),'handler missing');
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
