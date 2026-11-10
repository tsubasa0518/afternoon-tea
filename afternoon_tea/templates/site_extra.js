const priceFilter=document.getElementById('price-filter');
const areaToggle=document.getElementById('area-toggle'),areaLinks=document.getElementById('area-links');
function priceMatches(plan){
 const key=priceFilter.value,raw=plan.dataset.price;
 if(key==='all')return true;
 if(raw===undefined||raw==='')return key==='unknown';
 const price=Number(raw);if(!Number.isFinite(price))return key==='unknown';
 return key==='low'?price<=6000:key==='mid'?price>6000&&price<10000:key==='high'?price>=10000:false;
}
let filterRevision=0,areaRevision=0;
function apply(){
 filterRevision++;
 let shops=0,plans=0;
 const sweets=Array.from(st.sw);
 document.querySelectorAll('.card').forEach(card=>{
  const storeMatches=!!st.cat[card.dataset.cat];
  let count=0;
  card.querySelectorAll('.plan').forEach(plan=>{
   const tags=(plan.dataset.sw||'').split(' ');
   const tagsMatch=!sweets.length||sweets.some(key=>tags.includes(key));
   const daysMatch=(!st.x.wd&&!st.x.we)||(st.x.wd&&plan.dataset.wd==='1')||(st.x.we&&plan.dataset.we==='1');
   const ok=storeMatches&&tagsMatch&&priceMatches(plan)&&daysMatch;
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
 const active=priceFilter.value!=='all'||sweets.length||Object.values(st.x).some(Boolean)||Object.values(st.cat).some(on=>!on);
 document.getElementById('no-results').hidden=shops>0||(document.querySelectorAll('.card').length===0&&!active);
}
function setAreaExpanded(expanded){
 areaLinks.hidden=!expanded;areaToggle.setAttribute('aria-expanded',String(expanded));
 areaToggle.textContent=expanded?'閉じる':'詳細';
}
areaToggle.addEventListener('click',()=>{areaRevision++;setAreaExpanded(areaLinks.hidden)});
priceFilter.addEventListener('change',apply);
function resetFilters(){
 document.querySelectorAll('.fb').forEach(button=>button.setAttribute('aria-pressed',button.dataset.cat?'true':'false'));
 Object.keys(st.cat).forEach(key=>st.cat[key]=true);Object.keys(st.x).forEach(key=>st.x[key]=false);st.sw.clear();
 priceFilter.value='all';apply();
}
document.getElementById('reset-filters').addEventListener('click',resetFilters);
setAreaExpanded(false);resetFilters();
const initialRevision=filterRevision,initialAreaRevision=areaRevision;
window.addEventListener('pageshow',event=>{
 // Preserve filters selected during a slow initial visit; reset on history return.
 if(!event.persisted&&filterRevision!==initialRevision)return;
 resetFilters();
 if(event.persisted||areaRevision===initialAreaRevision)setAreaExpanded(false);
 // Browser form restoration may follow pageshow. Keep any newer user choice.
 const revision=filterRevision;
 setTimeout(()=>{if(filterRevision===revision)resetFilters()},0);
});
