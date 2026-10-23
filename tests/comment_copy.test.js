// SPDX-License-Identifier: Apache-2.0
// node tests for the <comment-copy> block of assets/canvas.js: the text behind "Copy this comment" and "Copy for AI"
// (run: node tests/comment_copy.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <comment-copy>[\s\S]*?\/\/ <\/comment-copy>/);assert(block,'block missing');
const {commentFeedbackText}=new Function(block[0]+'\n;return{commentFeedbackText}')();
const dict=JSON.parse(fs.readFileSync(path.join(__dirname,'..','assets','i18n.json'),'utf8'));
const trFor=lang=>(key,params)=>{let text=dict[lang][key];assert(typeof text==='string','missing key '+key);return params?text.replace(/\{(\w+)\}/g,(m,n)=>(n in params?params[n]:m)):text};
const zh=trFor('zh'),en=trFor('en');
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const meta={name:'Board',id:'proj',rev:'r2'};
const one={frame:'Canvas',element:'Note heading',target:'~note~intro~heading',text:'panel copy locate',status:'changed',replies:[{text:'agent reply'}]};

t('one comment uses the Copy for AI header and a single numbered row, in English',()=>{
 assert.strictEqual(commentFeedbackText(meta,[one],en),[
  'Board design comments (proj / r2)',
  'Please update the canvas at these elements:',
  '',
  '1. Canvas / Note heading',
  'Element ID: ~note~intro~heading',
  'Feedback: panel copy locate'].join('\n'));
});
t('the same comment in Chinese uses the Chinese header and row labels',()=>{
 assert.strictEqual(commentFeedbackText(meta,[one],zh),[
  'Board \u8bbe\u8ba1\u8bc4\u8bba\uff08proj / r2\uff09',
  '\u8bf7\u6309\u4ee5\u4e0b\u5143\u7d20\u4f4d\u7f6e\u4fee\u6539\u753b\u5e03\uff1a',
  '',
  '1. Canvas / Note heading',
  '\u5143\u7d20 ID\uff1a~note~intro~heading',
  '\u610f\u89c1\uff1apanel copy locate'].join('\n'));
});
t('status and replies are not part of the payload (they stay on the card)',()=>{
 const text=commentFeedbackText(meta,[one],en);
 assert(!/changed|Pending|agent reply|replies/.test(text),text);
});
t('several comments are numbered in order and separated by a blank line, same as Copy for AI',()=>{
 const second={frame:'Screen 1',element:'Button',target:'f01--b',text:'older comment'};
 const text=commentFeedbackText(meta,[one,second],en);
 assert(text.includes('1. Canvas / Note heading\nElement ID: ~note~intro~heading\nFeedback: panel copy locate\n\n2. Screen 1 / Button\nElement ID: f01--b\nFeedback: older comment'),text);
 assert.strictEqual(commentFeedbackText({name:'Board',id:'proj',rev:'r9'},[one],en).split('\n')[0],'Board design comments (proj / r9)');
});
t('feedback text is copied as stored, including a newline',()=>{
 const text=commentFeedbackText(meta,[{frame:'Canvas',element:'tip',target:'~note~intro~tip',text:'line one\nline two'}],en);
 assert(text.endsWith('Feedback: line one\nline two'),text);
});
t('the page wires each card button to this text, and history uses the snapshot rev',()=>{
 assert(src.includes('function feedback(rows){return commentFeedbackText({name:project.name,id:project.id,rev:historyRev||revision},rows,tr)}'),'feedback() must pass the snapshot rev in history');
 assert(src.includes("b.className='copy-comment'"),'per-card button missing');
 assert(src.includes('copyFeedbackRows([c])'),'button must copy that one comment');
 assert(src.includes('actions.append(commentCopyButton(c),locate)'),'history cards must offer copy');
 assert(src.includes('actions.append(commentCopyButton(c),locate,status,edit,remove)'),'live cards must offer copy');
 assert(src.includes("toast(tr('c.copied',{n:rows.length}))"),'successful copy must toast');
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
