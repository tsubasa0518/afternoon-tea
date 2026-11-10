const st={cat:{hotel:true,lux:true,cafe:true,unknown:true},x:{wd:false,we:false},sw:new Set()};
document.querySelectorAll('.fb').forEach(button=>button.addEventListener('click',()=>{
 const on=button.getAttribute('aria-pressed')!=='true';button.setAttribute('aria-pressed',on);
 if(button.dataset.cat)st.cat[button.dataset.cat]=on;
 else if(button.dataset.sw){on?st.sw.add(button.dataset.sw):st.sw.delete(button.dataset.sw)}
 else if(button.dataset.x)st.x[button.dataset.x]=on;
 apply();
}));
const tp=document.getElementById('top'),tt=document.querySelector('.totop');
if(tp&&tt&&'IntersectionObserver'in window){new IntersectionObserver(e=>tt.classList.toggle('show',!e[0].isIntersecting)).observe(tp)}else if(tt){tt.classList.add('show')}
