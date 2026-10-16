'use strict';
const $ = id => document.getElementById(id);
let data = null, group = '', page = 0, filtered = [];
let archiveKey = null, imageObserver = null, imageController = new AbortController(), mediaGeneration = 0;
const objectURLs = new Set();
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
  const decoded = JSON.parse(new TextDecoder().decode(plain));
  archiveKey = key;
  return decoded;
}

function clearImages() {
  mediaGeneration++; imageObserver?.disconnect(); imageController.abort(); imageController=new AbortController();
  objectURLs.forEach(url=>URL.revokeObjectURL(url)); objectURLs.clear();
}

function photoView(asset) {
  const figure=node('figure','photo-view');
  figure.dataset.mime=asset.mime;
  const status=node('figcaption','photo-status','Загружаем фотографию…');figure.append(status);
  const generation=mediaGeneration, signal=imageController.signal, key=archiveKey;
  const load=async()=>{
    try {
      if(!/^media\/[a-f0-9]{64}-[a-f0-9]{16}\.bin$/.test(asset.path))throw new Error('Invalid asset');
      const response=await fetch(asset.path,{cache:'no-store',signal});if(!response.ok)throw new Error('Image unavailable');
      const bytes=new Uint8Array(await response.arrayBuffer());
      const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes.slice(0,12)},key,bytes.slice(12));
      if(generation!==mediaGeneration || signal.aborted)return;
      const url=URL.createObjectURL(new Blob([plain],{type:asset.mime}));objectURLs.add(url);
      const link=node('a');link.href=url;link.target='_blank';link.rel='noopener';
      if(asset.mime.startsWith('image/')) {
        link.setAttribute('aria-label','Открыть изображение в полном размере');
        const image=node('img');image.alt='Изображение из сообщения';image.src=url;image.decoding='async';
        link.append(image);figure.replaceChildren(link,node('figcaption','photo-status','Открыть в полном размере ↗'));
      } else if(asset.mime==='video/webm') {
        const video=node('video');video.controls=true;video.loop=true;video.muted=true;video.playsInline=true;video.src=url;
        figure.replaceChildren(video,node('figcaption','photo-status','Анимированный стикер'));
      } else {
        link.download='sticker.tgs';link.textContent='Скачать анимированный стикер ↓';link.className='sticker-download';
        figure.replaceChildren(link);
      }
    } catch(error) {
      if(generation===mediaGeneration && error.name!=='AbortError')status.textContent='Не удалось загрузить фото. Обновите страницу и попробуйте снова.';
    }
  };
  figure.loadPhoto=load; imageObserver.observe(figure);return figure;
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
    initialize();
  } catch(error) { $('error').textContent=error.message; }
  finally { $('unlock').disabled=false; $('unlock').textContent='Открыть архив ↗'; }
});

function initialize() {
  const ordinary=data.messages.filter(m=>!m.service);
  const dates=data.messages.map(m=>m.date).filter(Number.isFinite);
  $('updated').textContent=`Снимок базы: ${timeFormat.format(new Date(data.generatedAt))} · московское время`;
  group=data.groups[0]?.id||''; drawGroups(); drawCourse();
}

function drawCourse() {
  const course=data.courseAnalysis;
  if(!course){$('course').hidden=true;return;}
  $('course').hidden=false; $('course-title').textContent=course.title;
  const selected=data.groups.find(g=>g.id===group); const selectedTitle=selected?.title||'';
  $('course-title').textContent=selectedTitle || 'Программа группы';
  $('course-method').textContent=`${course.teacher}. ${course.method}`;
  const c=course.coverage; $('course-coverage').textContent=`Даты занятий: ${c.firstTeacherMessage} — ${c.lastTeacherMessage}`;
  const box=$('course-subjects'); box.replaceChildren();
  course.subjects.forEach(subject=>{
    const modules=subject.modules.filter(mod=>mod.groups?.includes(selectedTitle));
    if(!modules.length)return;
    const article=node('article','course-subject');
    article.append(node('div','course-subject-title',subject.title),node('p','course-outcome',subject.outcome));
    const timeline=node('div','course-timeline'); modules.forEach(mod=>{
      const item=node('div','course-module'); item.append(node('time','course-date',mod.dates),node('h3','',mod.title));
      const list=node('ul'); mod.topics.forEach(t=>list.append(node('li','',t))); item.append(list); timeline.append(item);
      if(mod.practice)item.append(node('p','course-detail',`Практика: ${mod.practice}`));
      if(mod.evidence)item.append(node('p','course-evidence',`Основание в переписке: ${mod.evidence}`));
    }); article.append(timeline); box.append(article);
    if(subject.visuals?.length){const details=document.createElement('details');details.className='visual-analysis';details.open=true;details.append(node('summary','','Что подтверждают скриншоты'));const list=node('ul');subject.visuals.forEach(v=>list.append(node('li','',v)));details.append(list);article.append(details);}
  });
  $('assessment-items').replaceChildren(); course.assessment.forEach(item=>$('assessment-items').append(node('span','assessment-item',item)));
}

function drawGroups() {
  $('group-tabs').replaceChildren();
  data.groups.forEach(g=>{
    const button=node('button','group-tab'+(group===g.id?' active':''),g.title);
    button.setAttribute('aria-pressed',String(group===g.id));
    button.onclick=()=>{group=g.id;drawGroups();drawCourse();}; $('group-tabs').append(button);
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
  clearImages();
  imageObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{
    if(entry.isIntersecting){imageObserver.unobserve(entry.target);entry.target.loadPhoto();}
  }),{rootMargin:'600px'});
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
    if(m.images?.length)m.images.forEach(asset=>card.append(photoView(asset)));
    if(m.media.length){const tags=node('div','media-tags');m.media.forEach(t=>tags.append(node('span','tag',t+(m.images?.length?'':' · метаданные'))));card.append(tags);}
    $('messages').append(card);
  });
  $('page-number').textContent=`${page+1} / ${pages}`;$('previous').disabled=page===0;$('next').disabled=page===pages-1;
}

$('lock').onclick=()=>{clearImages();archiveKey=null;data=null;filtered=[];$('group-tabs').replaceChildren();$('course-subjects').replaceChildren();$('archive').hidden=true;$('gate').hidden=false;$('lock').hidden=true;$('password').focus();};
