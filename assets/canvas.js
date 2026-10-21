// SPDX-License-Identifier: Apache-2.0 AND MIT
// The <qr-encoder> block below is adapted from Project Nayuki's QR Code generator (MIT License); see NOTICE.
// <scroll-lock> Wheel-round routing. Pure logic (no DOM globals) so node tests can load this block verbatim.
// A "round" is a run of wheel events with no gap longer than `gap` ms (trackpad inertia belongs to the same round).
// The target (frame scroller vs canvas) is decided once, on the first event of a round, and stays until the round ends.
function createWheelRouter(opts){
 const gap=opts.gap==null?180:opts.gap,isFrame=opts.isFrame,styleOf=opts.styleOf;
 let lastT=-Infinity,lock=null;
 function canScroll(el,vertical,dir){
  const s=styleOf(el),ov=vertical?s.overflowY:s.overflowX;
  if(ov!=='auto'&&ov!=='scroll'&&ov!=='overlay')return false;
  const size=vertical?el.scrollHeight-el.clientHeight:el.scrollWidth-el.clientWidth;
  if(!(size>1))return false;
  const pos=vertical?el.scrollTop:el.scrollLeft;
  return dir<0?pos>0:pos<size-1;
 }
 function frameOf(el){for(;el;el=el.parentElement)if(isFrame(el))return el;return null}
 // Nearest ancestor (up to and including the frame root) that can still move in this direction.
 function findScroller(start,vertical,dir){for(let el=start;el;el=el.parentElement){if(canScroll(el,vertical,dir))return el;if(isFrame(el))break}return null}
 function route(ev){
  if(ev.ctrl)return{action:'zoom',frame:null,scroller:null,newRound:false};
  if(!ev.dx&&!ev.dy)return{action:'noop',frame:lock&&lock.frame,scroller:null,newRound:false};
  const vertical=Math.abs(ev.dy)>=Math.abs(ev.dx),dir=Math.sign(vertical?ev.dy:ev.dx);
  const fresh=!lock||!(ev.t-lastT<=gap);
  if(fresh){
   const frame=frameOf(ev.target);
   if(!frame)lock={kind:'canvas',reason:'blank'};
   else if(ev.space)lock={kind:'canvas',reason:'space'};
   else if(findScroller(ev.target,vertical,dir))lock={kind:'frame',frame,target:ev.target};
   else lock={kind:'canvas',reason:'frame-unscrollable'};
  }
  lastT=ev.t;
  if(lock.kind==='canvas')return{action:'pan',frame:null,scroller:null,newRound:fresh,reason:lock.reason};
  // Inside a locked round the scroller is re-picked per event (nested scrollers chain inside the frame);
  // when nothing can move any more the event is swallowed: it never reaches the canvas.
  const start=ev.target&&lock.frame.contains(ev.target)?ev.target:lock.target;
  return{action:'scroll',frame:lock.frame,scroller:findScroller(start,vertical,dir),newRound:fresh};
 }
 return{route,reset(){lock=null;lastT=-Infinity},canScroll,findScroller,get lock(){return lock}};
}
// </scroll-lock>
// <flow-core> Pure helpers shared by the canvas "Flow" view and the /m/ phone page (node tests load this block verbatim).
// data-goto="<frame id>" marks a jump button. The tile view never looks at it.
const flowDemoEnd=()=>typeof tr==='function'?tr('flow.demoEnd'):'End of demo';
function flowFrameUrl(rev,path){return rev?'/api/snapshots/'+encodeURIComponent(rev)+'/'+path.split('/').map(encodeURIComponent).join('/'):'/project/'+path}
// ?start= (want) wins, then project.flow_start, then the first frame; an id that is not a frame falls through to the next choice.
function flowPickStart(ids,flowStart,want){for(const c of [want,flowStart])if(typeof c==='string'&&ids.includes(c))return c;return ids[0]}
// What a click means in flow mode: {kind:'goto',id,el} | {kind:'demo',el} | null (leave the event alone: inputs, text selection, ...).
// Only a, button, [role=button] and elements with data-goto are intercepted; data-goto on an ancestor of the clicked element counts.
function flowClickAction(target,root,ids){
 if(!target||!target.closest||!root)return null;
 const g=target.closest('[data-goto]');
 if(g&&root.contains(g)){const v=(g.getAttribute('data-goto')||'').trim();if(v)return ids.includes(v)?{kind:'goto',id:v,el:g}:{kind:'demo',el:g,missing:v}}
 const c=target.closest('a,button,[role="button"]');
 if(c&&root.contains(c))return{kind:'demo',el:c};
 return null;
}
// What the board's comment click handler does with a click (it runs before the Flow jump handler, both in the capture phase on the board).
// s = {history, editorOpen, flow, commentMode, hasTarget (inside a [data-comment]), onButton}. Returns:
//  'close-editor' history view: read-only, a click only closes an open comment box; 'block' a comment box is open (or comment mode is on in the Flow view and the click hit nothing commentable): swallow the click, no jump;
//  'hint' tile view, comment mode off, a button was clicked: show the design-preview hint; 'select' select the element and open the comment box; 'ignore' do nothing (in the Flow view the jump handler then sees the click).
function commentClickPlan(s){
 if(s.history)return s.editorOpen?'close-editor':'ignore';
 if(s.editorOpen)return'block';
 if(!s.hasTarget)return s.flow&&s.commentMode?'block':'ignore';
 if(!s.commentMode)return !s.flow&&s.onButton?'hint':'ignore';
 return'select';
}
// Bottom hint that disappears by itself (1.5 s).
function createDemoToast(el,ms){ms=ms||1500;let t=0;return function(text){el.textContent=text||flowDemoEnd();el.classList.add('show');clearTimeout(t);t=setTimeout(()=>el.classList.remove('show'),ms)}}
// </flow-core>
// <tile-layout> Tile view layout: the one function behind the board (dimensions, frame placement) and the minimap (frameBoxes), so they cannot drift. Pure (no DOM); node tests load this block verbatim.
// Frames keep their order and are cut into sections by consecutive runs of the same `group` (blank or missing = no group). A section starts on a new row; a grouped section has a title bar above its grid.
// Each section has its own column count (project.groupColumns[group], else project.columns, else 3; at most the frames in the section) and its own column widths (widest frame per column in that section).
// A project without any group is one section: same columns, sizes and positions as the old single global grid. Returns {boxes: [{x,y,w,h}] per frame, sections: [{group,start,count,cols,rows,x,y,w,h,bar}], w, h}.
const TILE={gapX:40,gapY:44,pad:12,titleH:68,barH:36,barGap:20,sectionGap:72,columns:3};
function tileGroupOf(f){const g=f&&f.group;return typeof g==='string'&&g.trim()?g:''}
function tilePositive(v){return typeof v==='number'&&Number.isInteger(v)&&v>=1?v:0}
function tileLayout(project){
 const T=TILE,frames=project.frames||[],gc=project.groupColumns&&typeof project.groupColumns==='object'?project.groupColumns:null,baseCols=tilePositive(project.columns)||T.columns;
 const boxes=new Array(frames.length),sections=[];let y=T.pad,maxW=0,end=T.pad;
 for(let i=0;i<frames.length;){
  const group=tileGroupOf(frames[i]);let j=i+1;while(j<frames.length&&tileGroupOf(frames[j])===group)j++;
  const n=j-i,own=group&&gc&&Object.prototype.hasOwnProperty.call(gc,group)?tilePositive(gc[group]):0,cols=Math.min(own||baseCols,n),rows=Math.ceil(n/cols);
  const widths=Array(cols).fill(0),heights=Array(rows).fill(0);
  for(let k=0;k<n;k++){const f=frames[i+k];widths[k%cols]=Math.max(widths[k%cols],f.width);heights[Math.floor(k/cols)]=Math.max(heights[Math.floor(k/cols)],f.height+T.titleH)}
  const xs=[T.pad];for(let c=1;c<cols;c++)xs[c]=xs[c-1]+widths[c-1]+T.gapX;
  const top=y,gridTop=top+(group?T.barH+T.barGap:0),ys=[gridTop];for(let r=1;r<rows;r++)ys[r]=ys[r-1]+heights[r-1]+T.gapY;
  for(let k=0;k<n;k++){const f=frames[i+k];boxes[i+k]={x:xs[k%cols],y:ys[Math.floor(k/cols)],w:f.width,h:f.height+T.titleH}}
  const w=widths.reduce((a,b)=>a+b,0)+(cols-1)*T.gapX;end=ys[rows-1]+heights[rows-1];
  sections.push({group,start:i,count:n,cols,rows,x:T.pad,y:top,w,h:end-top,bar:group?{x:T.pad,y:top,w,h:T.barH}:null});
  maxW=Math.max(maxW,w);y=end+T.sectionGap;i=j;
 }
 return{boxes,sections,w:maxW+2*T.pad,h:end+T.pad};
}
// </tile-layout>
// <lazy-frames> Desktop start-up camera and which frames to load (only frames near the visible area are fetched). Pure (no DOM); node tests load this block verbatim.
// initialCamera: the "fit window" scale (centred, at most 100%) when it is at least LAZY.minScale; otherwise LAZY.minScale with the board's top-left corner LAZY.edge px from the viewport's.
// framesInView: indices of the boxes (board coordinates) that touch the viewport grown by `margin` (a fraction of its size), nearest to the centre first.
const LAZY={minScale:.5,edge:28,fitPad:56,margin:.5,concurrency:5};
function initialCamera(bw,bh,vw,vh){
 const fit=Math.max(.1,Math.min(1,(vw-LAZY.fitPad)/Math.max(bw,1),(vh-LAZY.fitPad)/Math.max(bh,1)));
 if(fit>=LAZY.minScale)return{scale:fit,panX:(vw-bw*fit)/2,panY:(vh-bh*fit)/2};
 return{scale:LAZY.minScale,panX:LAZY.edge,panY:LAZY.edge};
}
function framesInView(boxes,cam,vw,vh,margin){
 const mx=vw*margin,my=vh*margin,out=[];
 (boxes||[]).forEach((b,i)=>{const l=cam.panX+b.x*cam.scale,t=cam.panY+b.y*cam.scale,r=l+b.w*cam.scale,bt=t+b.h*cam.scale;
  if(r>-mx&&l<vw+mx&&bt>-my&&t<vh+my)out.push({i,d:Math.hypot((l+r)/2-vw/2,(t+bt)/2-vh/2)})});
 return out.sort((a,b)=>a.d-b.d||a.i-b.i).map(x=>x.i);
}
// </lazy-frames>
// <board-notes> Notes: free-standing HTML blocks on the board, outside every frame (project.notes). Pure (no DOM); node tests load this block verbatim.
// {id, path, x, y, width?, title?, anchor?}: x/y are board px, or measured from the top-left corner of the anchor frame's box (title included) when `anchor` names a frame.
// The server rejects bad entries; this function only keeps well-formed ones, so a hand-edited snapshot can never break the board.
const NOTE={width:320,max:20000};
function noteNum(v){return typeof v==='number'&&v>=0&&v<=NOTE.max}
function boardNotes(project){
 const list=project&&Array.isArray(project.notes)?project.notes:[],seen=new Set(),out=[];
 for(const n of list){
  if(!n||typeof n!=='object'||typeof n.id!=='string'||!/^[A-Za-z0-9_-]{1,120}$/.test(n.id)||seen.has(n.id)||typeof n.path!=='string'||!noteNum(n.x)||!noteNum(n.y))continue;
  const w=n.width==null?NOTE.width:n.width;if(!Number.isInteger(w)||w<40||w>4000)continue;
  seen.add(n.id);out.push({id:n.id,path:n.path,x:n.x,y:n.y,width:w,title:typeof n.title==='string'?n.title:'',anchor:typeof n.anchor==='string'?n.anchor:''});
 }
 return out;
}
// Top-left corner of a note on the board; `layout` is the result of tileLayout(project). An unknown anchor falls back to board coordinates.
function noteOrigin(note,project,layout){
 const i=note.anchor?(project.frames||[]).findIndex(f=>f.id===note.anchor):-1,b=i>=0&&layout.boxes[i]?layout.boxes[i]:{x:0,y:0};
 return{x:b.x+note.x,y:b.y+note.y};
}
// Target ids of the group title bars (one per grouped section; '' for a section without a bar). A group has no id of its own: its name is the identifier.
// 'group~<name>~title'; '~' and '%' in the name are percent-escaped so the name part never contains '~'. A name that starts another section later gets 'group~<name>~<n>~title' (n = 2, 3, ...).
// This is the only place that builds them; scripts/canvas.py (group_title_targets) mirrors it.
function groupTitleIds(sections){
 const seen=new Map();
 return sections.map(s=>{
  if(!s.bar)return'';
  const n=(seen.get(s.group)||0)+1;seen.set(s.group,n);
  return'group~'+s.group.replace(/%/g,'%25').replace(/~/g,'%7E')+(n>1?'~'+n:'')+'~title';
 });
}
// </board-notes>
// <qr-encoder> Minimal QR Code encoder (byte mode, error correction M, versions 1-10, UTF-8). No DOM, no network. qrEncode(text) -> {size,modules} or null when too long.
// Adapted from Project Nayuki QR Code generator (https://www.nayuki.io/page/qr-code-generator-library), MIT License, see NOTICE.
// SPDX-License-Identifier: MIT
function qrEncode(text){
 const T=[null,[16,10,1,16,0],[28,16,1,28,0],[44,26,1,44,0],[64,18,2,32,0],[86,24,2,43,0],[108,16,4,27,0],[124,18,4,31,0],[154,22,2,38,2],[182,22,3,36,2],[216,26,4,43,1]]; // [data codewords, EC per block, short blocks, short block data, long blocks (+1 byte)]
 const bytes=Array.from(new TextEncoder().encode(text));
 let ver=0;for(let v=1;v<=10;v++){if(4+(v<10?8:16)+8*bytes.length<=8*T[v][0]){ver=v;break}}
 if(!ver)return null;
 const [dataCw,ecLen,nShort,shortLen,nLong]=T[ver],size=ver*4+17;
 const bits=[];const put=(val,n)=>{for(let i=n-1;i>=0;i--)bits.push((val>>>i)&1)};
 put(4,4);put(bytes.length,ver<10?8:16);bytes.forEach(b=>put(b,8));
 put(0,Math.min(4,dataCw*8-bits.length));while(bits.length%8)bits.push(0);
 const data=[];for(let i=0;i<bits.length;i+=8)data.push(parseInt(bits.slice(i,i+8).join(''),2));
 for(let pad=0xEC;data.length<dataCw;pad^=0xEC^0x11)data.push(pad);
 const gfMul=(x,y)=>{let z=0;for(let i=7;i>=0;i--){z=(z<<1)^((z>>>7)*0x11D);z^=((y>>>i)&1)*x}return z};
 const div=new Array(ecLen).fill(0);div[ecLen-1]=1;for(let i=0,root=1;i<ecLen;i++){for(let j=0;j<ecLen;j++){div[j]=gfMul(div[j],root);if(j+1<ecLen)div[j]^=div[j+1]}root=gfMul(root,2)}
 const blocks=[];let k=0;
 for(let i=0;i<nShort+nLong;i++){const len=shortLen+(i<nShort?0:1),d=data.slice(k,k+len);k+=len;const r=new Array(ecLen).fill(0);for(const b of d){const f=b^r.shift();r.push(0);div.forEach((c,x)=>{r[x]^=gfMul(c,f)})}blocks.push({d,r})}
 const all=[];for(let i=0;i<=shortLen;i++)blocks.forEach(b=>{if(i<b.d.length)all.push(b.d[i])});for(let i=0;i<ecLen;i++)blocks.forEach(b=>all.push(b.r[i]));
 const mod=[],fn=[];for(let i=0;i<size;i++){mod.push(new Array(size).fill(false));fn.push(new Array(size).fill(false))}
 const setFn=(x,y,dark)=>{mod[y][x]=dark;fn[y][x]=true},bit=(v,i)=>((v>>>i)&1)!==0;
 for(let i=0;i<size;i++){setFn(6,i,i%2===0);setFn(i,6,i%2===0)}
 const finder=(cx,cy)=>{for(let dy=-4;dy<=4;dy++)for(let dx=-4;dx<=4;dx++){const d=Math.max(Math.abs(dx),Math.abs(dy)),x=cx+dx,y=cy+dy;if(x>=0&&x<size&&y>=0&&y<size)setFn(x,y,d!==2&&d!==4)}};
 finder(3,3);finder(size-4,3);finder(3,size-4);
 const pos=[];if(ver>1){const n=Math.floor(ver/7)+2,step=Math.ceil((ver*4+4)/(n*2-2))*2;pos.push(6);for(let p=size-7;pos.length<n;p-=step)pos.splice(1,0,p)}
 pos.forEach((cx,i)=>pos.forEach((cy,j)=>{if((i===0&&j===0)||(i===0&&j===pos.length-1)||(i===pos.length-1&&j===0))return;for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++)setFn(cx+dx,cy+dy,Math.max(Math.abs(dx),Math.abs(dy))!==1)}));
 const drawFormat=m=>{const d=(0<<3)|m;let r=d;for(let i=0;i<10;i++)r=(r<<1)^((r>>>9)*0x537);const f=((d<<10)|r)^0x5412; // ECC level M = 00
  for(let i=0;i<=5;i++)setFn(8,i,bit(f,i));setFn(8,7,bit(f,6));setFn(8,8,bit(f,7));setFn(7,8,bit(f,8));for(let i=9;i<15;i++)setFn(14-i,8,bit(f,i));
  for(let i=0;i<8;i++)setFn(size-1-i,8,bit(f,i));for(let i=8;i<15;i++)setFn(8,size-15+i,bit(f,i));setFn(8,size-8,true)};
 drawFormat(0);
 if(ver>=7){let r=ver;for(let i=0;i<12;i++)r=(r<<1)^((r>>>11)*0x1F25);const v=(ver<<12)|r;for(let i=0;i<18;i++){const b=bit(v,i),a=size-11+i%3,c=Math.floor(i/3);setFn(a,c,b);setFn(c,a,b)}}
 let n=0;for(let right=size-1;right>=1;right-=2){if(right===6)right=5;for(let vert=0;vert<size;vert++)for(let j=0;j<2;j++){const x=right-j,up=((right+1)&2)===0,y=up?size-1-vert:vert;if(!fn[y][x]&&n<all.length*8){mod[y][x]=bit(all[n>>>3],7-(n&7));n++}}}
 const MASKS=[(x,y)=>(x+y)%2===0,(x,y)=>y%2===0,(x,y)=>x%3===0,(x,y)=>(x+y)%3===0,(x,y)=>(Math.floor(x/3)+Math.floor(y/2))%2===0,(x,y)=>x*y%2+x*y%3===0,(x,y)=>(x*y%2+x*y%3)%2===0,(x,y)=>((x+y)%2+x*y%3)%2===0];
 const applyMask=m=>{for(let y=0;y<size;y++)for(let x=0;x<size;x++)if(!fn[y][x]&&MASKS[m](x,y))mod[y][x]=!mod[y][x]};
 const addHist=(run,h)=>{if(h[0]===0)run+=size;h.pop();h.unshift(run)};
 const countPat=h=>{const c=h[1],core=c>0&&h[2]===c&&h[3]===c*3&&h[4]===c&&h[5]===c;return(core&&h[0]>=c*4&&h[6]>=c?1:0)+(core&&h[6]>=c*4&&h[0]>=c?1:0)};
 const penalty=()=>{let res=0;
  for(let dir=0;dir<2;dir++){for(let a=0;a<size;a++){let color=false,run=0;const h=[0,0,0,0,0,0,0];for(let b=0;b<size;b++){const v=dir?mod[b][a]:mod[a][b];if(v===color){run++;if(run===5)res+=3;else if(run>5)res++}else{addHist(run,h);if(!color)res+=countPat(h)*40;color=v;run=1}}
   if(color){addHist(run,h);run=0}run+=size;addHist(run,h);res+=countPat(h)*40}}
  for(let y=0;y<size-1;y++)for(let x=0;x<size-1;x++){const c=mod[y][x];if(c===mod[y][x+1]&&c===mod[y+1][x]&&c===mod[y+1][x+1])res+=3}
  let dark=0;mod.forEach(r=>r.forEach(v=>{if(v)dark++}));res+=(Math.ceil(Math.abs(dark*20-size*size*10)/(size*size))-1)*10;return res};
 let best=0,bestP=Infinity;for(let m=0;m<8;m++){applyMask(m);drawFormat(m);const p=penalty();if(p<bestP){bestP=p;best=m}applyMask(m)}
 applyMask(best);drawFormat(best);
 return{size,modules:mod.map(r=>r.slice()),version:ver,mask:best};
}
// Inline SVG (black on white, 4-module quiet zone). Returns null when the text does not fit.
function qrSvg(text){
 const q=qrEncode(text);if(!q)return null;const N=q.size+8,NS='http://www.w3.org/2000/svg';let d='';
 q.modules.forEach((row,y)=>row.forEach((v,x)=>{if(v)d+='M'+(x+4)+' '+(y+4)+'h1v1h-1z'}));
 const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 '+N+' '+N);svg.setAttribute('shape-rendering','crispEdges');svg.setAttribute('aria-hidden','true');
 const bg=document.createElementNS(NS,'rect');bg.setAttribute('width',N);bg.setAttribute('height',N);bg.setAttribute('fill','#fff');
 const path=document.createElementNS(NS,'path');path.setAttribute('d',d);path.setAttribute('fill','#000');svg.append(bg,path);return svg;
}
// </qr-encoder>
// <keep-scroll> Opt-in scroll carry-over between frames (Flow view and /m/). An element with data-keep-scroll="<group>" hands its scroll position to the element with the same
// group name in the next frame that is shown. Put it on the scroll container; on a non-scrolling element the nearest scrollable ancestor (at most the .phone) is used.
// Frames without the attribute keep the old behaviour (a new frame starts at the top). The position is captured before the old frame is hidden (display:none drops scroll offsets)
// and applied after the new one is displayed and laid out; if its content is still too short to scroll that far (images / fonts / late layout), it is re-applied for a short while
// unless the user scrolls in the meantime.
function keepScrollGroup(el){return(el.getAttribute('data-keep-scroll')||'').trim()}
function keepScrollOwner(el,root){for(let n=el;n&&n!==root;n=n.parentElement){const c=getComputedStyle(n);if(/auto|scroll|overlay|hidden/.test(c.overflowX+' '+c.overflowY))return n}return root}
function keepScrollCapture(root){
 const saved=new Map();if(!root)return saved;
 root.querySelectorAll('[data-keep-scroll]').forEach(el=>{const g=keepScrollGroup(el);if(saved.has(g))return;const sc=keepScrollOwner(el,root);saved.set(g,{top:sc.scrollTop,left:sc.scrollLeft})});
 return saved;
}
let keepScrollRun=0;
function keepScrollRestore(root,saved){
 const run=++keepScrollRun;if(!root||!saved.size)return;
 const jobs=[],seen=new Set();
 root.querySelectorAll('[data-keep-scroll]').forEach(el=>{const g=keepScrollGroup(el),s=saved.get(g);if(!s||seen.has(g))return;seen.add(g);jobs.push({el:keepScrollOwner(el,root),top:s.top,left:s.left,last:null,done:false})});
 const t0=performance.now();
 const tick=()=>{
  if(run!==keepScrollRun||!root.isConnected||!root.getClientRects().length)return;
  let pending=false;
  for(const j of jobs){
   if(j.done)continue;const e=j.el;
   if(j.last&&(e.scrollTop!==j.last.top||e.scrollLeft!==j.last.left)){j.done=true;continue}
   e.scrollTop=j.top;e.scrollLeft=j.left;j.last={top:e.scrollTop,left:e.scrollLeft};
   if(Math.abs(j.last.top-j.top)>1||Math.abs(j.last.left-j.left)>1)pending=true;else j.done=true;
  }
  if(pending&&performance.now()-t0<1500)requestAnimationFrame(tick);
 };
 tick();
}
// </keep-scroll>
// <design-md> Tiny Markdown renderer for the read-only "Design notes" dialog (DESIGN.md). Pure (no DOM); node tests load this block verbatim.
// Supports headings, paragraphs, ordered / unordered (nested) lists, tables, quotes, rules, fenced code, **bold**, `code` and [text](http(s)/mailto link).
// Everything is HTML-escaped first; raw HTML is shown as text. Images are shown as plain text (no request); relative and other links show their text only.
function mdEsc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function mdSafeUrl(u){return /^(https?:\/\/[^\s<>"'`]+|mailto:[^\s<>"'`]+)$/i.test(u)}
const MD_IMG=/!\[[^\]\n]{0,500}\]\([^)\n]{0,2000}\)/y,MD_LINK=/\[([^\]\n]{1,500})\]\(\s*([^)\s]{1,2000})(?:\s+"[^"\n]*")?\s*\)/y;
function mdInline(s,noLink){
 let out='',i=0;const n=s.length;
 while(i<n){
  const c=s[i];
  if(c==='`'){let j=i;while(j<n&&s[j]==='`')j++;const run=s.slice(i,j);let k=s.indexOf(run,j);while(k>=0&&s[k+run.length]==='`'){k=s.indexOf(run,k+run.length+1)}
   if(k>j){let code=s.slice(j,k);if(code.length>1&&code[0]===' '&&code[code.length-1]===' '&&code.trim())code=code.slice(1,-1);out+='<code>'+mdEsc(code)+'</code>';i=k+run.length}else{out+=mdEsc(run);i=j}
   continue}
  if(c==='!'&&s[i+1]==='['){MD_IMG.lastIndex=i;const m=MD_IMG.exec(s);if(m){out+=mdEsc(m[0]);i+=m[0].length;continue}}
  if(c==='['&&!noLink){MD_LINK.lastIndex=i;const m=MD_LINK.exec(s);if(m){const label=mdInline(m[1],true);out+=mdSafeUrl(m[2])?'<a href="'+mdEsc(m[2])+'" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">'+label+'</a>':label;i+=m[0].length;continue}}
  if(c==='*'&&s[i+1]==='*'){const k=s.indexOf('**',i+2);if(k>i+2){out+='<strong>'+mdInline(s.slice(i+2,k),noLink)+'</strong>';i=k+2;continue}}
  out+=mdEsc(c);i++;
 }
 return out;
}
function mdCells(line){let t=line.trim();if(t[0]==='|')t=t.slice(1);if(t.length&&t[t.length-1]==='|'&&t[t.length-2]!=='\\')t=t.slice(0,-1);const cells=[];let cur='';for(let i=0;i<t.length;i++){const c=t[i];if(c==='\\'&&t[i+1]==='|'){cur+='|';i++}else if(c==='|'){cells.push(cur.trim());cur=''}else cur+=c}cells.push(cur.trim());return cells}
const MD_SEP=/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/,MD_LI=/^( *)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/,MD_FENCE=/^ {0,3}(```+|~~~+)/,MD_HEAD=/^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
function mdList(items){
 let out='';const st=[];
 const open=it=>{const ord=/^\d/.test(it.mark),start=ord?parseInt(it.mark,10):0;out+=ord?'<ol'+(start>1?' start="'+start+'"':'')+'>':'<ul>';st.push({ind:it.ind,ord})};
 const close=()=>{out+='</li></'+(st.pop().ord?'ol':'ul')+'>'};
 for(const it of items){
  while(st.length&&it.ind<st[st.length-1].ind)close();
  const top=st[st.length-1],ord=/^\d/.test(it.mark);
  if(top&&top.ind===it.ind&&top.ord===ord)out+='</li>';
  else if(top&&top.ind===it.ind){close();open(it)}
  else open(it);
  out+='<li>'+it.lines.map(x=>mdInline(x)).join('<br>');
 }
 while(st.length)close();
 return out;
}
function renderDesignMd(src){
 const lines=String(src).replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').replace(/\t/g,'    ').split('\n');
 let out='',i=0;
 const blank=l=>!l.trim();
 const special=(l,next)=>MD_FENCE.test(l)||MD_HEAD.test(l)||MD_LI.test(l)||/^ {0,3}>/.test(l)||/^ {0,3}([-*_])( *\1){2,} *$/.test(l)||(l.includes('|')&&next!==undefined&&MD_SEP.test(next)&&next.includes('-')&&(next.includes('|')||l.trim()[0]==='|'));
 while(i<lines.length){
  const l=lines[i];
  if(blank(l)){i++;continue}
  let m=MD_FENCE.exec(l);
  if(m){const f=m[1],buf=[];i++;while(i<lines.length&&!(lines[i].trim().startsWith(f[0].repeat(f.length))&&/^[`~]+\s*$/.test(lines[i].trim()))){buf.push(lines[i]);i++}i++;out+='<pre><code>'+mdEsc(buf.join('\n'))+'</code></pre>';continue}
  m=MD_HEAD.exec(l);
  if(m){const lv=Math.min(m[1].length+2,6);out+='<h'+lv+'>'+mdInline(m[2])+'</h'+lv+'>';i++;continue}
  if(/^ {0,3}([-*_])( *\1){2,} *$/.test(l)){out+='<hr>';i++;continue}
  if(/^ {0,3}>/.test(l)){const buf=[];while(i<lines.length&&/^ {0,3}>/.test(lines[i])){buf.push(lines[i].replace(/^ {0,3}> ?/,''));i++}out+='<blockquote>'+renderDesignMd(buf.join('\n'))+'</blockquote>';continue}
  if(l.includes('|')&&i+1<lines.length&&MD_SEP.test(lines[i+1])&&lines[i+1].includes('-')&&(lines[i+1].includes('|')||l.trim()[0]==='|')){
   const head=mdCells(l),al=mdCells(lines[i+1]).map(x=>/^:-+:$/.test(x)?'c':/^-+:$/.test(x)?'r':/^:-+$/.test(x)?'l':'');
   const cell=(tag,x,k)=>'<'+tag+(al[k]?' class="al-'+al[k]+'"':'')+'>'+mdInline(x||'')+'</'+tag+'>';
   out+='<div class="md-table"><table><thead><tr>'+head.map((x,k)=>cell('th',x,k)).join('')+'</tr></thead><tbody>';i+=2;
   while(i<lines.length&&!blank(lines[i])&&lines[i].includes('|')){const row=mdCells(lines[i]);out+='<tr>'+head.map((_,k)=>cell('td',row[k],k)).join('')+'</tr>';i++}
   out+='</tbody></table></div>';continue}
  m=MD_LI.exec(l);
  if(m){
   const items=[];
   while(i<lines.length){
    const mm=MD_LI.exec(lines[i]);
    if(mm&&!/^ {0,3}([-*_])( *\1){2,} *$/.test(lines[i])){items.push({ind:mm[1].length,mark:mm[2],lines:[mm[3]]});i++;continue}
    if(blank(lines[i])){let k=i;while(k<lines.length&&blank(lines[k]))k++;if(k<lines.length&&MD_LI.test(lines[k])&&!/^ {0,3}([-*_])( *\1){2,} *$/.test(lines[k])){i=k;continue}break}
    if(/^ +\S/.test(lines[i])&&!special(lines[i],lines[i+1])){items[items.length-1].lines.push(lines[i].trim());i++;continue}
    break;
   }
   out+=mdList(items);continue}
  const buf=[l.trim()];i++;
  while(i<lines.length&&!blank(lines[i])&&!special(lines[i],lines[i+1])){buf.push(lines[i].trim());i++}
  out+='<p>'+buf.map(x=>mdInline(x)).join('<br>')+'</p>';
 }
 return out;
}
// </design-md>
// <frame-ref> "Copy frame reference": plain text that points a person (or an AI chat) at one frame of this canvas. The page builds it from what it already knows:
// the address it was opened with (location.origin), the canvas id (/healthz), the snapshot rev and the frame. Never a file path, no server endpoint. Pure (no DOM); node tests load this block verbatim.
// o.rev is the snapshot shown in the text; the link carries &rev only for a history version (o.history), so a link copied from the latest version opens the live canvas.
// Numbered canvas ids are shown as #1, #2, … The stored id and /healthz id stay digits (a bare # is a URL fragment). A value that already starts with # is kept.
// Exactly 6 digits are left alone: that shape is also a legacy random id. /healthz display_id carries the hash for a real numbered canvas of any length.
function frameRefLink(origin,frameId,rev){const p=new URLSearchParams();p.set('view','flow');p.set('frame',String(frameId||''));if(rev)p.set('rev',rev);return String(origin||'').replace(/\/+$/,'')+'/#'+p.toString()}
function frameRefCanvasLabel(id){const s=String(id==null?'':id);if(!s||s.charAt(0)==='#')return s;return /^[1-9]\d*$/.test(s)&&s.length!==6?'#'+s:s}
function frameRefText(o,tr){
 const base=String(o.origin||'').replace(/\/+$/,'')+'/',f=o.frame||{},id=String(f.id||''),title=String(f.title||'').trim(),rev=o.rev?String(o.rev):'';
 const lines=[tr('c.ref.head'),o.canvasId?tr('c.ref.canvas',{url:base,id:frameRefCanvasLabel(o.canvasId)}):tr('c.ref.canvasNoId',{url:base})];
 if(rev)lines.push(tr('c.ref.rev',{rev}));
 lines.push(title&&title!==id?tr('c.ref.frame',{id,title}):tr('c.ref.frameNoTitle',{id}),tr('c.ref.link',{url:frameRefLink(o.origin,id,o.history?rev:'')}));
 return lines.join('\n');
}
// The newest usable snapshot in a GET /api/snapshots list (the server sorts it newest first); '' when there is none.
function latestSnapshotRev(list){if(!Array.isArray(list))return'';const it=list.find(x=>x&&x.valid!==false&&typeof x.rev==='string'&&x.rev);return it?it.rev:''}
// </frame-ref>
// <m-page> The /m/ phone page: read-only, one frame at a time. Reads only GET endpoints (frames), never comments or snapshot writes.
const IS_M_PAGE=location.pathname==='/m'||location.pathname.startsWith('/m/');
function mobileMain(){
 const $=id=>document.getElementById(id);
 const fail=msg=>{const p=document.createElement('p');p.className='m-error';p.setAttribute('role','alert');p.textContent=msg;document.body.append(p)};
 let boot;try{boot=JSON.parse($('m-boot').textContent)}catch(e){fail(tr('m.err.data'));return}
 const rev=boot.rev,frames=boot.frames||[],ids=frames.map(f=>f.id),meta=new Map(frames.map(f=>[f.id,f])),cache=new Map();
 if(!frames.length){fail(tr('m.err.noFrames'));return}
 if(typeof boot.html==='string')cache.set(boot.start,boot.html);
 const frameEl=$('m-frame'),phone=$('m-phone'),probe=$('m-probe'),demo=createDemoToast($('m-toast'));
 const start=ids.includes(boot.start)?boot.start:ids[0];let cur=null,seq=0;
 document.title=(boot.name||tr('m.defaultName'))+' · '+tr('h.mobile_preview')+(rev?tr('m.titleRev',{rev}):'');
 if(rev){$('m-rev').hidden=false;$('m-rev').textContent=tr('m.revLabel',{rev})}
 async function load(id){if(cache.has(id))return cache.get(id);const res=await fetch(flowFrameUrl(rev,meta.get(id).path),{cache:'no-store'});if(!res.ok)throw new Error(tr('m.err.page'));const text=await res.text();cache.set(id,text);return text}
 function insets(){const s=getComputedStyle(probe);return{t:parseFloat(s.paddingTop)||0,r:parseFloat(s.paddingRight)||0,b:parseFloat(s.paddingBottom)||0,l:parseFloat(s.paddingLeft)||0}}
 // Screens narrower than the design width (390) scale the frame down (frame box stays at design width). Phone-sized screens (up to M_FILL_MAX) get a frame as wide as the screen at 1x, so
 // the frame, its overlays and the page background always cover the same area (a 390 box centred on a 402/430 screen left strips that dimming scrims and bottom sheets did not reach).
 // Only wider screens (tablet / landscape, > M_FILL_MAX) keep the centred 390 box. Height always fills the screen.
 const M_FILL_MAX=560;
 function layout(){const f=meta.get(cur)||{width:390},i=insets(),aw=Math.max(1,innerWidth-i.l-i.r),ah=Math.max(1,innerHeight-i.t-i.b),s=Math.min(1,aw/f.width),w=aw<=M_FILL_MAX?Math.max(f.width,aw/s):f.width;
  frameEl.style.width=w+'px';frameEl.style.height=(ah/s)+'px';frameEl.style.transform='translate('+(i.l+(aw-w*s)/2)+'px,'+i.t+'px) scale('+s+')'}
 // A full-cover overlay (scrim) inside the frame is often a <button>; the page-wide button style gives it a 9px radius, which shows as rounded screen corners. Square it off on the phone page only.
 function squareCovers(){const pr=phone.getBoundingClientRect();if(!pr.width)return;phone.querySelectorAll('button,a,div,span,section').forEach(el=>{const r=el.getBoundingClientRect();if(r.width<pr.width-2||r.height<pr.height-2)return;const c=getComputedStyle(el);if((c.position==='absolute'||c.position==='fixed')&&parseFloat(c.borderTopLeftRadius)>0)el.style.borderRadius='0'})}
 function show(id,html){const keep=keepScrollCapture(phone);cur=id;frameEl.dataset.frameId=id;phone.innerHTML=html;phone.scrollTop=0;layout();squareCovers();keepScrollRestore(phone,keep);const bg=getComputedStyle(phone).backgroundColor;document.body.style.background=bg;document.documentElement.style.background=bg}
 async function go(id,push){if(!ids.includes(id)||(push&&id===cur))return;const mine=++seq;let html;try{html=await load(id)}catch(e){demo(tr('m.err.page'));return}if(mine!==seq)return;show(id,html);if(push)history.pushState({f:id},'')}
 frameEl.addEventListener('click',e=>{const a=flowClickAction(e.target,phone,ids);if(!a)return;e.preventDefault();e.stopPropagation();if(a.kind==='goto')go(a.id,true);else demo()},true);
 frameEl.addEventListener('submit',e=>e.preventDefault(),true);
 addEventListener('popstate',e=>{const f=e.state&&e.state.f;go(ids.includes(f)?f:start,false)});
 addEventListener('resize',layout);addEventListener('orientationchange',layout);
 history.replaceState({f:start},'');
 go(start,false).then(()=>{if(cur)setTimeout(()=>ids.forEach(id=>load(id).catch(()=>{})),300);else fail(tr('m.err.start'))});
}
// </m-page>
(async () => {
if(IS_M_PAGE){mobileMain();return}
const response=await fetch('/api/project');if(!response.ok)throw new Error(tr('c.err.project'));let project=await response.json();let liveProject=project;document.title=project.name+' · '+tr('h.ui_exploration_canvas');document.querySelector('.brand h1').textContent=project.name;document.querySelector('.brand p').textContent=project.id+' / '+project.revision;
const bulkSelected=new Set();let copyingFeedback=false;let flowMode=false;
const host=document.getElementById('board');
// Positions every frame node from tileLayout(proj) (CSS variables --x/--y, used by canvas.css) and adds one title bar per grouped section (a comment target outside every frame: id from groupTitleIds). Returns the nodes in DOM order.
function placeFrames(proj,nodes){
 const L=tileLayout(proj),out=[],ids=groupTitleIds(L.sections),at=(el,x,y)=>{el.style.setProperty('--x',x+'px');el.style.setProperty('--y',y+'px')};
 for(const [si,sec] of L.sections.entries()){
  if(sec.bar){const bar=document.createElement('div'),label=document.createElement('span');bar.className='group-bar';bar.id=ids[si];bar.dataset.comment=tr('c.groupTitle',{title:sec.group});bar.dataset.group=sec.group;bar.title=sec.group;label.textContent=sec.group;bar.append(label);at(bar,sec.bar.x,sec.bar.y);bar.style.width=sec.bar.w+'px';bar.style.height=sec.bar.h+'px';out.push(bar)}
  for(let k=sec.start;k<sec.start+sec.count;k++){at(nodes[k],L.boxes[k].x,L.boxes[k].y);out.push(nodes[k])}
 }
 return out;
}
// Builds the notes of `proj` (project.notes): free-standing blocks outside every frame. Same element convention as inside a frame (data-ui-id), host ids start with '~note~'.
async function buildNotes(proj,urlFor){
 const L=tileLayout(proj);
 return Promise.all(boardNotes(proj).map(async n=>{
  const el=document.createElement('div'),base='~note~'+n.id,o=noteOrigin(n,proj,L);el.className='board-note';el.dataset.noteId=n.id;el.id=base;el.style.width=n.width+'px';el.style.setProperty('--x',o.x+'px');el.style.setProperty('--y',o.y+'px');
  el.dataset.comment=tr('c.noteWhole',{title:n.title||n.id});
  try{const res=await fetch(urlFor(n.path),{cache:'no-store'});if(!res.ok)throw new Error(String(res.status));el.innerHTML=await res.text()}
  catch(e){el.replaceChildren(framePlaceholder(tr('c.err.frame',{path:n.path})));el.classList.add('note-error');return el}
  el.querySelectorAll('[data-ui-id]').forEach(e=>{e.id=base+'~'+e.dataset.uiId;e.dataset.comment=e.dataset.uiLabel||e.textContent.trim().slice(0,80)||e.dataset.uiId});
  return el;
 }));
}
// Frames are lazy: buildBoard() lays out an empty shell per frame (title, subtitle and a phone box of the right size with a placeholder) at once; the HTML of a frame
// is fetched only when it comes near the visible area (tile view), when it is shown (Flow view) or when something needs it (locating a comment). Each frame article
// carries data-load="idle|loading|loaded|error". A loaded frame is never unloaded. "?load=all" (or window.uicLoadAllFrames()) loads every frame.
const FRAME_REF_ICON='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
function frameShell(f){const article=document.createElement('article');article.className='frame';article.dataset.frame=f.title;article.dataset.frameId=f.id;article.dataset.load='idle';article.style.width=f.width+'px';article._frame=f;const header=document.createElement('header');header.className='frame-title';const h=document.createElement('h2');h.textContent=f.title;h.id=f.id+'~title';h.dataset.comment=tr('c.frameTitle',{title:f.title});const sub=document.createElement('p');sub.textContent=[f.group,f.state].filter(Boolean).join(' / ');if(sub.textContent){sub.id=f.id+'~subtitle';sub.dataset.comment=tr('c.frameSubtitle',{text:sub.textContent})}const ref=document.createElement('button');ref.type='button';ref.className='frame-ref';ref.title=tr('h.copy_frame_reference');ref.setAttribute('aria-label',tr('h.copy_frame_reference'));ref.innerHTML=FRAME_REF_ICON;header.append(h,ref,sub);const phone=document.createElement('div');phone.className='phone';phone.style.width=f.width+'px';phone.style.height=f.height+'px';phone.id=f.id+'--screen';phone.dataset.comment=tr('c.wholeLayout',{title:f.title});phone.append(framePlaceholder(tr('c.loading')));article.append(header,phone);return article}
function framePlaceholder(label){const ph=document.createElement('div');ph.className='frame-placeholder';ph.setAttribute('aria-hidden','true');ph.dataset.label=label;return ph}
function fillFrame(article,fragment){const f=article._frame,phone=article.querySelector('.phone');phone.innerHTML=fragment;phone.querySelectorAll('[data-ui-id]').forEach(el=>{el.id=f.id+'--'+el.dataset.uiId;el.dataset.comment=el.dataset.uiLabel||el.textContent.trim().slice(0,80)||el.dataset.uiId})}
// Lays out the shells of `proj` (no frame HTML is fetched here) plus its notes. Returns {nodes, frames: [article per frame], urlFor}.
async function buildBoard(proj,urlFor){const frames=proj.frames.map(frameShell);return{nodes:placeFrames(proj,frames).concat(await buildNotes(proj,urlFor)),frames,urlFor}}
const loader={gen:0,active:0,queue:new Map(),waiters:new Map(),frames:[],urlFor:null,boxes:[],hold:false};
function useBoard(built,proj){loader.gen++;loader.queue.clear();for(const list of loader.waiters.values())list.forEach(done=>done(false));loader.waiters.clear();loader.frames=built.frames;loader.urlFor=built.urlFor;loader.boxes=tileLayout(proj).boxes;host.replaceChildren(...built.nodes)}
function frameArticleById(id){return loader.frames.find(a=>a.dataset.frameId===id)||null}
function loaderPump(){
 while(loader.active<LAZY.concurrency&&loader.queue.size){let best=null,pri=Infinity;for(const [a,q] of loader.queue)if(q.pri<pri){pri=q.pri;best=a}loader.queue.delete(best);loadFrame(best)}
}
async function loadFrame(article){
 const gen=loader.gen,f=article._frame;article.dataset.load='loading';loader.active++;let ok=false;
 try{const res=await fetch(loader.urlFor(f.path),{cache:'no-store'});if(!res.ok)throw new Error(String(res.status));const fragment=await res.text();if(gen===loader.gen){fillFrame(article,fragment);ok=true}}
 catch(e){if(gen===loader.gen)console.warn(tr('c.err.frame',{path:f.path}),e)}
 finally{
  loader.active--;
  if(gen===loader.gen){article.dataset.load=ok?'loaded':'error';if(!ok){const phone=article.querySelector('.phone');phone.replaceChildren(framePlaceholder(tr('c.err.frame',{path:f.path})))}
   const list=loader.waiters.get(article);loader.waiters.delete(article);if(list)list.forEach(done=>done(ok));frameLoaded(article)}
  loaderPump();
 }
}
// Queue one frame. kind 'urgent' (shown or located now) goes first and also retries a failed frame; 'background' (Flow prefetch, load all) goes last. Resolves to true once filled.
function ensureFrame(article,kind){
 if(!article)return Promise.resolve(false);const st=article.dataset.load;
 if(st==='loaded')return Promise.resolve(true);
 if(st==='error'){if(kind!=='urgent')return Promise.resolve(false);article.dataset.load='idle'}
 return new Promise(done=>{const list=loader.waiters.get(article)||[];list.push(done);loader.waiters.set(article,list);
  if(article.dataset.load==='idle'){const pri=kind==='urgent'?-1e9-loader.waiters.size:1e9+loader.frames.indexOf(article),old=loader.queue.get(article);if(!old||pri<old.pri)loader.queue.set(article,{pri,kind})}
  loaderPump()});
}
function uicLoadAllFrames(){return Promise.all(loader.frames.map(a=>ensureFrame(a,'background')))}
window.uicLoadAllFrames=uicLoadAllFrames;
let visibleRaf=0;function scheduleVisible(){if(visibleRaf)return;visibleRaf=requestAnimationFrame(()=>{visibleRaf=0;queueVisible()})}
// Tile view: queue the idle frames near the visible area, nearest to its centre first; frames queued earlier for the view that are now far away are dropped (not cancelled once started).
function queueVisible(){
 if(flowMode||loader.hold||!loader.frames.length)return;
 for(const [a,q] of loader.queue)if(q.kind==='view')loader.queue.delete(a);
 framesInView(loader.boxes,{panX,panY,scale},availableWidth(),vp.clientHeight,LAZY.margin).forEach((i,rank)=>{const a=loader.frames[i];if(!a||a.dataset.load!=='idle')return;const old=loader.queue.get(a);if(!old||rank<old.pri)loader.queue.set(a,{pri:old?Math.min(old.pri,rank):rank,kind:old?old.kind:'view'})});
 loaderPump();
}
let loadedTimer=0;function frameLoaded(){clearTimeout(loadedTimer);loadedTimer=setTimeout(()=>{if(typeof refreshMissingLabels==='function')refreshMissingLabels()},120)}
useBoard(await buildBoard(project,path=>'/project/'+path),project);
const $=id=>document.getElementById(id),board=$('board'),vp=$('viewport');let panX=0,panY=0;let scale=.65,commentMode=false,selected=null,comments=[],historyRev=null,savedCamera=null;const revision=project.revision;let toastTimer;function toast(msg){$('toast').textContent=msg;$('toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').style.display='none',3200)}function dimensions(){const L=tileLayout(project),notes=[];let w=L.w,h=L.h;board.querySelectorAll(':scope>.board-note').forEach(n=>{if(!n.offsetWidth)return;const b={x:n.offsetLeft,y:n.offsetTop,w:n.offsetWidth,h:n.offsetHeight};notes.push(b);w=Math.max(w,b.x+b.w+TILE.pad);h=Math.max(h,b.y+b.h+TILE.pad)});board.style.width=w+'px';board.style.setProperty('--board-h',h+'px');return{...L,w,h,notes}}
function availableWidth(){return vp.clientWidth-(document.body.classList.contains('panel-open')&&innerWidth>1000?340:0)}
function apply(){board.style.transform=`translate(${panX}px,${panY}px) scale(${scale})`;$('zoom-value').textContent=Math.round(scale*100)+'%';updateMinimapViewport();scheduleVisible()}
// Start-up camera (also after switching versions): see initialCamera. "Fit window" in the zoom menu still fits the whole board at any scale.
function initView(){const d=dimensions(),c=initialCamera(d.w,d.h,availableWidth(),vp.clientHeight);scale=c.scale;panX=c.panX;panY=c.panY;apply()}
function fit(){const d=dimensions(),w=availableWidth(),h=vp.clientHeight;scale=Math.max(.1,Math.min(1,(w-56)/d.w,(h-56)/d.h));panX=(w-d.w*scale)/2;panY=(h-d.h*scale)/2;apply()}
function zoomAt(next,x,y){next=Math.max(.1,Math.min(3,next));const wx=(x-panX)/scale,wy=(y-panY)/scale;panX=x-wx*next;panY=y-wy*next;scale=next;apply()}
function centerZoom(next){zoomAt(next,availableWidth()/2,vp.clientHeight/2)}
$('export-ui').onclick=async()=>{
 const button=$('export-ui');if(button.disabled)return;if(historyRev){toast(tr('c.exportHist'));return}button.disabled=true;button.textContent=tr('c.exporting');
 try{
  const res=await fetch('/api/export-ui');if(!res.ok){const error=await res.json();throw new Error(error.error||tr('c.exportFailed'))}
  const disposition=res.headers.get('Content-Disposition')||'';
  const filename=disposition.match(/filename="([^"\r\n]+)"/)?.[1]||'ui-handoff.zip';
  download(await res.blob(),filename);toast(tr('c.exported',{n:res.headers.get('X-UI-Frame-Count')||project.frames.length}));
 }catch(e){toast(e.message)}finally{button.disabled=false;button.textContent=tr('h.export_ui_handoff')}
};
let listPort=4042;const refInfo={canvasId:'',rev:''};const loadListPort=()=>fetch('/healthz',{cache:'no-store'}).then(r=>r.json()).then(h=>{if(h&&h.list_port)listPort=h.list_port;if(h&&typeof h.display_id==='string'&&h.display_id)refInfo.canvasId=h.display_id;else if(h&&typeof h.id==='string')refInfo.canvasId=h.id}).catch(()=>{});loadListPort();
$('services').onclick=()=>{window.open('//'+location.hostname+':'+listPort+'/','_blank','noopener');loadListPort()};$('shortcuts').onclick=()=>{$('shortcuts-dialog').showModal()};$('close-shortcuts').onclick=()=>{$('shortcuts-dialog').close()};
$('zoom-out').onclick=()=>centerZoom(scale/1.2);$('zoom-in').onclick=()=>centerZoom(scale*1.2);
// Zoom dropdown: the same fit / centerZoom functions the old buttons used; the button label follows the scale (apply()).
const zoomBtn=$('zoom-trigger'),zoomMenu=$('zoom-menu');
function closeZoomMenu(){zoomMenu.hidden=true;zoomBtn.setAttribute('aria-expanded','false')}
function openZoomMenu(){closeHistoryMenu();const r=zoomBtn.getBoundingClientRect();zoomMenu.style.top=(r.bottom+4)+'px';zoomMenu.style.left=Math.max(8,Math.min(r.left,innerWidth-158))+'px';zoomMenu.hidden=false;zoomBtn.setAttribute('aria-expanded','true')}
zoomBtn.onclick=e=>{e.stopPropagation();if(zoomMenu.hidden)openZoomMenu();else closeZoomMenu()};
zoomMenu.addEventListener('click',e=>{const b=e.target.closest('[data-zoom]');if(!b)return;closeZoomMenu();const a=b.dataset.zoom;if(a==='fit')fit();else if(a==='actual')centerZoom(1);else if(a==='in')centerZoom(scale*1.2);else if(a==='out')centerZoom(scale/1.2)});
document.addEventListener('click',e=>{if(!zoomMenu.hidden&&!e.target.closest('#zoom-menu')&&!e.target.closest('#zoom-trigger'))closeZoomMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!zoomMenu.hidden){closeZoomMenu();zoomBtn.focus()}});
$('theme').onclick=()=>{document.body.classList.toggle('dark');$('theme').textContent=document.body.classList.contains('dark')?tr('h.light'):tr('h.dark')};function setMode(on){if(on&&historyRev){toast(tr('c.hist.noComment'));return}commentMode=on;document.body.classList.toggle('comment-mode',on);$('annotate').setAttribute('aria-pressed',String(on))}$('annotate').onclick=()=>setMode(!commentMode);function openPanel(){document.body.classList.add('panel-open');$('comments').hidden=false;$('open-comments').setAttribute('aria-expanded','true');renderComments()}function closePanel(){document.body.classList.remove('panel-open');$('comments').hidden=true;$('open-comments').setAttribute('aria-expanded','false')}function togglePanel(){if($('comments').hidden)openPanel();else closePanel()}$('open-comments').onclick=togglePanel;$('close-comments').onclick=closePanel;function clearSelection(){document.querySelectorAll('.comment-selected').forEach(e=>e.classList.remove('comment-selected'));selected=null}function cancel(){$('editor').close();clearSelection()}$('cancel').onclick=cancel;$('cancel-bottom').onclick=cancel;$('editor').addEventListener('cancel',clearSelection);board.addEventListener('click',e=>{let el=e.target.closest('[data-comment]');const plan=commentClickPlan({history:!!historyRev,editorOpen:$('editor').open,flow:flowMode,commentMode,hasTarget:!!el,onButton:!!e.target.closest('button')});if(plan==='close-editor'){$('editor').close();return}if(plan==='block'){e.preventDefault();if(flowMode)e.stopImmediatePropagation();return}if(plan==='hint'){toast(tr('c.demoHint'));return}if(plan!=='select')return;if(e.target.closest('svg'))el=e.target.closest('svg').parentElement.closest('[data-comment]')||el;e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();selectLayer(el);$('comment-text').value='';$('comment-form').dataset.clientId=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);$('save-error').textContent='';$('editor').show();$('comment-text').focus()},true);async function loadComments(){try{const res=await fetch('/api/comments');if(!res.ok)throw new Error(tr('c.err.comments'));comments=(await res.json()).comments;renderComments()}catch(e){toast(e.message)}}function renderComments(){$('comment-count').textContent=comments.length;$('panel-comment-count').textContent=comments.length;const list=$('comment-list');list.replaceChildren();if(!comments.length){const p=document.createElement('p');p.className='empty-comments';p.textContent=historyRev?tr('c.empty.hist'):tr('c.empty.none');list.append(p)}comments.forEach((c,i)=>{if($('comment-filter').value!=='all'&&c.status!==$('comment-filter').value)return;const item=document.createElement('div');item.className='comment-card';const context=document.createElement('div');context.className='context';const label=document.createTextNode('');label._base=`${i+1}. ${c.frame} / ${c.element}`;label.data=label._base+missingLabel(c);context.append(label);item.dataset.cid=c.id;item._label=label;const p=document.createElement('p');p.textContent=c.text;const state=document.createElement('p');state.textContent=({pending:tr('h.pending'),changed:tr('h.changed'),discussion:tr('h.needs_discussion')}[c.status]||tr('h.pending'))+(c.replies?.length?'\n'+c.replies.map(r=>r.text).join('\n'):'');const time=document.createElement('time');time.textContent=new Date(c.created_at).toLocaleString('zh-CN');const locate=document.createElement('button');locate.className='locate';locate.textContent=tr('c.locate');locate.onclick=()=>locateComment(c);item.append(context,p,state,time);if(historyRev){const actions=document.createElement('div');actions.className='comment-actions';actions.append(locate);item.append(actions)}else addCommentManagement(item,c,p,locate);list.append(item)});if(comments.length&&!list.children.length){const empty=document.createElement('p');empty.className='empty-comments';empty.textContent=tr('c.empty.state');list.append(empty)};refreshBulk();const pt=document.querySelector('#comments .panel-top h2');if(pt)pt.firstChild.textContent=historyRev?tr('c.histComments'):tr('h.design_comments')}// The frame a comment belongs to (its frame_id, or the "<frame id>--" prefix of the target), or null for targets outside frames.
function commentArticle(c){const id=c.frame_id||(String(c.target||'').includes('--')?String(c.target).split('--')[0]:'');return id?frameArticleById(id):null}
// '' when the target is on the board, or when its frame is not loaded yet (we cannot know yet); otherwise the "removed" label.
function missingLabel(c){if($(c.target))return '';const a=commentArticle(c);if(a&&a.dataset.load!=='loaded')return '';return historyRev?tr('c.missingInVersion'):tr('c.elementRemoved')}
function refreshMissingLabels(){const by=new Map(comments.map(c=>[c.id,c]));document.querySelectorAll('#comment-list .comment-card[data-cid]').forEach(item=>{const c=by.get(item.dataset.cid),label=item._label;if(c&&label)label.data=label._base+missingLabel(c)})}
async function locateComment(c){let el=$(c.target);if(!el){const a=commentArticle(c);if(a&&a.dataset.load!=='loaded'){await ensureFrame(a,'urgent');el=$(c.target)}}
if(!el){toast(tr('c.err.elementGone'));return}let k=scale;if(flowMode){const art=el.closest('.frame');if(art&&art.dataset.frameId!==flow.cur)await flowGo(art.dataset.frameId);if(!el.getClientRects().length){toast(tr('c.flow.noLocate'));return}k=parseFloat(document.documentElement.style.getPropertyValue('--flow-scale'))||1}const scroll=el.closest('.screen-scroll')||el.closest('.phone');if(scroll){const r=el.getBoundingClientRect(),sr=scroll.getBoundingClientRect();scroll.scrollTop+=(r.top+r.height/2-sr.top-sr.height/2)/k}if(!flowMode){const r=el.getBoundingClientRect(),v=vp.getBoundingClientRect();panX+=availableWidth()/2-(r.left+r.width/2-v.left);panY+=vp.clientHeight/2-(r.top+r.height/2-v.top);apply()}el.classList.add('comment-selected');setTimeout(()=>el.classList.remove('comment-selected'),3000)}
// Comment management never changes the annotation mode or the camera.
document.addEventListener('click',e=>{if(!e.target.closest('#comment-more'))$('comment-more').open=false});
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('comment-more').open=false});
$('comment-filter').onchange=()=>{bulkSelected.clear();closeBulkConfirmation();renderComments()};
async function updateComment(c,changes,deleting=false){
 if(historyRev)throw new Error(tr('c.err.histReadonly'));
 const response=await fetch('/api/comments/'+encodeURIComponent(c.id),{method:deleting?'DELETE':'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,revision,...changes})});
 const data=await response.json();if(!response.ok)throw new Error(data.error||tr('c.err.save'));
 if(deleting)comments=comments.filter(item=>item.id!==c.id);
 else comments=comments.map(item=>item.id===c.id?data.comment:item);
 renderComments();
}
function addCommentManagement(item,c,body,locate){
 const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.className='comment-check';checkbox.checked=bulkSelected.has(c.id);checkbox.setAttribute('aria-label',tr('c.pickComment',{text:c.text.slice(0,60)}));checkbox.onchange=()=>{if(checkbox.checked)bulkSelected.add(c.id);else bulkSelected.delete(c.id);closeBulkConfirmation();refreshBulk()};item.querySelector('.context').prepend(checkbox);
 const actions=document.createElement('div');actions.className='comment-actions';
 const status=document.createElement('select');status.setAttribute('aria-label',tr('c.statusLabel'));
 Object.entries({pending:tr('h.pending'),changed:tr('h.changed'),discussion:tr('h.needs_discussion')}).forEach(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;status.append(o)});status.value=c.status||'pending';
 const edit=document.createElement('button');edit.textContent=tr('c.edit');edit.type='button';
 const remove=document.createElement('button');remove.textContent=tr('c.delete');remove.type='button';remove.className='delete-comment';
 const error=document.createElement('p');error.className='comment-error';error.setAttribute('role','alert');
 const editor=document.createElement('div');editor.hidden=true;editor.className='comment-inline-editor';
 const textarea=document.createElement('textarea');textarea.maxLength=4000;textarea.rows=4;textarea.setAttribute('aria-label',tr('c.editText'));textarea.placeholder=tr('h.enter_to_save_shift_enter_for');
 const save=document.createElement('button');save.textContent=tr('c.save');save.type='button';
 const cancel=document.createElement('button');cancel.textContent=tr('h.cancel');cancel.type='button';
 editor.append(textarea,save,cancel);
 let busy=false;
 async function commit(changes,deleting=false){if(busy)return;busy=true;error.textContent='';[status,edit,remove,save,cancel].forEach(el=>el.disabled=true);try{await updateComment(c,changes,deleting)}catch(e){error.textContent=tr('c.retry',{msg:e.message});status.value=c.status||'pending'}finally{busy=false;[status,edit,remove,save,cancel].forEach(el=>el.disabled=false)}}
 status.onchange=()=>commit({status:status.value});
 edit.onclick=()=>{textarea.value=c.text;editor.hidden=false;body.hidden=true;actions.hidden=true;error.textContent='';textarea.focus()};
 cancel.onclick=()=>{editor.hidden=true;body.hidden=false;actions.hidden=false;error.textContent=''};
 save.onclick=()=>{const text=textarea.value.trim();if(!text){error.textContent=tr('c.needText');return}void commit({text})};
 bindCommentInput(textarea,()=>{if(!busy)save.click()});
 remove.onclick=()=>commit({},true);
 actions.append(locate,status,edit,remove);item.append(actions,editor,error);
}
function selectedComments(){return comments.filter(c=>bulkSelected.has(c.id))}
function visibleComments(){return comments.filter(c=>$('comment-filter').value==='all'||c.status===$('comment-filter').value)}
function refreshBulk(){
 if(historyRev){['copy-feedback','export','bulk-all','bulk-clear','bulk-apply','bulk-delete'].forEach(id=>$(id).disabled=true);$('comments').querySelector('.bulk-tools').hidden=true;return}
 $('bulk-all').disabled=false;
 const visible=visibleComments();const valid=new Set(comments.map(c=>c.id));for(const id of bulkSelected)if(!valid.has(id))bulkSelected.delete(id);
 $('copy-feedback').disabled=!bulkSelected.size||copyingFeedback;$('export').disabled=!bulkSelected.size;$('bulk-count').textContent=tr('c.selected',{n:bulkSelected.size});$('comments').querySelector('.bulk-tools').hidden=!bulkSelected.size;
 $('bulk-all').checked=visible.length>0&&visible.every(c=>bulkSelected.has(c.id));
 $('bulk-all').indeterminate=visible.some(c=>bulkSelected.has(c.id))&&!$('bulk-all').checked;
 $('bulk-all').disabled=!visible.length;
 ['bulk-clear','bulk-apply','bulk-delete'].forEach(id=>$(id).disabled=!bulkSelected.size);
}
$('bulk-all').onchange=()=>{visibleComments().forEach(c=>{if($('bulk-all').checked)bulkSelected.add(c.id);else bulkSelected.delete(c.id)});closeBulkConfirmation();renderComments()};
$('bulk-clear').onclick=()=>{bulkSelected.clear();closeBulkConfirmation();renderComments()};
let bulkBusy=false;
async function manageBulk(deleting){
 if(historyRev||bulkBusy||!bulkSelected.size)return;
 const ids=[...bulkSelected];bulkBusy=true;$('bulk-error').textContent='';$('bulk-dialog-error').textContent='';
 const controls=[...$('comments').querySelectorAll('button,input,select,textarea'),...$('bulk-confirm').querySelectorAll('button')];controls.forEach(el=>el.disabled=true);
 try{
  const res=await fetch('/api/comments/batch',{method:deleting?'DELETE':'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,revision,ids,status:$('bulk-status').value})});
  const data=await res.json();if(!res.ok)throw new Error(data.error||tr('c.err.bulk'));
  const updates=new Map(data.comments.map(c=>[c.id,c]));
  comments=deleting?comments.filter(c=>!updates.has(c.id)):comments.map(c=>updates.get(c.id)||c);
  bulkSelected.clear();closeBulkConfirmation();renderComments();toast(deleting?tr('c.bulkDeleted',{n:ids.length}):tr('c.bulkMarked',{n:ids.length}));
 }catch(e){($('bulk-confirm').open?$('bulk-dialog-error'):$('bulk-error')).textContent=tr('c.selectionKept',{msg:e.message})}
 finally{bulkBusy=false;controls.forEach(el=>el.disabled=false);refreshBulk()}
}
function closeBulkConfirmation(){if($('bulk-confirm').open)$('bulk-confirm').close()}
$('bulk-confirm').addEventListener('cancel',e=>{if(bulkBusy)e.preventDefault()});
$('bulk-apply').onclick=()=>manageBulk(false);
$('bulk-delete').onclick=()=>{$('bulk-confirm-label').textContent=tr('c.bulkConfirm',{n:bulkSelected.size});$('bulk-dialog-error').textContent='';$('bulk-confirm').showModal()};
$('bulk-cancel-delete').onclick=()=>{closeBulkConfirmation()};
$('bulk-confirm-delete').onclick=()=>manageBulk(true);
// The editor exposes the whole rendered frame tree, including SVG children.
function selectLayer(el){
 clearSelection();selected=el;el.classList.add('comment-selected');
 const frameOfEl=el.closest('.frame');$('selection-label').textContent=(frameOfEl?frameOfEl.dataset.frame:tr('c.canvas'))+' / '+el.dataset.comment;
 const phone=el.closest('.phone'),picker=$('layer-picker');picker.replaceChildren();
 const addOption=(node,depth)=>{const option=document.createElement('option');option.value=node.id;option.textContent='\u3000'.repeat(depth)+node.dataset.comment;picker.append(option)};
 if(phone){
  [phone,...phone.querySelectorAll('[data-comment]')].forEach(node=>{
   if(!node.getClientRects().length)return;
   let depth=0;for(let p=node;p!==phone;p=p.parentElement)depth++;
   addOption(node,depth);
  });
 }else{
  // Outside every phone: a "Canvas" top layer (a label, not a target) over the group title bars, the frame titles and the notes with their elements.
  const top=document.createElement('option');top.disabled=true;top.value='';top.textContent=tr('c.canvas');picker.append(top);
  board.querySelectorAll(':scope>.group-bar,:scope>.frame>.frame-title [data-comment],:scope>.board-note,:scope>.board-note [data-comment]').forEach(node=>{
   if(!node.getClientRects().length)return;
   const box=node.closest('.board-note,.frame-title,.group-bar');let depth=1;if(box.classList.contains('board-note'))for(let p=node;p!==box;p=p.parentElement)depth++;
   addOption(node,depth);
  });
 }
 picker.value=el.id;
 $('layer-parent').disabled=!el.parentElement.closest('[data-comment]');
}
$('layer-picker').onchange=e=>{const el=$(e.target.value);if(el)selectLayer(el)};
$('layer-parent').onclick=()=>{const parent=selected?.parentElement.closest('[data-comment]');if(parent)selectLayer(parent)};
// Both comment inputs use Enter to save and Shift+Enter for a native newline.
function bindCommentInput(input,save){
 let composing=false;
 input.addEventListener('compositionstart',()=>{composing=true});
 input.addEventListener('compositionend',()=>{composing=false});
 input.addEventListener('keydown',e=>{
  if(e.key!=='Enter'||e.isComposing||composing||e.keyCode===229)return;
  if(e.shiftKey)return;
  e.preventDefault();if(!e.repeat)save();
 });
}
bindCommentInput($('comment-text'),()=>{if(!$('save').disabled)$('comment-form').requestSubmit($('save'))});
$('comment-form').onsubmit=async e=>{e.preventDefault();if(historyRev||$('save').disabled)return;const text=$('comment-text').value.trim();if(!selected||!text){$('save-error').textContent=tr('c.needFeedback');return}const el=selected,frame=el.closest('.frame');const rect=el.getBoundingClientRect(),pr=(el.closest('.phone')||(frame?frame:board)).getBoundingClientRect();const payload={client_id:$('comment-form').dataset.clientId,excerpt:el.textContent.trim().slice(0,500),project_id:project.id,revision,target:el.id,frame_id:frame?frame.dataset.frameId:'',frame:frame?frame.dataset.frame:tr('c.canvas'),element:el.dataset.comment,text,...(flowMode?{}:{position:{x:(rect.left-pr.left)/pr.width,y:(rect.top-pr.top)/pr.height}})};$('save').disabled=true;$('save-error').textContent='';try{const res=await fetch('/api/comments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await res.json();if(!res.ok)throw new Error(data.error||tr('c.err.save'));comments.push(data.comment);cancel();renderComments();toast(tr('c.saved'))}catch(err){$('save-error').textContent=tr('c.textKept',{msg:err.message})}finally{$('save').disabled=false}};function feedback(rows){return tr('c.fbHead',{name:project.name,id:project.id,rev:revision})+rows.map((c,i)=>tr('c.fbRow',{i:i+1,frame:c.frame,element:c.element,target:c.target,text:c.text})).join('\n\n')}
$('copy-feedback').onclick=async()=>{
 $('comment-more').open=false;const rows=selectedComments();if(!rows.length||copyingFeedback)return;
 const text=feedback(rows);copyingFeedback=true;refreshBulk();let copied=false;
 try{
  try{if(navigator.clipboard){await navigator.clipboard.writeText(text);copied=true}}catch{}
  if(!copied)copied=copyTextFallback(text);
  if(copied)toast(tr('c.copied',{n:rows.length}));
  else{download(new Blob([text],{type:'text/plain;charset=utf-8'}),'ui-feedback.txt');toast(tr('c.downloaded',{n:rows.length}))}
 }catch(e){toast(tr('c.copyFailed'))}finally{copyingFeedback=false;refreshBulk()}
};
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
$('export').onclick=()=>{
 $('comment-more').open=false;const rows=selectedComments();if(!rows.length)return;
 download(new Blob([JSON.stringify({project_id:project.id,revision,comments:rows},null,2)],{type:'application/json'}),'ui-comments.json');
 toast(tr('c.exportedComments',{n:rows.length}))
};
window.addEventListener('resize',()=>{rebuildMinimap();apply()});  // the camera is kept; newly uncovered frames load


// Minimap chrome: one camera (panX/panY/scale). Thumbnail only when the frame set changes (resize, history switch).
const mm=$('minimap'),mmWorld=$('minimap-world'),mmView=$('minimap-viewport');
const MM_PAD=8,MM_MIN=20;let mmMap={scale:1,ox:0,oy:0,bw:1,bh:1};
function frameBoxes(){const L=dimensions();return{boxes:L.boxes,sections:L.sections,notes:L.notes,w:L.w,h:L.h}}
function rebuildMinimap(){if(!mm)return;const {boxes,sections,notes,w,h}=frameBoxes();const iw=mm.clientWidth-MM_PAD*2,ih=mm.clientHeight-MM_PAD*2;const s=Math.min(iw/Math.max(w,1),ih/Math.max(h,1));const ox=MM_PAD+(iw-w*s)/2,oy=MM_PAD+(ih-h*s)/2;mmMap={scale:s,ox,oy,bw:w,bh:h};mmWorld.replaceChildren();sections.forEach(b=>{if(!b.bar)return;const el=document.createElement('div');el.className='mm-bar';el.style.left=(ox+b.bar.x*s)+'px';el.style.top=(oy+b.bar.y*s)+'px';el.style.width=Math.max(2,b.bar.w*s)+'px';el.style.height=Math.max(2,b.bar.h*s)+'px';mmWorld.append(el)});boxes.forEach(b=>{const el=document.createElement('div');el.className='mm-frame';el.style.left=(ox+b.x*s)+'px';el.style.top=(oy+b.y*s)+'px';el.style.width=Math.max(2,b.w*s)+'px';el.style.height=Math.max(2,b.h*s)+'px';mmWorld.append(el)});notes.forEach(b=>{const el=document.createElement('div');el.className='mm-note';el.style.left=(ox+b.x*s)+'px';el.style.top=(oy+b.y*s)+'px';el.style.width=Math.max(2,b.w*s)+'px';el.style.height=Math.max(2,b.h*s)+'px';mmWorld.append(el)});updateMinimapViewport()}
function updateMinimapViewport(){if(!mm||!mmMap.scale)return;const s=mmMap.scale;const br=board.getBoundingClientRect(),vr=vp.getBoundingClientRect();const aw=availableWidth(),ah=vp.clientHeight;let left=mmMap.ox+((vr.left-br.left)/scale)*s;let top=mmMap.oy+((vr.top-br.top)/scale)*s;let width=(aw/scale)*s;let height=(ah/scale)*s;const cx=left+width/2,cy=top+height/2;if(width<MM_MIN){left=cx-MM_MIN/2;width=MM_MIN}if(height<MM_MIN){top=cy-MM_MIN/2;height=MM_MIN}mmView.style.left=left+'px';mmView.style.top=top+'px';mmView.style.width=width+'px';mmView.style.height=height+'px'}
function mmToPan(mx,my){const bx=(mx-mmMap.ox)/mmMap.scale,by=(my-mmMap.oy)/mmMap.scale;panX=availableWidth()/2-bx*scale;panY=vp.clientHeight/2-by*scale;apply()}
let mmDrag=null;
mmView.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();e.stopPropagation();mmDrag={id:e.pointerId,x:e.clientX,y:e.clientY,px:panX,py:panY};mmView.setPointerCapture(e.pointerId);mmView.classList.add('mm-dragging')});
mmView.addEventListener('pointermove',e=>{if(!mmDrag||mmDrag.id!==e.pointerId)return;const dx=e.clientX-mmDrag.x,dy=e.clientY-mmDrag.y;panX=mmDrag.px-dx/mmMap.scale*scale;panY=mmDrag.py-dy/mmMap.scale*scale;apply()});
function endMmDrag(e){if(!mmDrag||(e&&mmDrag.id!==e.pointerId))return;mmDrag=null;mmView.classList.remove('mm-dragging')}
mmView.addEventListener('pointerup',endMmDrag);mmView.addEventListener('pointercancel',endMmDrag);
mm.addEventListener('pointerdown',e=>{if(e.target===mmView||mmView.contains(e.target))return;if(e.button!==0)return;e.preventDefault();const r=mm.getBoundingClientRect();mmToPan(e.clientX-r.left,e.clientY-r.top)});

// Camera gestures stay outside the app preview and preserve annotation clicks.
let spaceHeld=false,drag=null,scrollDrag=null,suppressClickUntil=0;
function editingTarget(el){return !!el?.closest?.('input,textarea,select,[contenteditable="true"],dialog[open]')}
// Shift+C selects every current-revision comment and reuses the copy action.
document.addEventListener('keydown',e=>{
 if(e.code!=='KeyC'||!e.shiftKey||e.metaKey||e.ctrlKey||e.altKey||e.repeat||e.isComposing||e.keyCode===229||e.defaultPrevented)return;
 if(historyRev||$('comments').hidden||editingTarget(e.target)||document.querySelector('dialog[open]')||copyingFeedback)return;
 e.preventDefault();
 if(!comments.length){toast(tr('c.nothingToCopy'));return}
 $('comment-filter').value='all';bulkSelected.clear();comments.forEach(c=>bulkSelected.add(c.id));
 closeBulkConfirmation();renderComments();$('copy-feedback').click();
});
// C toggles annotation; D toggles the comments panel outside editing/dialogs.
document.addEventListener('keydown',e=>{
 if(!['KeyC','KeyD'].includes(e.code)||e.metaKey||e.ctrlKey||e.altKey||e.shiftKey||e.repeat||e.isComposing||e.keyCode===229||e.defaultPrevented)return;
 if(editingTarget(e.target)||document.querySelector('dialog[open]'))return;
 e.preventDefault();if(e.code==='KeyD')togglePanel();else setMode(!commentMode);
});
function stopDrag(){if(drag&&vp.hasPointerCapture(drag.id))vp.releasePointerCapture(drag.id);if(scrollDrag&&vp.hasPointerCapture(scrollDrag.id))vp.releasePointerCapture(scrollDrag.id);drag=null;scrollDrag=null;document.body.classList.remove('canvas-dragging')}
 document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&$('editor').open&&!document.querySelector('dialog[open]:not(#editor)')){e.preventDefault();cancel();return}
  if(flowMode||e.code!=='Space'||e.isComposing||e.keyCode===229||document.querySelector('dialog[open]:not(#editor)'))return;
  if(editingTarget(e.target))return;
  e.preventDefault();spaceHeld=true;document.body.classList.add('canvas-hand');
 });
document.addEventListener('keyup',e=>{if(e.code==='Space'){spaceHeld=false;document.body.classList.remove('canvas-hand')}});
window.addEventListener('blur',()=>{spaceHeld=false;document.body.classList.remove('canvas-hand');stopDrag()});
// Route browser zoom gestures to the canvas, including over chrome and dialogs.
document.addEventListener('wheel',e=>{
 if(flowMode||(!e.ctrlKey&&!e.metaKey))return;
 e.preventDefault();e.stopPropagation();
 const k=e.deltaMode===1?16:e.deltaMode===2?vp.clientHeight:1;
 const next=scale*Math.exp(-Math.max(-300,Math.min(300,e.deltaY*k))*.006);
 if(e.target.closest('#viewport')){const r=vp.getBoundingClientRect();zoomAt(next,e.clientX-r.left,e.clientY-r.top)}else centerZoom(next);
},{passive:false,capture:true});
document.addEventListener('keydown',e=>{
 if(flowMode||!(e.ctrlKey||e.metaKey)||e.altKey||e.isComposing||e.keyCode===229)return;
 const plus=['+','='].includes(e.key)||e.code==='NumpadAdd';
 const minus=['-','_'].includes(e.key)||e.code==='NumpadSubtract';
 const reset=e.key==='0';if(!plus&&!minus&&!reset)return;
 e.preventDefault();e.stopPropagation();centerZoom(reset?1:plus?scale*1.2:scale/1.2);
},true);
function wheelScroller(node,dy,dx){
 let el=node instanceof Element?node:null;
 if(!el||!el.closest('.phone'))return null;
 while(el&&!el.classList.contains('phone')){
  const s=getComputedStyle(el);
  const canY=(s.overflowY==='auto'||s.overflowY==='scroll')&&el.scrollHeight-el.clientHeight>1;
  const canX=(s.overflowX==='auto'||s.overflowX==='scroll')&&el.scrollWidth-el.clientWidth>1;
  if(dy&&canY)return el;
  if(dx&&canX)return el;
  el=el.parentElement;
 }
 return null;
}
// Wheel rounds: the first event of a round (quiet for >180ms before it) picks frame-scroll or canvas-pan; see <scroll-lock>.
const wheelRouter=createWheelRouter({gap:180,isFrame:el=>el.classList.contains('phone'),styleOf:el=>getComputedStyle(el)});
let lockedFrame=null,wheelEndTimer=0;
function setLockedFrame(f){if(lockedFrame===f)return;if(lockedFrame)lockedFrame.classList.remove('scroll-locked');lockedFrame=f;if(f)f.classList.add('scroll-locked')}
function endWheelRound(){clearTimeout(wheelEndTimer);wheelRouter.reset();setLockedFrame(null)}
vp.addEventListener('wheel',e=>{
 if(flowMode||e.altKey||e.ctrlKey||e.metaKey)return;
 const k=e.deltaMode===1?16:e.deltaMode===2?vp.clientHeight:1;
 const shift=e.shiftKey&&!e.deltaX;
 const dy=shift?0:e.deltaY*k,dx=(shift?e.deltaY:e.deltaX)*k;
 e.preventDefault();
 // Space + wheel over a screen forces the canvas for the whole round (decided at round start, like everything else).
 const r=wheelRouter.route({t:e.timeStamp||performance.now(),target:e.target instanceof Element?e.target:null,dx,dy,ctrl:false,space:spaceHeld});
 if(r.action==='scroll'){if(r.scroller){r.scroller.scrollTop+=dy;r.scroller.scrollLeft+=dx}}
 else if(r.action==='pan'){panX-=dx;panY-=dy;apply()}
 if(r.action!=='noop'){setLockedFrame(r.action==='scroll'?r.frame:null);clearTimeout(wheelEndTimer);wheelEndTimer=setTimeout(endWheelRound,180)}
},{passive:false});
window.addEventListener('blur',endWheelRound);
vp.addEventListener('pointerdown',e=>{
 if(flowMode||e.target.closest('#minimap')||e.pointerType==='touch'||!(e.button===0||e.button===1))return;
 e.preventDefault();suppressClickUntil=0;
 // A scrollable demo screen scrolls on drag too; only other areas pan the canvas.
 const scroller=e.button===0&&!spaceHeld?wheelScroller(e.target,1,1):null;
 if(scroller)scrollDrag={id:e.pointerId,x:e.clientX,y:e.clientY,top:scroller.scrollTop,left:scroller.scrollLeft,el:scroller,moved:false};
 else drag={id:e.pointerId,x:e.clientX,y:e.clientY,px:panX,py:panY,moved:false};
 // Capture only after movement, so a stationary click keeps its original target.
},true);
window.addEventListener('pointermove',e=>{
 if(scrollDrag&&scrollDrag.id===e.pointerId){
  const sdx=e.clientX-scrollDrag.x,sdy=e.clientY-scrollDrag.y;
  if(!scrollDrag.moved){if(Math.hypot(sdx,sdy)<=3)return;scrollDrag.moved=true;vp.setPointerCapture(e.pointerId);document.body.classList.add('canvas-dragging')}
  scrollDrag.el.scrollTop=scrollDrag.top-sdy;scrollDrag.el.scrollLeft=scrollDrag.left-sdx;
  return;
 }
 if(!drag||drag.id!==e.pointerId)return;
 const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
 if(!drag.moved){if(Math.hypot(dx,dy)<=3)return;drag.moved=true;vp.setPointerCapture(e.pointerId);document.body.classList.add('canvas-dragging')}
 panX=drag.px+dx;panY=drag.py+dy;apply();
});
window.addEventListener('pointerup',e=>{
 if(scrollDrag&&scrollDrag.id===e.pointerId){
  if(scrollDrag.moved)suppressClickUntil=performance.now()+400;
  stopDrag();
  return;
 }
 if(!drag||drag.id!==e.pointerId)return;
 if(drag.moved||spaceHeld||e.button===1)suppressClickUntil=performance.now()+400;
 stopDrag();
});
vp.addEventListener('dragstart',e=>e.preventDefault());
vp.addEventListener('pointercancel',stopDrag);vp.addEventListener('lostpointercapture',stopDrag);
vp.addEventListener('click',e=>{if(spaceHeld||performance.now()<suppressClickUntil){e.preventDefault();e.stopImmediatePropagation()}},true);
vp.addEventListener('auxclick',e=>{if(e.button===1)e.preventDefault()});

const toolbar=document.querySelector('.toolbar'),banner=$('history-banner');function syncToolbarHeight(){document.documentElement.style.setProperty('--toolbar-height',(toolbar.getBoundingClientRect().height+(banner.hidden?0:banner.getBoundingClientRect().height))+'px')}syncToolbarHeight();new ResizeObserver(syncToolbarHeight).observe(toolbar);new ResizeObserver(syncToolbarHeight).observe(banner);
// History: read-only viewing of snapshots/<rev>/ through GET /api/snapshots*. Nothing here writes; write controls are disabled while historyRev is set.
const histBtn=$('history'),histMenu=$('history-menu');
// Design notes: the read-only DESIGN.md of the canvas (or of the snapshot being viewed). GET /api/design or /api/snapshots/<rev>/design; {markdown:null} (no DESIGN.md) hides the button.
const dnBtn=$('design-notes'),dnDialog=$('design-dialog');
async function fetchDesign(rev){
 const res=await fetch(rev?'/api/snapshots/'+encodeURIComponent(rev)+'/design':'/api/design',{cache:'no-store'});
 if(!res.ok){let msg='';try{msg=(await res.json()).error}catch{}throw new Error(msg||tr('c.err.design'))}
 const data=await res.json();return typeof data.markdown==='string'?data.markdown:null;
}
async function syncDesignButton(){
 const want=historyRev;let md=null;
 try{md=await fetchDesign(want)}catch{md=null}
 if(historyRev===want&&dnBtn.hidden!==(typeof md!=='string')){dnBtn.hidden=typeof md!=='string';syncToolbarHeight()}
}
dnBtn.onclick=async()=>{
 const rev=historyRev;
 try{
  const md=await fetchDesign(rev);if(md===null){dnBtn.hidden=true;return}
  endWheelRound();
  $('dn-sub').textContent=rev?tr('c.designSubHist',{rev}):tr('c.designSubLive');
  const body=$('dn-body');if(md.trim())body.innerHTML=renderDesignMd(md);else{body.textContent=tr('c.designEmpty')}
  body.scrollTop=0;dnDialog.showModal();
 }catch(e){toast(e.message)}
};
$('dn-close').onclick=()=>dnDialog.close();
dnDialog.addEventListener('click',e=>{if(e.target!==dnDialog)return;const r=dnDialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dnDialog.close()});
dnDialog.addEventListener('close',()=>{$('dn-body').replaceChildren()});
function closeHistoryMenu(){histMenu.hidden=true;histBtn.setAttribute('aria-expanded','false')}
function fmtTime(iso){if(!iso)return tr('c.timeUnknown');const d=new Date(iso);return isNaN(d)?tr('c.timeUnknown'):d.toLocaleString(tr.lang==='zh'?'zh-CN':'en-US',{hour12:false})}
function setBrand(){const h=document.querySelector('.brand h1'),p=document.querySelector('.brand p');h.textContent=project.name;p.textContent=project.id+' / '+(historyRev?tr('c.revHist',{rev:historyRev}):project.revision);document.title=project.name+' · '+(historyRev?tr('c.histTitle',{rev:historyRev}):tr('h.ui_exploration_canvas'))}
function applyHistoryChrome(){
 const on=!!historyRev;document.body.classList.toggle('history-mode',on);banner.hidden=!on;
 $('annotate').disabled=on;$('annotate').title=on?tr('c.annHist'):tr('h.toggle_add_comment_mode_shortcut_c');
 $('export-ui').disabled=on;$('export-ui').title=on?tr('c.exportHistTitle'):tr('h.export_all_pages_of_the_current');
 histBtn.textContent=on?tr('c.histBtn',{rev:historyRev}):tr('h.history');syncDesignButton();syncToolbarHeight();
}
async function openHistoryMenu(){
 closeZoomMenu();
 const r=histBtn.getBoundingClientRect();histMenu.style.top=(r.bottom+4)+'px';histMenu.style.left=Math.max(8,Math.min(r.left,innerWidth-Math.min(360,innerWidth-16)-8))+'px';
 histMenu.hidden=false;histBtn.setAttribute('aria-expanded','true');histMenu.replaceChildren(Object.assign(document.createElement('p'),{className:'hm-empty',textContent:tr('c.loading')}));
 try{
  const res=await fetch('/api/snapshots',{cache:'no-store'});if(!res.ok)throw new Error(tr('c.err.histList'));
  const data=await res.json(),list=data.snapshots||[];histMenu.replaceChildren();refInfo.rev=latestSnapshotRev(list);
  const title=document.createElement('div');title.className='hm-title';title.textContent=tr('c.histMenuTitle',{n:list.length});histMenu.append(title);
  if(!list.length){const p=document.createElement('p');p.className='hm-empty';p.textContent=tr('c.histEmpty');histMenu.append(p)}
  list.forEach(it=>{
   const b=document.createElement('button');b.type='button';b.className='hm-item';b.setAttribute('role','menuitem');if(it.rev===historyRev)b.setAttribute('aria-current','true');
   const rev=document.createElement('span');rev.className='hm-rev';rev.textContent=it.rev;b.append(rev);
   if(it.current){const t=document.createElement('span');t.className='hm-tag';t.textContent=tr('c.sameRev');b.append(t)}
   const meta=document.createElement('span');meta.className='hm-meta';meta.textContent=it.valid?[fmtTime(it.created_at),tr('c.framesN',{n:it.frames}),tr('c.commentsN',{n:it.comments})].join(' · '):tr('c.snapBad');b.append(meta);
   b.disabled=!it.valid;b.onclick=()=>{closeHistoryMenu();openHistory(it.rev)};histMenu.append(b)
  });
 }catch(e){histMenu.replaceChildren(Object.assign(document.createElement('p'),{className:'hm-empty',textContent:e.message}))}
}
histBtn.onclick=e=>{e.stopPropagation();if(histMenu.hidden)openHistoryMenu();else closeHistoryMenu()};
document.addEventListener('click',e=>{if(!histMenu.hidden&&!e.target.closest('#history-menu')&&!e.target.closest('#history'))closeHistoryMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!histMenu.hidden){closeHistoryMenu();histBtn.focus()}});
async function openHistory(rev){
 const base='/api/snapshots/'+encodeURIComponent(rev);
 try{
  const [pr,cr]=await Promise.all([fetch(base+'/project',{cache:'no-store'}),fetch(base+'/comments',{cache:'no-store'})]);
  if(!pr.ok)throw new Error(tr('c.err.histRead',{rev}));
  const snap=await pr.json();if(!Array.isArray(snap.frames)||!snap.frames.length)throw new Error(tr('c.err.snapFrames'));
  const snapComments=cr.ok?((await cr.json()).comments||[]):[];
  const built=await buildBoard(snap,path=>base+'/'+path.split('/').map(encodeURIComponent).join('/'));
  if($('editor').open)$('editor').close();clearSelection();setMode(false);closeBulkConfirmation();bulkSelected.clear();
  if(!historyRev)savedCamera={panX,panY,scale};
  useBoard(built,snap);project=snap;historyRev=rev;comments=snapComments;if(flowMode)flowReset();
  $('history-banner-rev').textContent=rev;$('history-banner-meta').textContent=(snap.name?snap.name+' · ':'')+tr('c.histMeta',{frames:snap.frames.length,comments:snapComments.length});
  setBrand();applyHistoryChrome();renderComments();initView();rebuildMinimap();
 }catch(e){toast(e.message)}
}
async function backToCurrent(){
 if(!historyRev)return;
 try{
  const res=await fetch('/api/project',{cache:'no-store'});if(!res.ok)throw new Error(tr('c.err.current'));const fresh=await res.json();
  if(fresh.revision!==revision){location.reload();return}
  const built=await buildBoard(fresh,path=>'/project/'+path);
  useBoard(built,fresh);liveProject=fresh;project=fresh;historyRev=null;if(flowMode)flowReset();
  setBrand();applyHistoryChrome();await loadComments();rebuildMinimap();
  if(savedCamera){panX=savedCamera.panX;panY=savedCamera.panY;scale=savedCamera.scale;apply()}else initView();
  savedCamera=null;
 }catch(e){toast(e.message)}
}
$('history-back').onclick=backToCurrent;

