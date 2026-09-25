const $ = id => document.getElementById(id);
const state = {documentId:null, pages:[], pageIndex:0, placements:[], selected:null, presets:{}, assetIds:{}, fileName:'document.pdf', pendingPreset:null, certificate:null};
const widths = {signature:160, initials:75, approval:145};
const presetNames = {signature:'Подпись', initials:'Инициалы', approval:'Lu et approuvé'};

function status(message, error=false){ $('status').textContent=message; $('status').classList.toggle('error',error); }
async function api(url, options={}){
  const response=await fetch(url,options);
  if(!response.ok){let message='Ошибка сервера';try{message=(await response.json()).error||message;}catch{}throw new Error(message);}
  return response;
}
function fail(error){status(error.message||String(error),true);}
function base(){return `/api/documents/${state.documentId}`;}
function currentSize(){return state.pages[state.pageIndex];}
function clamp(v,lo,hi){return Math.min(Math.max(v,lo),hi);}
function scaledRect(p){const s=currentSize();return {left:`${100*p.x/s.width}%`,top:`${100*p.y/s.height}%`,width:`${100*p.width/s.width}%`,height:`${100*p.height/s.height}%`};}
function displayScale(){return $('page').getBoundingClientRect().width/currentSize().width;}
function updateControls(){
  const ready=!!state.documentId;
  $('download').disabled=!ready;
  $('prev-page').disabled=!ready||state.pageIndex===0;
  $('next-page').disabled=!ready||state.pageIndex===state.pages.length-1;
  $('page-label').textContent=ready?`Страница ${state.pageIndex+1} из ${state.pages.length}`:'Нет документа';
  const selected=state.placements.find(p=>p.id===state.selected);
  $('delete-item').disabled=!selected;
  $('item-width').disabled=!selected||selected.kind==='text';
  $('item-width').value=selected&&selected.kind==='image'?Math.round(selected.width):'';
  if(selected&&selected.kind==='text')$('font-size').value=selected.font_size;
}
function renderItems(){
  const layer=$('items');layer.replaceChildren();
  if(!state.documentId)return;
  const s=currentSize();
  for(const p of state.placements.filter(p=>p.page_index===state.pageIndex)){
    const el=document.createElement('div');el.className=`placed ${p.kind}${p.id===state.selected?' selected':''}`;
    Object.assign(el.style,scaledRect(p));
    if(p.kind==='image'){
      const img=document.createElement('img');img.src=p.url;img.alt='';el.append(img);
      if(p.id===state.selected){const handle=document.createElement('div');handle.className='handle';handle.addEventListener('pointerdown',event=>startDrag(event,p,'resize'));el.append(handle);}
    }else{
      el.textContent=p.text;
      el.style.fontSize=`${p.font_size*displayScale()}px`;
      el.style.lineHeight=`${p.height*displayScale()}px`;
    }
    el.addEventListener('pointerdown',event=>startDrag(event,p,'move'));
    layer.append(el);
  }
  updateControls();
}
async function showPage(){
  const s=currentSize();
  $('page').style.aspectRatio=`${s.width}/${s.height}`;
  $('page-image').src=`${base()}/pages/${state.pageIndex+1}/preview`;
  $('page').hidden=false;$('empty-state').hidden=true;
  renderItems();
}
async function openDocument(file){
  if(!file)return;
  status('Загружаю PDF…');
  try{
    const form=new FormData();form.append('file',file);
    const result=await (await api('/api/documents',{method:'POST',body:form})).json();
    state.documentId=result.id;state.pages=result.pages;state.pageIndex=0;state.placements=[];state.selected=null;state.assetIds={};state.fileName=file.name;
    showPage();status(`${file.name} открыт. Страниц: ${result.pages.length}.`);
  }catch(error){fail(error);}
}
function savePreset(key, data){
  state.presets[key]=data;
  try{localStorage.setItem(`pdf-editor-preset-${key}`,JSON.stringify(data));}
  catch{status('Изображение доступно до закрытия вкладки: в браузере не хватило места для сохранения.');}
}
async function uploadPreset(key){
  const preset=state.presets[key];
  if(!preset)throw new Error('Сначала выберите изображение.');
  if(state.assetIds[key])return state.assetIds[key];
  const blob=await (await fetch(preset.dataUrl)).blob();
  const form=new FormData();form.append('file',blob,preset.name||`${key}.png`);
  const asset=await (await api(`${base()}/assets`,{method:'POST',body:form})).json();
  state.assetIds[key]=asset.id;
  return asset.id;
}
async function addPreset(key){
  if(!state.documentId){status('Сначала откройте PDF.',true);return;}
  if(!state.presets[key]){state.pendingPreset=key;$('preset-file').click();return;}
  try{
    const assetId=await uploadPreset(key);
    const preset=state.presets[key],s=currentSize();
    const width=Math.min(widths[key],s.width*.35),height=width*preset.height/preset.width;
    const p={id:crypto.randomUUID(),kind:'image',page_index:state.pageIndex,x:(s.width-width)/2,y:(s.height-height)/2,width,height,asset_id:assetId,url:preset.dataUrl,aspect:preset.height/preset.width};
    state.placements.push(p);state.selected=p.id;renderItems();status(`${presetNames[key]} добавлены на страницу.`);
  }catch(error){fail(error);}
}
function addText(){
  if(!state.documentId){status('Сначала откройте PDF.',true);return;}
  const value=$('text-input').value.trim(),font=Number($('font-size').value);
  if(!value){status('Введите текст.',true);return;}
  if(!Number.isFinite(font)||font<6||font>96){status('Размер шрифта: от 6 до 96 пт.',true);return;}
  const s=currentSize(),width=Math.min(s.width,Math.max(font*2,value.length*font*.55)),height=font*1.35;
  const p={id:crypto.randomUUID(),kind:'text',page_index:state.pageIndex,x:(s.width-width)/2,y:(s.height-height)/2,width,height,text:value,font_size:font};
  state.placements.push(p);state.selected=p.id;renderItems();status('Текст добавлен.');
}
function startDrag(event,p,mode){
  event.preventDefault();event.stopPropagation();state.selected=p.id;renderItems();
  const target=$('page'),rect=target.getBoundingClientRect(),scale=rect.width/currentSize().width;
  const startX=event.clientX,startY=event.clientY,origin={x:p.x,y:p.y,width:p.width,height:p.height};
  function move(e){
    const dx=(e.clientX-startX)/scale,dy=(e.clientY-startY)/scale,s=currentSize();
    if(mode==='move'){
      p.x=clamp(origin.x+dx,0,Math.max(0,s.width-p.width));
      p.y=clamp(origin.y+dy,0,Math.max(0,s.height-p.height));
    }else{
      const requested=Math.max((origin.width+dx+((origin.height+dy)/p.aspect))/2,12);
      p.width=clamp(requested,1,Math.min(s.width-p.x,(s.height-p.y)/p.aspect));
      p.height=p.width*p.aspect;
    }
    renderItems();
  }
  function stop(){window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);}
  window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop,{once:true});
}
async function downloadPdf(){
  if(!state.documentId)return;
  const signing=$('sign-enabled').checked,certificate=state.certificate||$('certificate-file').files[0];
  if(signing&&!certificate){status('Выберите сертификат .p12 / .pfx.',true);return;}
  if(signing&&!$('certificate-password').value){status('Введите пароль сертификата.',true);return;}
  status('Создаю PDF…');$('download').disabled=true;
  try{
    const form=new FormData();
    form.append('placements',JSON.stringify(state.placements.map(({kind,page_index,x,y,width,height,text,font_size,asset_id})=>({kind,page_index,x,y,width,height,text,font_size,asset_id}))));
    if(signing){form.append('certificate',certificate,certificate.name);form.append('password',$('certificate-password').value);}
    const response=await api(`${base()}/export`,{method:'POST',body:form});
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=state.fileName.replace(/\.pdf$/i,'')+'-signed.pdf';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    status('Готово. Новый PDF скачан.');
  }catch(error){fail(error);}finally{updateControls();}
}
async function createCertificate(event){
  event.preventDefault();
  try{
    const response=await api('/api/certificates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('cert-name').value,email:$('cert-email').value,password:$('cert-password').value})});
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
    const file=new File([blob],'personal-signing-certificate.p12',{type:'application/x-pkcs12'});
    state.certificate=file;$('sign-enabled').checked=true;$('certificate-password').value=$('cert-password').value;
    link.href=url;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
    $('certificate-dialog').close();status('Сертификат создан и скачан.');
  }catch(error){fail(error);}
}
function initialize(){
  for(const key of Object.keys(widths)){try{state.presets[key]=JSON.parse(localStorage.getItem(`pdf-editor-preset-${key}`)||'null');}catch{}}
  $('pdf-file').addEventListener('change',e=>{openDocument(e.target.files[0]);e.target.value='';});
  document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>addPreset(button.dataset.preset)));
  $('preset-file').addEventListener('change',e=>{
    const file=e.target.files[0],key=state.pendingPreset;if(!file||!key)return;
    if(!['image/png','image/jpeg'].includes(file.type)){status('Нужен PNG или JPG.',true);return;}
    const reader=new FileReader();reader.onload=()=>{
      const img=new Image();img.onload=()=>{savePreset(key,{dataUrl:reader.result,name:file.name,width:img.naturalWidth,height:img.naturalHeight});delete state.assetIds[key];addPreset(key);};img.src=reader.result;
    };reader.readAsDataURL(file);e.target.value='';
  });
  $('replace-preset').addEventListener('click',()=>{const key=prompt('Какой пресет заменить? signature / initials / approval','signature');if(key&&widths[key]){state.pendingPreset=key;$('preset-file').click();}});
  $('add-text').addEventListener('click',addText);
  $('text-input').addEventListener('keydown',e=>{if(e.key==='Enter')addText();});
  $('font-size').addEventListener('change',()=>{const p=state.placements.find(p=>p.id===state.selected);if(!p||p.kind!=='text')return;const size=Number($('font-size').value);if(size<6||size>96)return;const s=currentSize();p.font_size=size;p.width=Math.min(s.width,Math.max(size*2,p.text.length*size*.55));p.height=size*1.35;p.x=clamp(p.x,0,s.width-p.width);p.y=clamp(p.y,0,s.height-p.height);renderItems();});
  $('item-width').addEventListener('change',()=>{const p=state.placements.find(p=>p.id===state.selected);if(!p||p.kind!=='image')return;const requested=Number($('item-width').value),s=currentSize();if(!Number.isFinite(requested)||requested<=0)return;p.width=clamp(requested,1,Math.min(s.width-p.x,(s.height-p.y)/p.aspect));p.height=p.width*p.aspect;renderItems();});
  $('delete-item').addEventListener('click',()=>{state.placements=state.placements.filter(p=>p.id!==state.selected);state.selected=null;renderItems();});
  $('clear-page').addEventListener('click',()=>{if(!state.documentId)return;state.placements=state.placements.filter(p=>p.page_index!==state.pageIndex);state.selected=null;renderItems();});
  $('prev-page').addEventListener('click',()=>{if(state.pageIndex>0){state.pageIndex--;state.selected=null;showPage();}});
  $('next-page').addEventListener('click',()=>{if(state.pageIndex<state.pages.length-1){state.pageIndex++;state.selected=null;showPage();}});
  $('items').addEventListener('pointerdown',e=>{if(e.target===$('items')){state.selected=null;renderItems();}});
  $('download').addEventListener('click',downloadPdf);
  $('certificate-file').addEventListener('change',()=>{state.certificate=null;});
  $('create-certificate').addEventListener('click',()=>$('certificate-dialog').showModal());
  $('cancel-certificate').addEventListener('click',()=>$('certificate-dialog').close());
  $('certificate-form').addEventListener('submit',createCertificate);
  window.addEventListener('resize',renderItems);
  updateControls();
}
initialize();
