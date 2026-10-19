// SPDX-License-Identifier: Apache-2.0
// node tests for the <design-md> block of assets/canvas.js: the small Markdown renderer behind "Design notes" (run: node tests/design_md.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <design-md>[\s\S]*?\/\/ <\/design-md>/);assert(block,'block missing');
const {renderDesignMd:md,mdEsc}=new Function(block[0]+'\n;return{renderDesignMd,mdEsc}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const has=(html,part)=>assert(html.includes(part),'missing '+part+' in '+html);
const lacks=(html,part)=>assert(!html.includes(part),'unexpected '+part+' in '+html);

t('headings become h3..h6 (the dialog title is the h2), trailing # removed',()=>{
 const h=md('# One\n\n## Two ##\n\n###### Six\n\n####### not a heading');
 has(h,'<h3>One</h3>');has(h,'<h4>Two</h4>');has(h,'<h6>Six</h6>');has(h,'<p>####### not a heading</p>');
});
t('paragraphs: blank line splits, a soft line break becomes <br>',()=>{
 assert.strictEqual(md('a\nb\n\nc'),'<p>a<br>b</p><p>c</p>');
 assert.strictEqual(md(''),'');assert.strictEqual(md('\n\n  \n'),'');
});
t('unordered, ordered (with start) and nested lists',()=>{
 assert.strictEqual(md('- a\n- b'),'<ul><li>a</li><li>b</li></ul>');
 assert.strictEqual(md('1. a\n2. b'),'<ol><li>a</li><li>b</li></ol>');
 has(md('3. x\n4. y'),'<ol start="3">');
 assert.strictEqual(md('- a\n  - a1\n  - a2\n- b'),'<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>');
 assert.strictEqual(md('* a\n+ b'),'<ul><li>a</li><li>b</li></ul>');
 assert.strictEqual(md('- a\n\n- b'),'<ul><li>a</li><li>b</li></ul>','a blank line between items keeps one list');
 assert.strictEqual(md('- a\n  more\n- b'),'<ul><li>a<br>more</li><li>b</li></ul>','indented continuation line');
 assert.strictEqual(md('- a\n1. b'),'<ul><li>a</li></ul><ol><li>b</li></ol>','changing the list type starts a new list');
});
t('a list directly after a paragraph line ends the paragraph',()=>{assert.strictEqual(md('intro\n- a'),'<p>intro</p><ul><li>a</li></ul>')});
t('tables: header, rows, alignment, short rows, escaped pipe, inline markup in cells',()=>{
 const h=md('| A | B | C |\n|:--|:-:|--:|\n| 1 | **two** | `3` |\n| x |\n\nafter');
 has(h,'<div class="md-table"><table><thead><tr><th class="al-l">A</th><th class="al-c">B</th><th class="al-r">C</th></tr></thead>');
 has(h,'<td class="al-l">1</td><td class="al-c"><strong>two</strong></td><td class="al-r"><code>3</code></td>');
 has(h,'<td class="al-l">x</td><td class="al-c"></td><td class="al-r"></td>');has(h,'<p>after</p>');
 has(md('A | B\n--|--\na \\| b | c'),'<td>a | b</td>');
 assert.strictEqual(md('just | a pipe\nnext line'),'<p>just | a pipe<br>next line</p>','no separator row, no table');
});
t('bold, inline code (also with backticks inside), unmatched markers stay text',()=>{
 assert.strictEqual(md('a **b** c'),'<p>a <strong>b</strong> c</p>');
 assert.strictEqual(md('use `x < y` here'),'<p>use <code>x &lt; y</code> here</p>');
 assert.strictEqual(md('`` a`b ``'),'<p><code>a`b</code></p>');
 assert.strictEqual(md('**open and `code`'),'<p>**open and <code>code</code></p>');
 assert.strictEqual(md('a ` b'),'<p>a ` b</p>');assert.strictEqual(md('a ****'),'<p>a ****</p>');
 assert.strictEqual(md('**`a`**'),'<p><strong><code>a</code></strong></p>');
 assert.strictEqual(md('**not `bold**`'),'<p><strong>not `bold</strong>`</p>');
});
t('fenced code keeps its text verbatim and escaped; an unclosed fence runs to the end; Markdown inside is not rendered',()=>{
 assert.strictEqual(md('```js\nconst a = "<b>"; **x**\n```\nafter'),'<pre><code>const a = &quot;&lt;b&gt;&quot;; **x**</code></pre><p>after</p>');
 assert.strictEqual(md('~~~\na\n- b'),'<pre><code>a\n- b</code></pre>');
 assert.strictEqual(md('```\n```'),'<pre><code></code></pre>');
});
t('links: http(s) and mailto are anchors with rel noopener; relative, anchors and script-like URLs keep only the text',()=>{
 has(md('[site](https://example.com/a?b=1&c=2)'),'<a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">site</a>');
 has(md('[mail](mailto:a@b.co)'),'<a href="mailto:a@b.co"');
 assert.strictEqual(md('[a](./other.md)'),'<p>a</p>');assert.strictEqual(md('[a](/x/y)'),'<p>a</p>');assert.strictEqual(md('[a](#top)'),'<p>a</p>');
 for(const u of ['javascript:alert(1)','JaVaScRiPt:alert(1)','data:text/html,x','vbscript:x',' javascript:x','//evil.example/x','file:///etc/passwd']){const h=md('[click]('+u+')');lacks(h,'<a');lacks(h,'href')}
 has(md('[**bold** label](https://e.co "title")'),'<strong>bold</strong> label</a>');
 assert.strictEqual(md('[no close](https://e.co'),'<p>[no close](https://e.co</p>');
});
t('images are plain escaped text: no <img>, no request',()=>{
 const h=md('![alt](https://tracker.example/x.png) and ![](rel/a.png)');
 lacks(h,'<img');lacks(h,'<a');has(h,'![alt](https://tracker.example/x.png) and ![](rel/a.png)');
});
t('HTML is escaped everywhere (XSS payloads stay text)',()=>{
 const evil=['<script>alert(1)</script>','<img src=x onerror=alert(1)>','<a href="javascript:alert(1)">x</a>','"><svg/onload=alert(1)>','<iframe src=//evil></iframe>'];
 const doc=[...evil.map(e=>e),'# '+evil[0],'- '+evil[1],'| '+evil[2]+' | b |\n|--|--|\n| '+evil[3]+' | '+evil[4]+' |','> '+evil[1],'**'+evil[0]+'**','`'+evil[1]+'`','[<b>x</b>]('+evil[0]+')','```\n'+evil[0]+'\n```'].join('\n\n');
 const h=md(doc);
 assert(!/<(script|img|svg|iframe|b)\b/i.test(h),h);
 assert.strictEqual(mdEsc('<&>"\''),'&lt;&amp;&gt;&quot;&#39;');
 assert(!/<[^>]*\son(error|load)=/i.test(h),h);
});
t('quotes and rules',()=>{
 assert.strictEqual(md('> a\n> **b**'),'<blockquote><p>a<br><strong>b</strong></p></blockquote>');
 assert.strictEqual(md('a\n\n---\n\nb'),'<p>a</p><hr><p>b</p>');
 assert.strictEqual(md('* * *'),'<hr>');
});
t('CRLF, BOM, tabs and CJK text',()=>{
 assert.strictEqual(md('\uFEFF# \u6807\u9898\r\n\r\n- \u9879\u76ee\u4e00\r\n- \u9879\u76ee\u4e8c\r\n'),'<h3>\u6807\u9898</h3><ul><li>\u9879\u76ee\u4e00</li><li>\u9879\u76ee\u4e8c</li></ul>');
 assert.strictEqual(md('- a\n\t- b'),'<ul><li>a<ul><li>b</li></ul></li></ul>');
});
t('odd input never throws (non-string, huge line, deep nesting, many brackets)',()=>{
 for(const v of [null,undefined,0,{},[]])md(v);
 const t0=Date.now();
 md('['.repeat(200000));md('`'.repeat(200000));md('**'.repeat(100000));md('![a]('.repeat(50000));md('['+'a'.repeat(100000));
 md('- a\n'.repeat(20000));md(Array.from({length:60},(_,i)=>' '.repeat(i*2)+'- x').join('\n'));md('> '.repeat(500)+'x');
 md('|a|b|\n|-|-|\n'+'|1|2|\n'.repeat(20000));
 assert(Date.now()-t0<5000,'too slow: '+(Date.now()-t0)+' ms');
});
t('a realistic design note renders in order',()=>{
 const h=md('# \u9996\u6b21\u8fdb\u5165\u7a7a\u6001 · r2\n\n\u672c\u8f6e\u6309\u7528\u6237\u9700\u6c42\u505a\u8bbe\u8ba1\u63a2\u7d22\u3002\n\nA \u53cc\u5165\u53e3\u5361\u7247\uff1a\u4f18\u70b9\u662f\u6e05\u6670\u3002\n\n## r3 · \u65b9\u6848 C\n\n- \u7b2c\u4e00\u9879\n- \u7b2c\u4e8c\u9879\n\n1. \u6b65\u9aa4\u4e00\n2. \u6b65\u9aa4\u4e8c');
 assert(h.indexOf('<h3>')<h.indexOf('<p>\u672c\u8f6e')&&h.indexOf('<h4>')<h.indexOf('<ul>')&&h.indexOf('<ul>')<h.indexOf('<ol>'),h);
});
console.log(`${n} passed, ${fail} failed`);process.exit(fail?1:0);
