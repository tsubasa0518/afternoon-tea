// Run the real generated filter script against DOM records parsed from its HTML.
const fs=require('fs'),vm=require('vm'),payload=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)},add(k){n.classes.add(k)}};return n}
const cards=payload.cards.map(record=>{const c=node(record.dataset);c.plans=record.plans.map(p=>{const x=node(p.dataset);x.querySelector=()=>({textContent:p.name});return x});c.querySelector=()=>({textContent:record.name});c.querySelectorAll=()=>c.plans;return c});
const buttons=[];for(const cat of ['cafe','hotel','lux','unknown'])buttons.push(node({cat}));for(const x of ['wd','we'])buttons.push(node({x}));for(const sw of payload.buttons)buttons.push(node({sw:sw.key}));
const ids={};for(const id of ['price-filter','filter-status','no-results','reset-filters','area-toggle','area-links'])ids[id]=node();
const document={getElementById(id){return ids[id]||null},querySelector(){return null},querySelectorAll(q){return q==='.card'?cards:q==='.fb'?buttons:[]}};
vm.runInNewContext(payload.js,{document,window:{addEventListener(){}},setTimeout(){}});
function assert(value,message){if(!value)throw Error(message)}
function reset(){ids['reset-filters'].events.click()}
function click(key,kind='sw'){buttons.find(b=>b.dataset[kind]===key).events.click()}
function result(){const plans=cards.flatMap(c=>c.plans.filter(p=>!p.hidden));const shops=cards.filter(c=>!c.classes.has('hide'));assert(shops.every(c=>c.plans.some(p=>!p.hidden)),'no empty matching shop');assert(cards.filter(c=>c.classes.has('hide')).every(c=>c.plans.every(p=>p.hidden)),'only matching shop');assert(ids['filter-status'].textContent===`表示 ${shops.length}店舗・${plans.length}プラン`,'status counts');return {shops:shops.length,plans:plans.length}}
assert(result().plans===8,'all plans initially');
for(const button of payload.buttons){if(payload.eventKeys.includes(button.key))continue;reset();click(button.key);assert(result().plans===button.count,'single button count '+button.key)}
reset();click('ichigo');click('scone');assert(result().plans===4&&result().shops===2,'OR union with overlap counted once');
click('wd','x');assert(result().plans===2,'OR sweets AND weekday on same plan');
reset();click('ichigo');click('scone');ids['price-filter'].value='high';ids['price-filter'].events.change();assert(result().plans===2,'OR sweets AND price above 8000');
reset();click('grape');click('choco');assert(result().plans===3,'grape OR chocolate, both counted once');
reset();click('hotel','cat');assert(cards.filter(c=>c.dataset.cat==='hotel').every(c=>c.classes.has('hide')),'category combines with sweets');
reset();assert(result().plans===8,'reset all');
process.stdout.write('all single-button counts and OR/AND combinations passed');