// Flow view: the same frames as the tile view, one at a time in a 390 phone (CSS only, see body.flow-mode). data-goto jumps. Comment mode works here too: the comment click handler (registered earlier on the board, capture phase) stops the event before the jump handler below, so a click selects instead of jumping.
const flowBar=$('flow-bar'),demoToast=createDemoToast($('demo-toast')),flow={stack:[],cur:null};
function flowIds(){return project.frames.map(f=>f.id)}
function flowArticle(id){return [...host.children].find(a=>a.dataset.frameId===id)||null}
function updateFlowBar(){
 const ids=flowIds(),i=ids.indexOf(flow.cur),f=project.frames[i];$('flow-back').disabled=flow.stack.length<2;
 $('flow-title').textContent=f?tr('c.flowPage',{i:i+1,n:ids.length}):'';
 $('flow-frame-id').textContent=f?f.id:'';$('flow-screen-title').textContent=f?f.title:'';$('flow-screen-sub').textContent=f?[f.group,f.state].filter(Boolean).join(' / '):'';
 const rv=$('flow-rev');rv.replaceChildren();
 if(historyRev){const b=document.createElement('span');b.className='fb-rev-hist';b.textContent=tr('c.flowHist',{rev:historyRev});rv.append(b);rv.append(document.createTextNode(tr('c.flowLive',{rev:liveProject.revision||''})))}
 else rv.textContent=tr('c.flowCurrent',{rev:project.revision||''});
}
// Flow layout: scale the phone so its height never exceeds the visible canvas height and its width never exceeds the left column
// (wide: phone left / panel right; narrow canvas < 760: phone on top at <= 70% of the visible height, panel below, canvas scrolls). Never scales above 1.
const FLOW_PANEL_W=300,FLOW_GAP=32,FLOW_NARROW=760,FLOW_NARROW_H=.7;
function flowLayout(){
 const root=document.documentElement;
 if(!flowMode){['--flow-scale','--flow-w','--flow-h'].forEach(k=>root.style.removeProperty(k));if(document.body.classList.contains('flow-narrow'))document.body.classList.remove('flow-narrow');return}
 const f=project.frames.find(x=>x.id===flow.cur);if(!f)return;
 const panelOpen=document.body.classList.contains('panel-open');
 const narrow=(vp.clientWidth-(panelOpen?340:0))<FLOW_NARROW;if(document.body.classList.contains('flow-narrow')!==narrow)document.body.classList.toggle('flow-narrow',narrow);
 const cs=getComputedStyle(vp),pad=k=>parseFloat(cs[k])||0;
 const cw=vp.clientWidth-pad('paddingLeft')-pad('paddingRight'),ch=vp.clientHeight-pad('paddingTop')-pad('paddingBottom');
 const availW=narrow?cw:cw-FLOW_PANEL_W-FLOW_GAP,availH=narrow?vp.clientHeight*FLOW_NARROW_H:ch;
 let s=Math.min(1,availW/f.width,availH/f.height);if(!(s>0.02))s=0.02;s=Math.floor(s*1000)/1000;
 root.style.setProperty('--flow-scale',String(s));root.style.setProperty('--flow-w',(f.width*s)+'px');root.style.setProperty('--flow-h',(f.height*s)+'px');
}
let flowLayoutRaf=0;function flowLayoutSoon(){if(!flowMode||flowLayoutRaf)return;flowLayoutRaf=requestAnimationFrame(()=>{flowLayoutRaf=0;flowLayout()})}
addEventListener('resize',flowLayout);addEventListener('orientationchange',flowLayout);
new ResizeObserver(flowLayoutSoon).observe(vp);new MutationObserver(flowLayoutSoon).observe(document.body,{attributes:true,attributeFilter:['class']});
// The view lives in the URL hash (#view=flow&frame=<id>&rev=<rN>) so a refresh stays in the flow view, on the same page, on the same (history) version.
// The hash is only written while in the flow view; tile view never leaves a hash. Unknown view / frame / rev values fall back to the defaults.
function parseViewHash(){
 try{const p=new URLSearchParams(location.hash.replace(/^#/,''));if(p.get('view')!=='flow')return null;return{frame:p.get('frame')||'',rev:p.get('rev')||''}}catch{return null}
}
function syncViewHash(){
 let want='';
 if(flowMode){const p=new URLSearchParams();p.set('view','flow');if(flow.cur)p.set('frame',flow.cur);if(historyRev)p.set('rev',historyRev);want='#'+p.toString()}
 if(!flowMode&&!/(^|[#&])view=/.test(location.hash))return;
 if(location.hash===want||(!want&&!location.hash))return;
 try{history.replaceState(history.state,'',location.pathname+location.search+want)}catch{}
}
function flowShow(id,push,fresh){const art=flowArticle(id);if(!art)return;const prev=fresh?null:flowArticle(flow.cur),keep=keepScrollCapture(prev&&prev.querySelector('.phone'));host.querySelectorAll('.flow-current').forEach(a=>a.classList.remove('flow-current'));art.classList.add('flow-current');if(push)flow.stack.push(id);flow.cur=id;vp.scrollTop=0;vp.scrollLeft=0;const ph=art.querySelector('.phone');if(ph)ph.scrollTop=0;updateFlowBar();flowLayout();keepScrollRestore(ph,keep);syncViewHash()}
// Flow view loads the screen it shows first: a jump keeps the old screen until the new one is loaded (so the scroll carry-over sees real content); the first screen
// (fresh) is shown at once with its placeholder. After a screen is shown, the frames its data-goto buttons lead to are fetched when the browser is idle.
let flowSeq=0;
async function flowOpen(id,push,fresh,before){
 const mine=++flowSeq,art=flowArticle(id);if(!art)return;
 if(fresh){flowShow(id,push,fresh);await ensureFrame(art,'urgent');if(mine===flowSeq&&flowMode&&flow.cur===id){flowLayout();flowPrefetch(art)}return}
 if(art.dataset.load!=='loaded')await ensureFrame(art,'urgent');
 if(mine!==flowSeq||!flowMode)return;
 if(before)before();flowShow(id,push,fresh);flowPrefetch(art);
}
const idle=window.requestIdleCallback?f=>requestIdleCallback(f,{timeout:1500}):f=>setTimeout(f,200);
function flowPrefetch(art){idle(()=>{if(!flowMode||art.dataset.load!=='loaded')return;const ids=flowIds();new Set([...art.querySelectorAll('[data-goto]')].map(el=>(el.getAttribute('data-goto')||'').trim()).filter(v=>ids.includes(v))).forEach(v=>ensureFrame(flowArticle(v),'background'))})}
function flowReset(want){flow.stack=[];flow.cur=null;const ids=flowIds();return flowOpen(typeof want==='string'&&ids.includes(want)?want:flowPickStart(ids,project.flow_start,null),true,true)}
function flowGo(id){return id!==flow.cur?flowOpen(id,true):Promise.resolve()}
function flowBack(){if(flow.stack.length<2)return;return flowOpen(flow.stack[flow.stack.length-2],false,false,()=>flow.stack.pop())}
function setView(mode,start){
 const on=mode==='flow';if(on===flowMode)return;
 if($('editor').open)$('editor').close();clearSelection();setMode(false);if(on)endWheelRound();
 flowMode=on;document.body.classList.toggle('flow-mode',on);flowBar.hidden=!on;
 $('view-tile').setAttribute('aria-pressed',String(!on));$('view-flow').setAttribute('aria-pressed',String(on));
 ['zoom-out','zoom-in','zoom-trigger'].forEach(id=>{$(id).disabled=on});if(on)closeZoomMenu();applyHistoryChrome();
 if(on)flowReset(start);else{flowSeq++;host.querySelectorAll('.flow-current').forEach(a=>a.classList.remove('flow-current'));vp.scrollTop=0;vp.scrollLeft=0;flowLayout();syncViewHash();apply()}
 syncToolbarHeight();if(on)flowLayout();
}
$('view-tile').onclick=()=>setView('tile');$('view-flow').onclick=()=>setView('flow');
$('flow-back').onclick=()=>flowBack();$('flow-home').onclick=()=>flowReset();
board.addEventListener('click',e=>{
 if(!flowMode)return;const art=flowArticle(flow.cur),phone=art&&art.querySelector('.phone'),a=flowClickAction(e.target,phone,flowIds());
 if(!a)return;e.preventDefault();e.stopPropagation();if(a.kind==='goto')flowGo(a.id);else demoToast();
},true);
board.addEventListener('submit',e=>{if(flowMode)e.preventDefault()},true);
// Phone preview: QR + link built from the address this page was opened with (never hard-coded).
const ppDialog=$('phone-preview-dialog');
function previewUrl(){return location.origin+'/m/'+(historyRev?'?rev='+encodeURIComponent(historyRev):'')}
function isLocalHost(h){h=String(h).replace(/^\[|\]$/g,'').toLowerCase();return h==='localhost'||h.endsWith('.localhost')||h==='::1'||h==='0.0.0.0'||/^127\./.test(h)}
function openPreview(){
 endWheelRound();const url=previewUrl(),box=$('pp-qr');$('pp-url').value=url;$('pp-hint').hidden=!isLocalHost(location.hostname);
 const svg=qrSvg(url);box.replaceChildren();if(svg)box.append(svg);else{const s=document.createElement('span');s.className='pp-qr-fail';s.textContent=tr('c.qrTooLong');box.append(s)}
 $('pp-sub').textContent=historyRev?tr('c.ppSubHist',{rev:historyRev}):tr('h.scan_with_a_phone_to_open');
 $('pp-copy').textContent=tr('h.copy_preview_link');ppDialog.showModal();
}
let copyTimer=0;
$('pp-copy').onclick=async()=>{
 const input=$('pp-url'),url=input.value;let ok=false;
 try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(url);ok=true}}catch{}
 if(!ok){input.focus();input.select();input.setSelectionRange(0,url.length);try{ok=document.execCommand('copy')}catch{}}
 $('pp-copy').textContent=ok?tr('c.copied1'):tr('c.copyManual');clearTimeout(copyTimer);copyTimer=setTimeout(()=>{$('pp-copy').textContent=tr('h.copy_preview_link')},1500);
};
$('phone-preview').onclick=openPreview;$('pp-close').onclick=()=>ppDialog.close();
ppDialog.addEventListener('click',e=>{if(e.target!==ppDialog)return;const r=ppDialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)ppDialog.close()});

// Clipboard: the async API only exists in a secure context (https / localhost); a canvas opened over LAN http falls back to a hidden textarea + execCommand('copy'),
// which must run inside the click (no await before it), so callers build the text synchronously.
function copyTextFallback(text){const prev=document.activeElement,area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.top='0';area.style.left='0';area.style.opacity='0';document.body.append(area);area.focus();area.select();let ok=false;try{ok=document.execCommand('copy')}catch{}finally{area.remove();if(prev&&prev!==document.body&&prev.focus)try{prev.focus({preventScroll:true})}catch{}}return ok}
async function copyText(text){if(navigator.clipboard&&window.isSecureContext){try{await navigator.clipboard.writeText(text);return true}catch{}}return copyTextFallback(text)}
// Copy frame reference (text from <frame-ref>): the frame title bar button (tile view) and the button next to the frame id (Flow view). The snapshot rev is the version
// being viewed: the history rev, else the newest snapshot (GET /api/snapshots, fetched at start and refreshed on focus, when the history menu loads, when the pointer
// reaches a copy button and after each copy), so the copy itself never waits for the network. No snapshot yet: no rev line. The link has &rev only in a history version.
let refRevAt=0;
function refreshRefRev(force){if(!force&&Date.now()-refRevAt<5000)return;refRevAt=Date.now();fetch('/api/snapshots',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{if(d)refInfo.rev=latestSnapshotRev(d.snapshots)}).catch(()=>{})}
function frameRefFor(f){return frameRefText({origin:location.origin,canvasId:refInfo.canvasId,rev:historyRev||refInfo.rev,history:!!historyRev,frame:f},tr)}
async function copyFrameRef(f){if(!f)return;const ok=await copyText(frameRefFor(f));toast(ok?tr('c.ref.copied'):tr('c.copyFailed'));refreshRefRev(true)}
board.addEventListener('click',e=>{const b=e.target.closest('.frame-ref');if(!b||!board.contains(b))return;e.preventDefault();e.stopPropagation();const art=b.closest('.frame');copyFrameRef(art&&art._frame)});
board.addEventListener('pointerover',e=>{if(e.target.closest&&e.target.closest('.frame-ref'))refreshRefRev()});
$('flow-copy-ref').onclick=()=>copyFrameRef(project.frames.find(f=>f.id===flow.cur));
$('flow-copy-ref').addEventListener('pointerenter',()=>refreshRefRev());
addEventListener('focus',()=>refreshRefRev(true));
refreshRefRev(true);

const bootView=parseViewHash();
loader.hold=!!bootView;  // a Flow deep link loads its screen first: no tile-view loading until the view is set
initView();rebuildMinimap();syncDesignButton();
if(new URLSearchParams(location.search).get('load')==='all')uicLoadAllFrames();
if(bootView){
 await loadComments();
 if(bootView.rev)await openHistory(bootView.rev);
 loader.hold=false;setView('flow',bootView.frame);  // the deep-linked screen is the first one loaded
}else loadComments();
})().catch(error=>{const message=document.createElement('p');message.className='canvas-error';message.setAttribute('role','alert');message.textContent=tr('c.err.start',{msg:error.message});document.body.append(message);console.error(error)});
