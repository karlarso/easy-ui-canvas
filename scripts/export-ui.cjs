// SPDX-License-Identifier: Apache-2.0
// Export renderer. Uses installed Playwright and Chrome; never fetches project comments.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {pathToFileURL}=require('node:url');
function playwright(){
 const candidates=[process.env.UI_CANVAS_PLAYWRIGHT_MODULE,'playwright'];
 const cache=path.join(os.homedir(),'.npm','_npx');
 if(fs.existsSync(cache))for(const entry of fs.readdirSync(cache))candidates.push(path.join(cache,entry,'node_modules','playwright'));
 for(const candidate of candidates.filter(Boolean))try{return require(candidate)}catch{}
 throw Error('Playwright is not installed; install playwright and Chromium or Google Chrome');
}
(async()=>{
 const root=process.argv[2],config=JSON.parse(fs.readFileSync(path.join(root,'project.json'),'utf8'));
 const {chromium}=playwright();let browser;
 try{browser=await chromium.launch({headless:true})}catch{browser=await chromium.launch({headless:true,channel:'chrome'})}
 try{
  for(const frame of config.frames){
   const page=await browser.newPage({viewport:{width:frame.width,height:frame.height},deviceScaleFactor:1});
   await page.goto(pathToFileURL(path.join(root,'pages',frame.id+'.html')).href,{waitUntil:'load'});
   await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode()))});
   await page.evaluate(()=>{
    const phone=document.querySelector('.phone');
    for(const el of [...phone.querySelectorAll('*')].reverse()){
     const style=getComputedStyle(el);
     if(['auto','scroll'].includes(style.overflowY)&&el.scrollHeight>el.clientHeight){el.style.height=el.scrollHeight+'px';el.style.maxHeight='none';el.style.overflowY='visible';el.style.flexShrink='0'}
    }
    phone.style.height=Math.max(phone.clientHeight,phone.scrollHeight)+'px';phone.style.overflow='visible';
   });
   await page.locator('.phone').screenshot({path:path.join(root,'previews',frame.id+'.png'),animations:'disabled'});
   await page.close();
  }
 }finally{await browser.close()}
})().catch(e=>{process.stderr.write(e.message+'\n');process.exit(1)});
