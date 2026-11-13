// Exercise the generated filter script, including reload/history restoration.
const vm=require('vm'),fs=require('fs'),code=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){
 const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),
  getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},
  addEventListener(k,f){this.events[k]=f}};
 n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)},add(k){n.classes.add(k)}};
 return n;
}
function plan(price,wd='0',we='0'){return node({price,wd,we})}
function card(cat,plans){const c=node({cat});c.plans=plans;c.querySelectorAll=()=>plans;return c}
const a=card('hotel',[plan('7000','1'),plan('11000','0','1')]);
const b=card('cafe',[plan('','0','1')]),cards=[a,b],buttons=[];
for(const cat of ['hotel','cafe','lux','unknown'])buttons.push(node({cat}));
for(const x of ['wd','we'])buttons.push(node({x}));
const groups=['hotel','cafe','lux'].map(cat=>{
 const g=node({cat});g.querySelectorAll=()=>cards.filter(c=>c.dataset.cat===cat&&!c.classes.has('hide'));
 g.querySelector=()=>({textContent:''});return g;
});
const area=node();area.querySelector=()=>({textContent:''});
area.querySelectorAll=()=>cards.filter(c=>!c.classes.has('hide'));
const ids={};
for(const id of ['price-filter','filter-status','no-results','reset-filters','area-toggle','area-links'])ids[id]=node();
const document={getElementById(id){return ids[id]||null},querySelector(){return null},
 querySelectorAll(q){return q==='.card'?cards:q==='.cat'?groups:q==='.fb'?buttons:q==='section.area'?[area]:[]}};
const pageEvents={},pending=[],window={addEventListener(name,fn){pageEvents[name]=fn}};
ids['price-filter'].value='high';
buttons.forEach(b=>b.attrs['aria-pressed']=b.dataset.cat?'false':'true');
vm.runInNewContext(code,{document,window,setTimeout(fn){pending.push(fn)}});
function flush(){while(pending.length)pending.shift()()}
function assert(v,m){if(!v)throw Error(m)}
function visible(){return cards.flatMap(c=>c.plans).filter(p=>!p.hidden).length}
function click(key,value){buttons.find(b=>b.dataset[key]===value).events.click()}
function price(value){ids['price-filter'].value=value;ids['price-filter'].events.change()}
function reset(){ids['reset-filters'].events.click()}
function assertReset(label){
 assert(ids['price-filter'].value==='all',label+' fields');
 assert(buttons.every(b=>b.attrs['aria-pressed']===(b.dataset.cat?'true':'false')),label+' buttons');
 assert(cards.every(c=>!c.classes.has('hide')&&c.plans.every(p=>!p.hidden)),label+' visibility');
 assert(ids['filter-status'].textContent==='表示 2店舗・3プラン',label+' counts');
}
assertReset('first load / reload');
assert(ids['area-links'].hidden&&ids['area-toggle'].attrs['aria-expanded']==='false','area initially closed');
if(process.env.TEST_EARLY_CHOICE){
 click('x','wd');pageEvents.pageshow({persisted:false});flush();
 assert(visible()===1,'early choice preserved');reset();
}else{
 pageEvents.pageshow({persisted:false});ids['price-filter'].value='high';flush();
 assertReset('late initial restoration');
}
click('x','wd');assert(visible()===1&&!a.plans[0].hidden,'weekday');
const status=ids['filter-status'].textContent;
ids['area-toggle'].events.click();
assert(!ids['area-links'].hidden&&ids['area-toggle'].attrs['aria-expanded']==='true','expand areas');
assert(visible()===1&&ids['filter-status'].textContent===status,'disclosure leaves filters unchanged');
ids['area-toggle'].events.click();assert(ids['area-links'].hidden,'collapse areas');
price('high');assert(visible()===0&&!ids['no-results'].hidden,'weekday AND price gives no results');
reset();assertReset('manual reset');
click('x','we');assert(visible()===2&&a.plans[0].hidden,'weekend');
click('x','wd');assert(visible()===3,'weekday OR weekend');
price('high');assert(visible()===1&&!a.plans[1].hidden,'day OR AND price');
reset();
const unknownDay=plan('7000'),both=plan('7000','1','1');
a.plans.push(unknownDay,both);reset();assert(visible()===5,'unconfirmed days included by default');
click('x','wd');assert(visible()===2&&!both.hidden&&unknownDay.hidden,'weekday includes daily plans');
click('x','we');assert(visible()===4&&!both.hidden&&unknownDay.hidden,'OR overlap counted once');
click('x','wd');assert(visible()===3&&a.plans[0].hidden,'turn weekday off');
click('x','we');assert(visible()===5&&!unknownDay.hidden,'turn both off');
a.plans.splice(-2);reset();
price('unknown');assert(visible()===1&&!b.plans[0].hidden,'unknown price');
reset();click('cat','hotel');assert(a.classes.has('hide')&&visible()===1,'category');
pageEvents.pageshow({persisted:true});assertReset('history return');
ids['price-filter'].value='high';flush();assertReset('late history restoration');
pageEvents.pageshow({persisted:true});price('high');flush();
assert(visible()===1&&!a.plans[1].hidden,'new choice survives queued reset');
reset();assertReset('manual after history');
const unknown=card('unknown',[plan('')]);cards.push(unknown);click('cat','unknown');
assert(unknown.classes.has('hide'),'unknown category can filter');reset();
assert(!unknown.classes.has('hide')&&!unknown.plans[0].hidden,'reset includes unknown category');
cards.pop();reset();assertReset('all categories restored');
cards.length=0;click('x','wd');assert(!ids['no-results'].hidden,'zero-store selected option');
reset();assert(ids['no-results'].hidden,'zero-store reset');
