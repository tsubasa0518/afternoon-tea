// Preserve the reference handlers and data attributes; extend only local filtering.
st.cat.unknown=true;
const sweetEvents=new Set(['halloween','xmas','valentine','whiteday','collab','season']);
const shopSearch=document.getElementById('shop-search'),themeSearch=document.getElementById('theme-search'),priceFilter=document.getElementById('price-filter');
function normalizeText(value){return String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/\s+/g,' ').trim()}
function priceMatches(plan){
 const key=priceFilter.value,raw=plan.dataset.price;
 if(key==='all')return true;
 if(raw===undefined||raw==='')return key==='unknown';
 const price=Number(raw);if(!Number.isFinite(price))return key==='unknown';
 return key==='low'?price<=6000:key==='mid'?price>6000&&price<10000:key==='high'?price>=10000:false;
}
let filterRevision=0;
apply=function(){
 filterRevision++;
 let shops=0,plans=0;
 const q=normalizeText(shopSearch.value),theme=normalizeText(themeSearch.value);
 const selected=Array.from(st.sw),sweets=selected.filter(k=>!sweetEvents.has(k)),events=selected.filter(k=>sweetEvents.has(k));
 document.querySelectorAll('.card').forEach(card=>{
  const name=card.querySelector('header');
  const storeMatches=!!st.cat[card.dataset.cat]&&normalizeText(name?name.textContent:'').includes(q);
  let count=0;
  card.querySelectorAll('.plan').forEach(plan=>{
   const title=plan.querySelector('.theme');
   const tags=(plan.dataset.sw||'').split(' ');
   const tagsMatch=(!sweets.length||sweets.some(k=>tags.includes(k)))&&(!events.length||events.some(k=>tags.includes(k)));
   const ok=storeMatches&&tagsMatch&&normalizeText(title?title.textContent:'').includes(theme)&&priceMatches(plan)&&(!st.x.pk||plan.dataset.pk==='1')&&(!st.x.wd||plan.dataset.wd==='1')&&(!st.x.we||plan.dataset.we==='1');
   plan.hidden=!ok;if(ok)count++;
  });
  card.classList.toggle('hide',count===0);if(count){shops++;plans+=count}
 });
 document.querySelectorAll('.cat').forEach(group=>{
  group.classList.toggle('hide',!st.cat[group.dataset.cat]);
  const count=group.querySelectorAll('.card:not(.hide)').length,label=group.querySelector('.cnt');if(label)label.textContent=count+'件';
 });
 document.querySelectorAll('section.area').forEach(area=>{const label=area.querySelector('.acnt');if(label)label.textContent=area.querySelectorAll('.card:not(.hide)').length+'件'});
 document.getElementById('filter-status').textContent='表示 '+shops+'店舗・'+plans+'プラン';
 const active=q||theme||priceFilter.value!=='all'||selected.length||Object.values(st.x).some(Boolean)||Object.values(st.cat).some(on=>!on);
 document.getElementById('no-results').hidden=shops>0||(document.querySelectorAll('.card').length===0&&!active);
};
shopSearch.addEventListener('input',apply);themeSearch.addEventListener('input',apply);priceFilter.addEventListener('change',apply);
function resetFilters(){
 document.querySelectorAll('.fb').forEach(button=>button.setAttribute('aria-pressed',button.dataset.cat?'true':'false'));
 Object.keys(st.cat).forEach(key=>st.cat[key]=true);Object.keys(st.x).forEach(key=>st.x[key]=false);st.sw.clear();
 shopSearch.value='';themeSearch.value='';priceFilter.value='all';apply();
}
document.getElementById('reset-filters').addEventListener('click',resetFilters);
resetFilters();
const initialRevision=filterRevision;
window.addEventListener('pageshow',event=>{
 // A slow initial load must not clear choices already made on this visit.
 if(!event.persisted&&filterRevision!==initialRevision)return;
 resetFilters();
 // History may restore form values after pageshow. Do not overwrite a new user choice.
 const revision=filterRevision;
 setTimeout(()=>{if(filterRevision===revision)resetFilters()},0);
});
