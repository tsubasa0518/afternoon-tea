const st={cat:{hotel:true,lux:true,cafe:true},x:{wd:false,we:false,pk:false},sw:new Set()};
function apply(){
 document.querySelectorAll('.card').forEach(c=>{let ok=st.cat[c.dataset.cat];
  if(st.x.wd&&c.dataset.wd!=="1")ok=false; if(st.x.we&&c.dataset.we!=="1")ok=false; if(st.x.pk&&c.dataset.pk!=="1")ok=false;
  if(st.sw.size&&!(c.dataset.sw||"").split(" ").some(t=>st.sw.has(t)))ok=false;
  c.classList.toggle('hide',!ok);});
 document.querySelectorAll('.cat').forEach(b=>{const on=st.cat[b.dataset.cat];b.classList.toggle('hide',!on);
  const vis=b.querySelectorAll('.card:not(.hide)').length;const cn=b.querySelector('.cnt');if(cn)cn.textContent=vis+'件';});
}
document.querySelectorAll('.fb').forEach(b=>b.addEventListener('click',()=>{const on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on);
 if(b.dataset.cat)st.cat[b.dataset.cat]=on; else if(b.dataset.sw){on?st.sw.add(b.dataset.sw):st.sw.delete(b.dataset.sw);} else st.x[b.dataset.x]=on; apply();}));
const tp=document.getElementById('top'),tt=document.querySelector('.totop');
if(tp&&tt&&'IntersectionObserver'in window){new IntersectionObserver(e=>tt.classList.toggle('show',!e[0].isIntersecting)).observe(tp);}else if(tt){tt.classList.add('show');}