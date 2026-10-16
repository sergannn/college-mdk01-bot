'use strict';
const $ = id => document.getElementById(id);
let data = null, group = '', page = 0, filtered = [];
const PAGE_SIZE = 40;
const nf = new Intl.NumberFormat('ru-RU');
const dateFormat = new Intl.DateTimeFormat('ru-RU', {day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Moscow'});
const timeFormat = new Intl.DateTimeFormat('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});
const dayFormat = new Intl.DateTimeFormat('sv-SE', {year:'numeric',month:'2-digit',day:'2-digit',timeZone:'Europe/Moscow'});
const dateKey = seconds => dayFormat.format(new Date(seconds * 1000));
const b64 = text => Uint8Array.from(atob(text), c => c.charCodeAt(0));
const node = (tag, cls, text) => { const element=document.createElement(tag); if(cls)element.className=cls; if(text!==undefined)element.textContent=text; return element; };

async function decrypt(envelope, password) {
  if(envelope.version!==1 || envelope.algorithm!=='AES-256-GCM' || envelope.kdf!=='PBKDF2-SHA256' || envelope.iterations!==310000) throw new Error('Unsupported archive');
  const material = await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  const key = await crypto.subtle.deriveKey({name:'PBKDF2',salt:b64(envelope.salt),iterations:envelope.iterations,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['decrypt']);
  const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(envelope.iv)},key,b64(envelope.ciphertext));
  return JSON.parse(new TextDecoder().decode(plain));
}

$('unlock-form').addEventListener('submit', async event => {
  event.preventDefault(); $('error').textContent=''; $('unlock').disabled=true; $('unlock').textContent='Открываем…';
  try {
    let envelope;
    try { const response=await fetch('archive.enc.json',{cache:'no-store'}); if(!response.ok)throw new Error(); envelope=await response.json(); }
    catch { throw new Error('Не удалось загрузить архив. Проверьте интернет и попробуйте ещё раз.'); }
    try { data=await decrypt(envelope,$('password').value); }
    catch { throw new Error('Не удалось открыть архив. Проверьте пароль и целостность файла.'); }
    $('password').value=''; $('gate').hidden=true; $('archive').hidden=false; $('lock').hidden=false;
    initialize(); $('search').focus();
  } catch(error) { $('error').textContent=error.message; }
  finally { $('unlock').disabled=false; $('unlock').textContent='Открыть архив ↗'; }
});

function initialize() {
  const ordinary=data.messages.filter(m=>!m.service);
  $('total').textContent=nf.format(ordinary.length);
  $('people').textContent=nf.format(new Set(ordinary.map(m=>m.authorKey)).size);
  $('groups-count').textContent=data.groups.length;
  $('media-count').textContent=nf.format(ordinary.filter(m=>m.media.length).length);
  const dates=data.messages.map(m=>m.date).filter(Number.isFinite);
  $('period').textContent=dates.length ? `${dateFormat.format(new Date(Math.min(...dates)*1000))} — ${dateFormat.format(new Date(Math.max(...dates)*1000))}` : 'Нет сообщений';
  $('updated').textContent=`Снимок базы: ${timeFormat.format(new Date(data.generatedAt))} · московское время`;
  const authors=new Map(); ordinary.forEach(m=>authors.set(m.authorKey,m.author));
  $('author').replaceChildren(node('option','','Все авторы')); $('author').firstChild.value='';
  [...authors].sort((a,b)=>a[1].localeCompare(b[1],'ru')).forEach(([id,name])=>{const option=node('option','',name);option.value=id;$('author').append(option);});
  group=''; page=0; drawGroups(); drawChart(); render();
}

function drawGroups() {
  $('group-tabs').replaceChildren();
  [{id:'',title:'Все группы'},...data.groups].forEach(g=>{
    const count=data.messages.filter(m=>!m.service && (!g.id || m.group===g.id)).length;
    const button=node('button','group-tab'+(group===g.id?' active':''),g.title);
    button.setAttribute('aria-pressed',String(group===g.id)); button.append(node('span','',`${nf.format(count)} сообщений`));
    button.onclick=()=>{group=g.id;page=0;drawGroups();render();}; $('group-tabs').append(button);
  });
}

function drawChart() {
  const ordinary=data.messages.filter(m=>!m.service);
  if(!ordinary.length)return;
  const last=Math.max(...ordinary.map(m=>m.date));
  const lastKey=dateKey(last), lastUTC=Date.parse(lastKey+'T00:00:00Z');
  const counts=new Map(); ordinary.forEach(m=>{const key=dateKey(m.date);counts.set(key,(counts.get(key)||0)+1);});
  const bars=Array.from({length:30},(_,i)=>{const key=new Date(lastUTC-(29-i)*86400000).toISOString().slice(0,10);return {key,count:counts.get(key)||0};});
  const max=Math.max(...bars.map(b=>b.count),1); $('chart').replaceChildren();
  bars.forEach(b=>{const bar=node('div','bar');bar.style.height=`${Math.max(4,b.count/max*100)}%`;bar.title=`${b.key}: ${b.count} сообщений`;$('chart').append(bar);});
  $('activity-range').textContent=`${bars[0].key} — ${bars[29].key}`;
}

const serviceNames={invite_members:'Добавлены участники',join_group_by_link:'Участник вступил по ссылке',
  remove_members:'Удалён участник',edit_group_title:'Изменено название группы',edit_group_photo:'Изменено фото группы',
  pin_message:'Закреплено сообщение',migrate_to_supergroup:'Группа преобразована в супергруппу',
  migrate_from_group:'Создана супергруппа',create_group:'Создана группа'};

function render() {
  const query=$('search').value.trim().toLocaleLowerCase('ru');
  const author=$('author').value, from=$('from').value, to=$('to').value, kind=$('kind').value;
  filtered=data.messages.filter(m=>{
    const date=dateKey(m.date);
    return (!group||m.group===group)&&(!author||m.authorKey===author)&&(!from||date>=from)&&(!to||date<=to)
      &&($('service').checked||!m.service)&&(kind!=='media'||m.media.length>0)&&(kind!=='text'||Boolean(m.text))
      &&(!query||`${m.text} ${m.author}`.toLocaleLowerCase('ru').includes(query));
  }).sort((a,b)=>$('order').value==='desc'?b.date-a.date:a.date-b.date);
  const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE)); page=Math.min(page,pages-1);
  $('result-count').textContent=`Найдено: ${nf.format(filtered.length)}`;
  $('empty').hidden=Boolean(filtered.length); $('messages').replaceChildren();
  filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE).forEach(m=>{
    const card=node('article','message'+(m.service?' service-message':''));
    const head=node('div','message-head');head.append(node('span','avatar',m.author.split(/\s+/).filter(Boolean).slice(0,2).map(s=>s[0]).join('').toLocaleUpperCase('ru')));
    const authorBox=node('div');authorBox.append(node('div','author',m.author),node('div','message-meta',`${data.groups.find(g=>g.id===m.group)?.title||''} · ${m.source}${m.edited?' · изменено':''}`));
    const time=node('time','',timeFormat.format(new Date(m.date*1000)));time.dateTime=new Date(m.date*1000).toISOString();head.append(authorBox,time);card.append(head);
    const text=m.text || (m.service?(serviceNames[m.action]||'Служебное событие'):m.media.length?'':'Сообщение без текста');
    if(text)card.append(node('p','message-text',text));
    if(m.media.length){const tags=node('div','media-tags');m.media.forEach(t=>tags.append(node('span','tag',t+' · метаданные')));card.append(tags);}
    $('messages').append(card);
  });
  $('page-number').textContent=`${page+1} / ${pages}`;$('previous').disabled=page===0;$('next').disabled=page===pages-1;
}

['search','author','from','to','kind','service','order'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',()=>{if(data){page=0;render();}}));
$('reset').onclick=()=>{['search','author','from','to'].forEach(id=>$(id).value='');$('kind').value='all';$('service').checked=false;page=0;render();};
$('previous').onclick=()=>{page--;render();$('result-count').scrollIntoView({block:'start',behavior:'smooth'});};
$('next').onclick=()=>{page++;render();$('result-count').scrollIntoView({block:'start',behavior:'smooth'});};
$('lock').onclick=()=>{data=null;filtered=[];$('messages').replaceChildren();$('group-tabs').replaceChildren();$('author').replaceChildren();$('search').value='';$('archive').hidden=true;$('gate').hidden=false;$('lock').hidden=true;$('password').focus();};
$('download').onclick=()=>{
  const cell=value=>'"'+String(value??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';
  const rows=[['Дата (Москва)','Группа','Автор','Текст','Вложения','Источник'],...filtered.map(m=>[timeFormat.format(new Date(m.date*1000)),data.groups.find(g=>g.id===m.group)?.title,m.author,m.text,m.media.join(', '),m.source])];
  const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const link=node('a');link.href=url;link.download='telegram-archive.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
