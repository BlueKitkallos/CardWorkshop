'use strict';
const $ = s => document.querySelector(s);
const el = (tag, attrs={}, text) => {const e=document.createElement(tag); for(const [k,v] of Object.entries(attrs)){if(k==='class')e.className=v;else e.setAttribute(k,v);} if(text!==undefined)e.textContent=text;return e;};
let token, project, catalog=[], byRef=new Map(), byName=new Map(), tab='packs', selected=1, selectedCard, dirty=false, saveTimer, busy=false;
const rarities=['ultra','super','rare','common'];
const sections=['main','extra','side'];
const langs={e:'English',f:'French',g:'German',i:'Italian',s:'Spanish',j:'Japanese',k:'Korean'};
const storageKey='wc-community-editor-recovery-v1';
let cpuMetadata,cpuLoading,returnToCpu,baseBanlists,baseBanlistsLoading,openingReady=false,deckRule;
let tabSelections={},fieldId=0,undoStack=[],redoStack=[],lastState,savedState,toastTimer,addSection='main',addRarity='common';
const sectionViews=new Map(),tabViews=new Map(),displayNames=new Map(),byPassword=new Map();
const baseFields=['name','deck','deck_name','portrait','key_card','rating','talk'];
let baseCache={project:null,items:new Map()};
function baseCpu(chara){return cpuMetadata?.base.find(b=>b.chara===chara);}
function selectedBase(){return typeof selected==='string'&&selected.startsWith('base:')?Number(selected.slice(5)):null;}
function baseItem(chara){
 const b=baseCpu(chara);if(!b)return;
 if(baseCache.project!==project)baseCache={project,items:new Map()};
 if(!baseCache.items.has(chara)){const o=structuredClone(project.base_cpus[chara]||{});baseCache.items.set(chara,{...structuredClone(Object.fromEntries(baseFields.map(f=>[f,b[f]]))),...o,talk:b.talk.map((line,i)=>o.talk?.[i]??line)});}
 return baseCache.items.get(chara);
}
function syncBase(){
 if(baseCache.project!==project)return;
 for(const [chara,item] of baseCache.items){const b=baseCpu(chara),prev=project.base_cpus[chara]||{},o={};for(const f of [...Object.keys(prev).filter(k=>baseFields.includes(k)),...baseFields.filter(k=>!(k in prev))])if(f==='talk'){const lines=Object.fromEntries(item.talk.map((line,i)=>[i,line]).filter(([i,line])=>line!==b.talk[i]));if(Object.keys(lines).length)o.talk=lines;}else if(JSON.stringify(item[f])!==JSON.stringify(b[f]))o[f]=structuredClone(item[f]);if(Object.keys(o).length)project.base_cpus[chara]=o;else delete project.base_cpus[chara];}
}
const rosters={duel:'CPU Duel',turbo:'CPU Turbo Duel',tag:'CPU Tag Duel','tag-turbo':'CPU Tag Turbo Duel'};
function roster(o){return o.tag?(o.turbo?'tag-turbo':'tag'):o.turbo?'turbo':'duel';}
function cpuName(chara){const o=project.opponents.find(o=>o.chara===chara);if(o)return o.name;const b=baseCpu(chara);return b?project.base_cpus[chara]?.name??b.name:`CPU ${chara}`;}
function addCpu(kind){
 if(project.opponents.length>=196){toast('You can add up to 196 CPUs.');return;}
 let chara=465;while(project.opponents.some((o,i)=>(o.chara??465+i)===chara))chara++;
 const cpu={name:'New CPU',chara,deck:project.decks.find(d=>d.main.length===40)?.file||project.decks[0].file,template_deck:113,portrait:300,key_card:'id:4007',turbo:kind.endsWith('turbo')};
 if(kind.startsWith('tag'))Object.assign(cpu,{tag:true,partner:cpuMetadata?.base.find(b=>b.list===kind)?.chara,team_name:'New team'});
 const deck=structuredClone(project.decks.find(d=>d.file===cpu.deck));deck.file='user_'+crypto.randomUUID()+'.ydc';deck.name='New CPU deck';project.decks.push(deck);cpu.deck=deck.file;
 project.opponents.push(cpu);selected=project.opponents.length-1;$('#listSearch').value='';changed();list();editor();$('#editor').scrollTop=0;
}
function newCpuPicker(){
 const dialog=el('dialog',{class:'cpu-picker','aria-label':'New CPU'}),close=el('button',{},'Cancel');close.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
 dialog.append(el('h2',{},'Add a CPU to'));
 for(const [kind,label] of Object.entries(rosters)){const b=el('button',{},label);b.onclick=()=>{dialog.close();addCpu(kind);};dialog.append(b);}
 dialog.append(close);document.body.append(dialog);dialog.showModal();
}
function cpuExists(id){return typeof id==='string'?!!baseCpu(Number(id.slice(5))):!!project.opponents[id];}
function toast(s){clearTimeout(toastTimer);$('#toastText').textContent=s;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,9000);}
function status(s){$('#status').textContent=s;}
function resolve(ref){if(typeof ref!=='string')return;const explicit=ref.match(/\[id:(\d+)\]$/);return byRef.get(explicit?'id:'+explicit[1]:ref) || byName.get(ref.toLowerCase()) || byPassword.get(String(Number(ref)));}
function name(ref){const c=resolve(ref);return c ? displayNames.get(c.ref)||c.name : ref;}
function refs(text){return text.split('\n').map(s=>s.trim()).filter(Boolean).map(s=>resolve(s)?.ref || s);}
function syncActions(){
 for(const id of ['saveProject','export','validate'])$('#'+id).disabled=!project||busy;
 $('#openProject').disabled=!project||busy;
 $('#undo').disabled=busy||!undoStack.length;$('#redo').disabled=busy||!redoStack.length;
 $('#workspace').inert=busy;document.body.setAttribute('aria-busy',String(busy));
}
function persistRecovery(){
 clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{localStorage.setItem(storageKey,JSON.stringify(project));}catch{status('The browser has no room for a recovery copy. Save your project.');}},500);
}
function changed(){
 syncBase();
 const next=JSON.stringify(project);
 if(next!==lastState){if(lastState){undoStack.push(lastState);if(undoStack.length>40)undoStack.shift();}redoStack=[];lastState=next;}
 dirty=next!==savedState;$('#dirty').textContent=dirty?'Unsaved changes':'No unsaved changes';persistRecovery();syncActions();
 if(selectedCard)cardInfo(selectedCard);
}
function historyStep(redo=false){
 const source=redo?redoStack:undoStack,target=redo?undoStack:redoStack;if(!source.length||busy)return;
 target.push(lastState);lastState=source.pop();project=JSON.parse(lastState);dirty=lastState!==savedState;
 $('#dirty').textContent=dirty?'Unsaved changes':'No unsaved changes';$('#projectName').value=project.name;
 ensureSelection();list();editor();if(selectedCard)cardInfo(selectedCard);persistRecovery();syncActions();status(redo?'Redone':'Undone');
}
function ensureSelection(){
 if(tab==='packs'&&!project.packs.some(p=>p.id===selected))selected=project.packs[0]?.id;
 if(tab==='decks'&&!project.decks.some(d=>d.file===selected))selected=project.decks[0]?.file;
 if(tab==='banlists'&&!project.banlists.some(b=>b.id===selected))selected=project.banlists[0]?.id;
 if(tab==='opponents'&&!current())selected=cpuMetadata?.base.length?'base:'+cpuMetadata.base[0].chara:0;
 $('#add').disabled=tab==='banlists'&&project.banlists.length>=2||tab==='packs'&&project.packs.filter(p=>p.id>=97).length>=20;
}
function commitFocused(){const input=document.activeElement;if(input?.matches('input,textarea,select'))input.blur();}
function labelControl(text,control){const label=el('label',{for:control.id||(control.id='field-'+(++fieldId))},text);return label;}
function numberField(label,value,min,max,onchange){
 const wrap=field(label,value,onchange),input=wrap.querySelector('input');input.type='number';input.min=min;input.max=max;input.step=1;input.required=true;return wrap;
}
function issueLocation(message){
 const pack=message.match(/^Pack (\d+)/);if(pack)return {tab:'packs',id:Number(pack[1])};
 const deck=project.decks.find(d=>message.startsWith('Deck '+d.file));if(deck)return {tab:'decks',id:deck.file};
 const cpu=project.opponents.findIndex(o=>message.startsWith('CPU '+o.name+':'));if(cpu>=0)return {tab:'opponents',id:cpu};
 const base=cpuMetadata?.base.find(b=>message.startsWith(`CPU ${project.base_cpus[b.chara]?.name??b.name}:`));if(base)return {tab:'opponents',id:'base:'+base.chara};
 const list=project.banlists.find(b=>message.startsWith(b.name+':'));if(list)return {tab:'banlists',id:list.id};
 if(message.startsWith('Better pack opening:'))return {tab:'patches'};
}
function showIssues(issues){
 const root=$('#issueList');root.replaceChildren();
 if(!issues.length)root.append(el('p',{},'Ready to export'));
 else{
  root.append(el('p',{},`${issues.length} ${issues.length===1?'issue':'issues'} to fix before export`));const issueRows=el('ul');
  for(const text of issues){
   const location=issueLocation(text),deck=location?.tab==='decks'?project.decks.find(d=>d.file===location.id):null;
   const row=el('li',{},deck?text.replace('Deck '+deck.file,deckLabel(deck)):text);
   if(location){const fix=el('button',{},'Open');fix.onclick=()=>{$('#issues').close();setTab(location.tab);if(location.id!==undefined)selected=location.id;$('#listSearch').value='';list();editor();$('#editor').scrollTop=0;};row.append(fix);}issueRows.append(row);
  }root.append(issueRows);
 }
 if(!$('#issues').open)$('#issues').showModal();
}
async function api(path,data,raw=false){const r=await fetch(path,{method:'POST',headers:{'X-Editor-Token':token,'Content-Type':raw?'application/octet-stream':'application/json'},body:raw?data:JSON.stringify(data)});if(!r.ok){const d=await r.json();throw Error(d.error || r.statusText);}return r;}
function download(blob,filename){const u=URL.createObjectURL(blob);const a=el('a',{href:u,download:filename});a.click();setTimeout(()=>URL.revokeObjectURL(u),2000);}
function deckLabel(deck){
 if(deck.name&&deck.name!==deck.file)return deck.name;
 const template=cpuMetadata?.templates.find(t=>t.file===deck.file);
 return template?`${template.name} · ${template.deck_name}`:deck.file==='default_jf.ydc'?'Default deck':`Base game deck ${project.decks.indexOf(deck)+1}`;
}
function loadCpuMetadata(){
 if(cpuMetadata)return Promise.resolve(cpuMetadata);
 if(!cpuLoading)cpuLoading=fetch('/api/cpus').then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error);cpuMetadata=d;return d;}).finally(()=>cpuLoading=null);
 return cpuLoading;
}
function current(){return tab==='packs'?project.packs.find(p=>p.id===selected):tab==='decks'?project.decks.find(d=>d.file===selected):tab==='banlists'?project.banlists.find(b=>b.id===selected):selectedBase()!==null?baseItem(selectedBase()):project.opponents[selected];}
function list(){const root=$('#list');root.replaceChildren();const q=$('#listSearch').value.toLowerCase();let rows=[];
 if(tab==='packs')rows=project.packs.map(p=>({id:p.id,title:p.name.e,sub:p.id<97?`Base game · #${p.id}`:`Added · #${p.id}`,image:p.image || (p.id<97?`/api/image/pack/${p.id}`:null)}));
 if(tab==='decks')rows=project.decks.map(d=>({id:d.file,title:deckLabel(d),sub:`${d.main.length} main · ${d.extra.length} extra · ${d.side.length} side`}));
 if(tab==='banlists')rows=project.banlists.map(b=>({id:b.id,title:b.name,sub:b.id==='points'?`Points · ${b.cap} per deck`:'Classic'}));
 if(tab==='opponents')rows=Object.keys(rosters).flatMap(kind=>[
  ...(cpuMetadata?.base||[]).filter(b=>b.list===kind).map(b=>{const o=project.base_cpus[b.chara]||{};return {id:'base:'+b.chara,roster:kind,title:o.name??b.name,sub:[b.team,Object.keys(o).length?'Edited':'Base game'].filter(Boolean).join(' · '),image:`/api/image/portrait/${o.portrait??b.portrait}`};}),
  ...project.opponents.map((o,i)=>[o,i]).filter(([o])=>roster(o)===kind).map(([o,i])=>({id:i,roster:kind,title:o.name,sub:[o.tag&&o.team_name,'Added'].filter(Boolean).join(' · '),image:`/api/image/portrait/${o.portrait??300}`}))]);
 let heading;for(const row of rows.filter(r=>`${r.title} ${r.sub} ${r.id}`.toLowerCase().includes(q))){if(row.roster&&row.roster!==heading){heading=row.roster;root.append(el('h3',{class:'list-heading'},rosters[heading]));}const b=el('button',{class:'list-row'+(row.id===selected?' active':'')});if(row.image)b.append(el('img',{src:row.image,alt:'',loading:'lazy'}));const t=el('span',{},row.title);t.append(el('small',{},row.sub));b.append(t);b.onclick=()=>{selected=row.id;list();editor();};b.setAttribute('aria-current',String(row.id===selected));root.append(b);}if(!root.childElementCount)root.append(el('p',{class:'muted'},q?'No matches':tab==='opponents'?'Loading CPUs…':tab==='banlists'?'No lists added':'No entries'));}
function field(label,value,onchange,type='input'){const wrap=el('div');wrap.append(el('label',{},label));const input=el(type,{id:'field-'+(++fieldId)});wrap.firstChild.htmlFor=input.id;input.value=value;input.addEventListener('change',()=>{if(!input.checkValidity()){input.reportValidity();input.value=value;return;}onchange(input.value);});wrap.append(input);return wrap;}
function notice(text){return el('p',{class:'notice'},text);}
function deckText(rows){
 const grouped=new Map();for(const ref of rows){const key=resolve(ref)?.ref||ref;grouped.set(key,(grouped.get(key)||0)+1);}
 return [...grouped].map(([ref,count])=>`${count} × ${name(ref)}`).join('\n');
}
function deckRefs(text){
 const out=[];
 for(const line of text.split('\n').map(s=>s.trim()).filter(Boolean)){
  const match=line.match(/^(\d+)\s*[x×]\s+(.+)$/),count=match?Number(match[1]):1,ref=match?match[2]:line;
  if(count<1||count>3)throw Error('Use 1–3 copies per card');
  for(let i=0;i<count;i++)out.push(resolve(ref)?.ref||ref);
 }
 return out;
}
function deckError(item){
 const limits={main:60,extra:15,side:15},copies=new Map();
 for(const sec of sections){
  if(item[sec].length>limits[sec])return `The ${sec[0].toUpperCase()+sec.slice(1)} Deck can't hold more than ${limits[sec]} cards.`;
  for(const ref of item[sec]){
   const c=resolve(ref),key=c?.canonical_id||c?.id||ref;
   if(c&&(c.placement==='none'||sec!=='side'&&c.placement!==sec))return `${name(ref)} can't go in the ${sec[0].toUpperCase()+sec.slice(1)} Deck.`;
   copies.set(key,(copies.get(key)||0)+1);
   if(copies.get(key)>3)return 'A deck can hold at most 3 copies of a card.';
  }
 }
 return null;
}
function commitDeck(item,next){const error=deckError(next);if(error){toast(error);return false;}for(const sec of sections)item[sec]=next[sec];changed();editor();list();return true;}
function tile(ref,section,index){
 const c=resolve(ref),t=el('div',{class:'tile'+(c?' frame-'+(c.frame||'effect'):' draft-card'),draggable:'true',title:name(ref)});
 if(c)t.append(el('img',{src:`/api/image/card/${c.id}`,alt:name(ref),loading:'lazy'}));
 const inspect=el('button',{class:'tile-name'},c?.name||ref);inspect.onclick=e=>{e.stopPropagation();cardInfo(ref);};t.append(inspect);if(!c)t.append(el('small',{class:'danger'},'Draft'));
 if(tab==='decks'){
  const controls=el('div',{class:'copy-controls'}),item=current();
  const count=item[section].filter(n=>(resolve(n)?.ref||n)===(c?.ref||ref)).length;
  const minus=el('button',{'aria-label':`Decrease ${name(ref)}`},'−');
  minus.onclick=e=>{e.stopPropagation();const at=item[section].findIndex(n=>(resolve(n)?.ref||n)===(c?.ref||ref));item[section].splice(at,1);changed();editor();list();};
  const plus=el('button',{'aria-label':`Increase ${name(ref)}`},'+');
  plus.onclick=e=>{e.stopPropagation();const next=structuredClone(item);next[section].push(ref);commitDeck(item,next);};
  controls.append(minus,el('b',{},String(count)),plus);t.append(controls);
 }else{
  const remove=el('button',{'aria-label':`Remove ${name(ref)}`},'−');
  remove.onclick=e=>{e.stopPropagation();current().cards[section].splice(index,1);changed();editor();list();};t.append(remove);
 }
 dropzone(t,section,index);t.onclick=()=>cardInfo(ref);
 t.ondragstart=e=>{e.dataTransfer.setData('application/x-wc-card',JSON.stringify({ref,tab,selected,section,index}));e.dataTransfer.effectAllowed='move';};
 return t;
}
function dropzone(zone,section,beforeIndex=null){
 zone.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-wc-card')){e.preventDefault();e.stopPropagation();zone.classList.add('dropover');}};
 zone.ondragleave=()=>zone.classList.remove('dropover');
 zone.ondrop=e=>{
  e.preventDefault();e.stopPropagation();zone.classList.remove('dropover');
  try{
   const payload=JSON.parse(e.dataTransfer.getData('application/x-wc-card'));
   if(typeof payload.ref!=='string')return;
   const item=current(),candidate=tab==='decks'?structuredClone(item):item;const target=tab==='packs'?(item.cards[section] ||= []):candidate[section];
   const sameItem=payload.tab===tab&&payload.selected===selected&&payload.section;
   const source=sameItem?(tab==='packs'?item.cards[payload.section]:candidate[payload.section]):null;
   const moving=source&&source[payload.index]===payload.ref;
   if(tab==='packs'&&Object.entries(item.cards).some(([r,rows])=>rows.some((n,i)=>(resolve(n)?.ref||n)===(resolve(payload.ref)?.ref||payload.ref)&&!(moving&&r===payload.section&&i===payload.index)))){
    toast('This card is already in the pack. Drag its tile to change its rarity.');return;
   }
   let insertion=beforeIndex===null?target.length:beforeIndex;
   if(moving){source.splice(payload.index,1);if(source===target&&payload.index<insertion)insertion--;}
   target.splice(insertion,0,payload.ref);if(tab==='decks'){commitDeck(item,candidate);}else{changed();editor();list();}
  }catch{toast('Could not read the dragged card.');}
 };
}
function sectionNavigation(item,names){
 const nav=el('nav',{class:'section-navigation','aria-label':'Card sections'});
 for(const section of names){const rows=tab==='packs'?item.cards[section]||[]:item[section],button=el('button',{},`${section[0].toUpperCase()+section.slice(1)} ${rows.length}`);button.onclick=()=>document.querySelector(`[data-rarity="${section}"]`).scrollIntoView({block:'start',behavior:'instant'});nav.append(button);}return nav;
}
function addCardPicker(item,section){
 const deckMode=tab==='decks',dialog=el('dialog',{class:'cpu-picker','aria-label':'Add card'}),search=el('input',{placeholder:'Find a card…','aria-label':'Find card to add'}),grid=el('div',{class:'picker-grid'});
 const heading=el('h2',{},'Add card · '+section[0].toUpperCase()+section.slice(1)),feedback=el('p',{'role':'status',class:'muted'}),close=el('button',{},'Done');
 close.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.append(heading,search,feedback,grid,close);
 function draw(){
  grid.replaceChildren();const q=search.value.trim().toLowerCase();
  const rows=catalog.filter(c=>(!deckMode||c.placement!=='none'&&(section==='side'||c.placement===section))&&(!q||`${c.name} ${c.id} ${String(c.password).padStart(8,'0')}`.toLowerCase().includes(q))).sort((a,b)=>a.name.localeCompare(b.name)||a.id-b.id);
  for(const card of rows.slice(0,120)){
   const pick=el('button',{class:'picker-card'}),count=deckMode?sections.flatMap(s=>item[s]).filter(r=>(resolve(r)?.canonical_id||r)===card.canonical_id).length:0;
   const duplicate=!deckMode&&Object.values(item.cards).flat().some(r=>(resolve(r)?.ref||r)===card.ref);
   const full=deckMode&&item[section].length>=({main:60,extra:15,side:15}[section]);
   pick.disabled=duplicate||count>=3||full;
   pick.append(el('img',{src:`/api/image/card/${card.id}`,alt:'',loading:'lazy'}),el('span',{},card.name));
   if(card.id!==card.canonical_id)pick.append(el('small',{class:'muted'},'Alternate artwork'));
   if(duplicate||count||full)pick.append(el('small',{class:'muted'},duplicate?'Already in pack':full?'Section full':`${count} / 3 in deck`));
   pick.onclick=()=>{
    if(deckMode){const next=structuredClone(item);next[section].push(card.ref);if(!commitDeck(item,next))return;}
    else{(item.cards[section] ||= []).push(card.ref);changed();editor();list();}
    feedback.textContent='Added '+card.name;draw();
   };grid.append(pick);
  }
  if(!rows.length)grid.append(el('p',{class:'muted'},'No cards found'));
  if(rows.length>120)grid.append(el('p',{class:'muted'},'Search to narrow results'));
 }
 search.oninput=draw;draw();document.body.append(dialog);dialog.showModal();search.focus();
}
function cardSection(item,section){
 const rows=tab==='packs'?(item.cards[section]||[]):item[section];
 const box=el('div',{class:'rarity','data-rarity':section});
 const title=el('div',{class:'section-label'},`${section[0].toUpperCase()+section.slice(1)} · ${rows.length}${tab==='decks'?' / '+({main:60,extra:15,side:15}[section]):''}`),view=el('button',{'aria-label':`Toggle ${section} text list`}),viewKey=tab+':'+selected+':'+section;const actions=el('div',{class:'section-actions'}),add=el('button',{'aria-label':`Add card to ${section}`},'Add card');add.onclick=()=>addCardPicker(item,section);actions.append(add,view);title.append(actions);box.append(title);
 const text=el('textarea',{'aria-label':`${section} card list`,spellcheck:'false'});
 text.value=tab==='decks'?deckText(rows):rows.map(name).join('\n');text.placeholder=tab==='decks'?'3 × Card name':'One card per line';
 text.onchange=()=>{
  let value;try{value=tab==='decks'?deckRefs(text.value):refs(text.value);}catch(e){toast(e.message);text.value=deckText(rows);return;}
  if(tab==='packs'){item.cards[section]=value;changed();editor();list();}
  else{const next=structuredClone(item);next[section]=value;if(!commitDeck(item,next))text.value=deckText(item[section]);}
 };
 box.append(text);const tiles=el('div',{class:'tiles'}),seen=new Set();
 rows.forEach((ref,i)=>{const key=resolve(ref)?.ref||ref;if(tab==='decks'&&seen.has(key))return;seen.add(key);tiles.append(tile(ref,section,i));});
 box.append(tiles);function showView(){const textMode=sectionViews.get(viewKey)==='text';text.hidden=!textMode;tiles.hidden=textMode;view.textContent=textMode?'Images':'Text';view.setAttribute('aria-pressed',String(textMode));}view.onclick=()=>{sectionViews.set(viewKey,text.hidden?'text':'images');showView();};showView();if(!rows.length)tiles.append(el('span',{class:'muted'},'No cards'));dropzone(box,section);return box;
}
const talkTriggers=['Duel start','Draws','Summons','Attacks','Direct attack','Final attack','Activates a Spell','Activates a Trap','Ends turn','Small damage','Medium damage','Large damage','Wins','Loses','Draw result','Uses key card','Key card gone','Chain','Ahead on LP','Behind on LP','Idle','Tag Duel opening','Partner chains','Partner takes medium damage','Partner takes large damage','Tag team wins','Tag team loses','Tag team draws'];
function copyCpuDeck(item,sourceFile){
 const source=project.decks.find(d=>d.file===sourceFile);if(!source)return;
 const d=structuredClone(source);d.file='user_'+crypto.randomUUID()+'.ydc';d.name=item.name+' deck';
 project.decks.push(d);item.deck=d.file;changed();editor();list();
}
function cpuPicker(item,mode){
 const dialog=el('dialog',{class:'cpu-picker'}),search=el('input',{placeholder:mode==='portrait'?'Find a portrait…':'Find a CPU…','aria-label':'Search picker'}),grid=el('div',{class:'picker-grid'});
 const close=el('button',{},'Close');close.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
 dialog.append(el('h2',{},mode==='portrait'?'Portraits':'Base game CPUs'),search,grid,close);
 function draw(){
  grid.replaceChildren();const q=search.value.toLowerCase();
  const rows=mode==='portrait'?cpuMetadata.portraits:cpuMetadata.templates;
  for(const entry of rows.filter(x=>(x.name+' '+(x.deck_name||'')).toLowerCase().includes(q))){
   const portrait=mode==='portrait'?entry.id:entry.portrait;
   const b=el('button',{class:'picker-card'});b.append(el('img',{src:`/api/image/portrait/${portrait}`,alt:'',loading:'lazy'}),el('span',{},entry.name));
   if(mode!=='portrait')b.append(el('small',{class:'muted'},entry.deck_name));
   b.onclick=()=>{
    if(mode==='portrait'){item.portrait=entry.id;changed();editor();}
    else{
     item.template_deck=entry.slot;item.portrait=entry.portrait;item.key_card=entry.key_card;item.rating=entry.rating;
     item.deck_name=entry.deck_name;delete item.talk;
     if(!item.name||item.name==='New CPU')item.name=entry.name;
     copyCpuDeck(item,entry.file);
    }
    dialog.close();
   };grid.append(b);
  }
 }
 search.oninput=draw;draw();document.body.append(dialog);dialog.showModal();search.focus();
}
function setKeyCard(item,ref){
 const card=resolve(ref);if(!card){toast('The key card must be a card from the game, not a draft.');return false;}
 item.key_card=card.ref;changed();editor();return true;
}
function keyCardPicker(item){
 const dialog=el('dialog',{class:'cpu-picker','aria-label':'Choose key card'}),search=el('input',{placeholder:'Find a card…','aria-label':'Find key card'}),grid=el('div',{class:'picker-grid'});
 const scope=el('select',{'aria-label':'Key card source'});scope.append(el('option',{value:'deck'},'Deck'),el('option',{value:'all'},'All cards'));
 const deck=project.decks.find(d=>d.file===item.deck),refs=new Set(deck?sections.flatMap(s=>deck[s]).map(r=>resolve(r)?.ref||r):[]);
 if(!refs.size)scope.value='all';
 const close=el('button',{},'Cancel');close.onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
 dialog.append(el('h2',{},'Choose key card'),scope,search,grid,close);
 function draw(){
  grid.replaceChildren();const q=search.value.trim().toLowerCase();
  const rows=catalog.filter(c=>(scope.value==='all'||refs.has(c.ref))&&(!q||`${c.name} ${c.id} ${c.password}`.toLowerCase().includes(q)));
  for(const card of rows.slice(0,200)){
   const pick=el('button',{class:'picker-card','aria-pressed':String(resolve(item.key_card||'')?.ref===card.ref)});
   pick.append(el('img',{src:`/api/image/card/${card.id}`,alt:'',loading:'lazy'}),el('span',{},card.name));
   pick.onclick=()=>{if(setKeyCard(item,card.ref))dialog.close();};grid.append(pick);
  }
  if(!rows.length)grid.append(el('p',{class:'muted'},'No cards found'));
  if(rows.length>200)grid.append(el('p',{class:'muted'},'Search to narrow results'));
 }
 search.oninput=draw;scope.onchange=draw;draw();document.body.append(dialog);dialog.showModal();search.focus();
}
function keyCardControl(item,deck){
 const box=el('section',{class:'key-card-control','aria-label':'Key card'}),card=resolve(item.key_card||'id:4007');
 const preview=el('button',{class:'key-card-preview','aria-label':'Inspect key card'});
 if(card)preview.append(el('img',{src:`/api/image/card/${card.id}`,alt:card.name}));
 preview.onclick=()=>cardInfo(item.key_card||'id:4007');
 const info=el('div');info.append(el('label',{},'Key card'),el('strong',{},card?card.name:item.key_card));
 const change=el('button',{},'Change key card');change.onclick=()=>keyCardPicker(item);info.append(change);
 if(deck&&card&&!sections.some(s=>deck[s].some(r=>resolve(r)?.canonical_id===card.canonical_id)))info.append(el('small',{class:'muted'},'Not in this deck'));
 box.append(preview,info);
 box.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-wc-card')){e.preventDefault();box.classList.add('dropover');}};
 box.ondragleave=()=>box.classList.remove('dropover');
 box.ondrop=e=>{e.preventDefault();box.classList.remove('dropover');try{setKeyCard(item,JSON.parse(e.dataTransfer.getData('application/x-wc-card')).ref);}catch{toast('Could not read the dragged card.');}};
 return box;
}
function renderCpu(root,item){
 if(!cpuMetadata){
  root.append(el('h2',{},'Free Duel CPU'));
  root.append(el('p',{class:'muted'},'Loading CPUs…'));loadCpuMetadata().then(()=>{if(tab==='opponents')editor();}).catch(e=>{toast(e.message);const retry=el('button',{},'Retry');retry.onclick=editor;root.append(retry);});
  return;
 }
 const chara=selectedBase(),base=chara===null?null:baseCpu(chara);
 const head=el('div',{class:'editor-head cpu-head'}),portrait=el('button',{class:'portrait-button','aria-label':'Choose portrait'});
 portrait.append(el('img',{src:`/api/image/portrait/${item.portrait??300}`,alt:item.name}));portrait.onclick=()=>cpuPicker(item,'portrait');
 const actions=el('div');actions.append(el('span',{class:'eyebrow'},(base?['BASE GAME',base.team]:['ADDED',item.tag&&item.team_name]).filter(Boolean).join(' · ')),el('h2',{},item.name));
 if(!base){const choose=el('button',{},'Copy base game CPU');choose.onclick=()=>cpuPicker(item,'template');actions.append(choose);}
 const choosePortrait=el('button',{},'Choose portrait');choosePortrait.onclick=()=>cpuPicker(item,'portrait');actions.append(choosePortrait);head.append(portrait,actions);root.append(head);
 root.append(field('Name',item.name,v=>{item.name=v;changed();list();}),field('Deck name in game',item.deck_name||'',v=>{item.deck_name=v;changed();}));
 const deck=el('select',{'aria-label':'CPU deck'});project.decks.forEach(d=>deck.append(el('option',{value:d.file},deckLabel(d))));deck.value=item.deck;deck.onchange=()=>{item.deck=deck.value;changed();editor();};const deckSearch=el('input',{placeholder:'Find a deck…','aria-label':'Find CPU deck'});deckSearch.oninput=()=>{const q=deckSearch.value.toLowerCase();for(const option of deck.options)option.hidden=!option.textContent.toLowerCase().includes(q);};root.append(labelControl('Deck',deck),deckSearch,deck);
 const deckActions=el('div',{class:'row cpu-actions'}),edit=el('button',{},'Edit deck'),copy=el('button',{},'Copy deck');
 edit.onclick=()=>{const file=item.deck,from=selected;setTab('decks');returnToCpu=from;selected=file;list();editor();};
 copy.onclick=()=>copyCpuDeck(item,item.deck);deckActions.append(edit,copy);root.append(deckActions);
 const d=project.decks.find(d=>d.file===item.deck);
 if(d){root.append(el('p',{class:'muted'},`${d.main.length} Main · ${d.extra.length} Extra · ${d.side.length} Side`));const error=deckError(d)||(d.main.length<40?'The Main Deck needs at least 40 cards.':null);if(error)root.append(notice(error));}
 root.append(keyCardControl(item,d));
 const advanced=el('details',{class:'cpu-settings'});advanced.append(el('summary',{},'Dialogue & rating'));
 if(!base){
  const mode=el('select',{'aria-label':'CPU list'});for(const [kind,label] of Object.entries(rosters))mode.append(el('option',{value:kind},label));mode.value=roster(item);mode.onchange=()=>{item.turbo=mode.value.endsWith('turbo');if(mode.value.startsWith('tag')){item.tag=true;item.partner??=cpuMetadata.base.find(b=>b.list===mode.value)?.chara;item.team_name??='New team';}else{delete item.tag;delete item.partner;delete item.team_name;}changed();list();editor();};root.append(labelControl('List',mode),mode);
  if(item.tag){const partner=el('select',{'aria-label':'Tag partner'});for(const c of [...cpuMetadata.base.map(b=>b.chara),...project.opponents.map(o=>o.chara)].filter(c=>c!==item.chara))partner.append(el('option',{value:c},cpuName(c)));partner.value=item.partner;partner.onchange=()=>{item.partner=Number(partner.value);changed();};root.append(labelControl('Partner',partner),partner,field('Team name',item.team_name||'',v=>{item.team_name=v;changed();list();}));}
  const template=el('select',{'aria-label':'Base game template'});cpuMetadata.templates.forEach(t=>template.append(el('option',{value:t.slot},t.name+' · '+t.deck_name)));template.value=item.template_deck??113;template.onchange=()=>{item.template_deck=Number(template.value);changed();editor();$('#editor .cpu-settings').open=true;};advanced.append(labelControl('Copy dialogue from',template),template);
 }
 root.append(advanced);
 const meta=base||cpuMetadata.templates.find(t=>t.slot===(item.template_deck??113));
 advanced.append(numberField('Rating',item.rating??meta?.rating??1000,0,65535,v=>{const n=Number(v);if(!Number.isInteger(n)||n<0||n>65535){toast('Rating must be from 0 to 65535.');editor();return;}item.rating=n;changed();}));
 const talk=el('details',{class:'cpu-dialogue'});talk.append(el('summary',{},'Dialogue'));
 const reset=el('button',{},base?'Use base game dialogue':'Use template dialogue');reset.onclick=()=>{if(base)item.talk=structuredClone(base.talk);else delete item.talk;changed();editor();};talk.append(reset);
 const lines=item.talk||meta?.talk||[];
 for(let i=0;i<28;i++)talk.append(field(talkTriggers[i],lines[i]||'',v=>{if(!item.talk?.length)item.talk=Array.from({length:28},(_,j)=>lines[j]||'...');item.talk[i]=v;changed();},'textarea'));
 advanced.append(talk);
 if(base){const reset=el('button',{class:'danger'},'Reset to base game');reset.onclick=()=>{baseCache.items.delete(chara);delete project.base_cpus[chara];changed();list();editor();};root.append(reset);return;}
 const del=el('button',{class:'danger'},'Remove CPU');del.onclick=()=>{project.opponents.splice(selected,1);selected=0;changed();list();editor();};root.append(del);
}
function renderDeckRules(root,deck){
 if(!project.banlists.length)return;
 const select=el('select',{'aria-label':'Banlist'});select.append(el('option',{value:'none'},'None'));
 for(const b of project.banlists)select.append(el('option',{value:b.id},b.name));
 if(deckRule===undefined)deckRule=project.default_banlist==='base'?'none':project.default_banlist;
 select.value=project.banlists.some(b=>b.id===deckRule)?deckRule:'none';select.onchange=()=>{deckRule=select.value;editor();};root.append(labelControl('Banlist',select),select);
 const bl=project.banlists.find(b=>b.id===select.value);if(!bl)return;
 const values=new Map(Object.entries(bl.cards).map(([ref,n])=>[resolve(ref)?.canonical_id||resolve(ref)?.id||ref,n])),counts=new Map();
 for(const ref of [...deck.main,...deck.extra,...deck.side]){const c=resolve(ref),key=c?.canonical_id||c?.id||ref;counts.set(key,(counts.get(key)||0)+1);}
 if(bl.id==='points'){
  const total=[...counts].reduce((n,[key,count])=>n+(values.get(key)||0)*count,0);
  root.append(el('p',{class:total>bl.cap?'danger':'muted'},`${total} / ${bl.cap} points`));
 }else{
  for(const [key,count]of counts){const max=values.get(key)??3;if(count>max)root.append(el('p',{class:'danger'},`${name(typeof key==='number'?'id:'+key:key)}: ${count} / ${max}`));}
 }
}
function newBanlistPicker(){
 const dialog=el('dialog',{'aria-label':'New list'});dialog.append(el('h2',{},'New list'));
 for(const [id,label] of [['classic','Classic banlist'],['points','Points list']]){
  const button=el('button',{},label);button.disabled=project.banlists.some(b=>b.id===id);
  button.onclick=()=>{createBanlist(id);dialog.close();};dialog.append(button);
 }
 const cancel=el('button',{},'Cancel');cancel.onclick=()=>dialog.close();dialog.append(cancel);
 dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
}
async function copyPointsPreset(bl){
 try{
  busy=true;syncActions();status('Copying Retro-Genesys…');
  const response=await fetch('/api/points-preset'),preset=await response.json();if(!response.ok)throw Error(preset.error);
  bl.name=preset.name;bl.cap=preset.cap;bl.cards=preset.cards;changed();list();editor();
  toast(`Copied ${Object.keys(bl.cards).length} cards. Skipped ${preset.skipped.length} that aren't in the base game.`);
 }catch(e){toast(e.message);}finally{busy=false;syncActions();status('Ready');}
}
function createBanlist(type){
 if(project.banlists.some(b=>b.id===type)){selected=type;list();editor();return;}
 const b={id:type,name:type==='classic'?'Classic banlist':'Points list',cards:{}};if(type==='points')b.cap=100;
 project.banlists.push(b);selected=type;changed();list();editor();$('#add').disabled=project.banlists.length>=2;
}
function banValueControl(bl,ref){
 if(bl.id==='classic'){
  const select=el('select',{'aria-label':`Limit for ${name(ref)}`});['Forbidden','Limited','Semi-limited','Unlimited'].forEach((t,i)=>select.append(el('option',{value:i},t)));
  select.value=bl.cards[ref];select.onchange=()=>{bl.cards[ref]=Number(select.value);changed();};return select;
 }
 const number=el('input',{type:'number',min:'0',max:'99','aria-label':`Points for ${name(ref)}`});number.value=bl.cards[ref];
 number.onchange=()=>{const n=Number(number.value);if(!Number.isInteger(n)||n<0||n>99){number.value=bl.cards[ref];toast('A card can cost 0 to 99 points.');return;}bl.cards[ref]=n;changed();};return number;
}
function renderBanlist(root,bl){
 if(!bl){const choices=el('div',{class:'row'});for(const [id,label]of [['classic','Classic banlist'],['points','Points list']]){const b=el('button',{},'+ '+label);b.onclick=()=>createBanlist(id);choices.append(b);}root.append(el('h2',{},'Banlists'),choices);return;}
 root.append(el('h2',{},bl.id==='classic'?'Classic banlist':'Points list'),field('Name',bl.name,v=>{bl.name=v;changed();list();}));
 const starting=el('select',{'aria-label':'Starting list'});starting.append(el('option',{value:'base'},'Base game'));for(const b of project.banlists)starting.append(el('option',{value:b.id},b.name));starting.value=project.default_banlist;starting.onchange=()=>{project.default_banlist=starting.value;changed();};root.append(labelControl('Default for a new game',starting),starting);
 if(bl.id==='points'){const copy=el('button',{},'Copy Retro-Genesys');copy.onclick=()=>copyPointsPreset(bl);root.append(copy);}
 if(bl.id==='points')root.append(numberField('Deck point budget',bl.cap,1,65535,v=>{const n=Number(v);if(!Number.isInteger(n)||n<1||n>65535){toast('The budget must be from 1 to 65535.');editor();return;}bl.cap=n;changed();list();}));
 if(bl.id==='classic'){
  if(!baseBanlists&&!baseBanlistsLoading)baseBanlistsLoading=fetch('/api/banlists').then(r=>r.json()).then(d=>{baseBanlists=d;if(tab==='banlists')editor();}).catch(e=>toast(e.message)).finally(()=>baseBanlistsLoading=null);
  if(baseBanlists){const row=el('div',{class:'row cpu-actions'}),select=el('select',{'aria-label':'Base game banlist'});for(const b of baseBanlists)select.append(el('option',{value:b.file},b.name));const copy=el('button',{},'Copy base game list');copy.onclick=()=>{bl.cards=structuredClone(baseBanlists.find(b=>b.file===select.value).cards);changed();editor();};row.append(select,copy);root.append(row);}
 }
 const filter=el('input',{placeholder:'Find a card in this list…','aria-label':'Search list cards'});root.append(filter);const table=el('div',{class:'banlist-table'});filter.oninput=()=>{for(const row of table.children)row.hidden=!row.dataset.name.includes(filter.value.trim().toLowerCase());};
 for(const ref of Object.keys(bl.cards).sort((a,b)=>name(a).localeCompare(name(b)))){
  const row=el('div',{class:'banlist-row','data-name':name(ref).toLowerCase()}),c=resolve(ref),pick=el('button',{class:'banlist-card'},name(ref));
  if(c)pick.prepend(el('img',{src:`/api/image/card/${c.id}`,alt:'',loading:'lazy'}));pick.onclick=()=>cardInfo(ref);
  const remove=el('button',{'aria-label':`Remove ${name(ref)}`},'−');remove.onclick=()=>{delete bl.cards[ref];changed();editor();};row.append(pick,banValueControl(bl,ref),remove);table.append(row);
 }
 if(!Object.keys(bl.cards).length)table.append(el('p',{class:'muted','data-name':''},'No cards yet. Find one under Cards to add it.'));root.append(table);
 const bulk=el('details');bulk.append(el('summary',{},'Text list'));const text=el('textarea',{'aria-label':'Banlist text',placeholder:'Card = value',spellcheck:'false'});text.value=Object.entries(bl.cards).map(([ref,n])=>`${name(ref)} = ${n}`).join('\n');
 text.onchange=()=>{const cards={};try{for(const line of text.value.split('\n').map(s=>s.trim()).filter(Boolean)){const match=line.match(/^(.+?)\s*=\s*(\d+)$/);if(!match)throw Error('Write each line as Card = value.');const n=Number(match[2]),max=bl.id==='points'?99:3;if(n>max)throw Error(`Each card takes a value from 0 to ${max}.`);cards[resolve(match[1].trim())?.ref||match[1].trim()]=n;}bl.cards=cards;changed();editor();}catch(e){toast(e.message);}};bulk.append(text);root.append(bulk);
 const del=el('button',{class:'danger'},'Remove list');del.onclick=()=>{project.banlists=project.banlists.filter(b=>b!==bl);if(project.default_banlist===bl.id)project.default_banlist='base';selected=project.banlists[0]?.id;changed();list();editor();$('#add').disabled=false;};root.append(del);
}
function editor(){ensureSelection();const root=$('#editor');root.replaceChildren();if(tab==='patches'){root.append(el('span',{class:'eyebrow'},'QUALITY OF LIFE'),el('h2',{},'Patches'));for(const q of window.qol){const box=el('div',{class:'patch-option'});const label=el('label');const cb=el('input',{type:'checkbox'});cb.disabled=!q.available||(q.id==='pack-opening'&&!openingReady);cb.checked=project.patches.includes(q.id);cb.onchange=()=>{project.patches=project.patches.filter(id=>id!==q.id);if(cb.checked)project.patches.push(q.id);changed();};label.append(cb,document.createTextNode(' '+q.name));box.append(label,el('p',{class:'muted'},q.reason));if(q.id==='pack-opening'){const donor=el('button',{},openingReady?'Replace WC2010 ROM':'Import WC2010 ROM');donor.onclick=()=>$('#donorFile').click();box.append(donor);}root.append(box);}return;}
 const item=current();if(tab==='banlists'){renderBanlist(root,item);return;}if(!item){root.append(el('h2',{},tab==='opponents'?'Free Duel CPUs':'Select an item'));if(tab==='opponents'){const add=el('button',{class:'primary'},'New CPU');add.onclick=()=>$('#add').click();root.append(add);}return;}
 if(tab==='packs'){
  const head=el('div',{class:'editor-head'});head.append(el('img',{class:'pack-art',src:item.image || (item.id<97?`/api/image/pack/${item.id}`:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E'),alt:'Pack artwork'}));const info=el('div');info.append(el('span',{class:'eyebrow'},item.id<97?`BASE GAME · ${item.id}`:`NEW PACK ${item.id}`),el('h2',{},item.name.e));const art=el('button',{},'Replace pack image');art.onclick=()=>$('#artFile').click();info.append(art);head.append(info);head.ondragover=e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault();};head.ondrop=e=>{e.preventDefault();if(e.dataTransfer.files[0])importArt(e.dataTransfer.files[0]);};root.append(head);
  const language=el('select',{'aria-label':'Text language'});Object.entries(langs).forEach(([code,label])=>language.append(el('option',{value:code},label)));const textFields=el('div');function renderText(){textFields.replaceChildren(field('Pack name',item.name[language.value],v=>{item.name[language.value]=v;changed();list();}),field('Description',item.desc[language.value],v=>{item.desc[language.value]=v;changed();},'textarea'));}language.onchange=renderText;root.append(language,textFields);renderText();
  if(item.id>=97){root.append(numberField('Price (DP)',item.price??150,1,65535,v=>{item.price=Number(v);changed();}));const del=el('button',{class:'danger'},'Remove added pack');del.onclick=()=>{project.packs=project.packs.filter(p=>p!==item);selected=1;changed();list();editor();};root.append(del);}
  if(item.id===60){root.append(notice('Draws from the full card pool.'));return;}

  const missing=item.id<60||item.id>=97?rarities.filter(r=>(item.cards?.[r]?.length||0)<(r==='common'?4:1)):[];if(missing.length)root.append(notice('Add '+new Intl.ListFormat('en').format(missing.map(r=>(r==='common'?'4 Commons':'1 '+r[0].toUpperCase()+r.slice(1))))+'.'));
  root.append(sectionNavigation(item,rarities));const grid=el('div',{class:'rarities'});for(const r of rarities)grid.append(cardSection(item,r));root.append(grid);
 }else if(tab==='decks'){
  if(returnToCpu!==undefined&&cpuExists(returnToCpu)){const back=el('button',{},'Back to CPU');back.onclick=()=>{const i=returnToCpu;setTab('opponents');selected=i;list();editor();};root.append(back);}
  root.append(el('h2',{},deckLabel(item)));root.append(field('Project label',deckLabel(item),v=>{item.name=v;changed();list();}));const users=[...project.opponents.map(o=>o.deck),...(cpuMetadata?.base||[]).map(b=>project.base_cpus[b.chara]?.deck??b.deck)].filter(f=>f===item.file);if(users.length>1)root.append(notice(`${users.length} CPUs use this deck.`));
  const error=deckError(item)||(item.main.length<40?'The Main Deck needs at least 40 cards.':null);if(error)root.append(notice(error));renderDeckRules(root,item);
  root.append(sectionNavigation(item,sections));const grid=el('div',{class:'rarities'});for(const s of sections)grid.append(cardSection(item,s));root.append(grid);
 }else{
  renderCpu(root,item);

 }}
function cardInfo(ref){selectedCard=ref;const root=$('#cardInfo');root.replaceChildren();const c=resolve(ref);if(c){root.append(el('img',{class:'preview',src:`/api/image/card/${c.id}`,alt:c.name}),el('h3',{},c.name),el('p',{class:'muted'},`ID ${c.id} · ${String(c.password).padStart(8,'0')} · ATK ${c.atk} / DEF ${c.def}`),el('p',{},c.description));}else{root.append(el('h3',{},ref),notice('Replace this draft card before you export.'));}
 if(tab==='decks'&&current()){const target=el('select',{'aria-label':'Add to deck section'});for(const sec of sections)target.append(el('option',{value:sec},sec[0].toUpperCase()+sec.slice(1)));target.value=c?.placement==='extra'?'extra':addSection==='extra'?'main':addSection;target.onchange=()=>addSection=target.value;const add=el('button',{},'Add to deck');add.disabled=c?.placement==='none';add.onclick=()=>{const item=current(),next=structuredClone(item);next[target.value].push(c?.ref||ref);commitDeck(item,next);};root.append(target,add);}
 if(tab==='opponents'&&current()){const key=el('button',{},'Use as key card');key.onclick=()=>setKeyCard(current(),c?.ref||ref);root.append(key);}
 if(tab==='banlists'&&current()){const add=el('button',{},'Add to list');add.onclick=()=>{const bl=current(),key=c?`id:${c.canonical_id||c.id}`:ref;bl.cards[key]??=1;changed();editor();};root.append(add);}
 if(tab==='packs'&&current()?.id!==60){const select=el('select',{'aria-label':'Rarity to add selected card'});rarities.forEach(r=>select.append(el('option',{value:r},r[0].toUpperCase()+r.slice(1))));select.value=addRarity;select.onchange=()=>addRarity=select.value;const b=el('button',{},'Add to pack');b.onclick=()=>{const p=current();p.cards ||= {};p.cards[select.value] ||= [];if(Object.values(p.cards).flat().some(n=>(resolve(n)?.ref||n)===(c?.ref||ref))){toast('This card is already in the pack.');return;}p.cards[select.value].push(c?.ref||ref);changed();editor();list();};root.append(select,b);}
 root.append(el('h3',{},'Packs'));let count=0;for(const p of project.packs)for(const [r,names]of Object.entries(p.cards||{})){if(names.some(n=>c?resolve(n)?.name===c.name:n===ref)){count++;const row=el('div',{class:'membership'});row.append(el('b',{},r.toUpperCase()),el('div',{},p.name.e),el('small',{class:'muted'},`Pack ${p.id} · ${p.id>=97?'added':'Base game'}`));const jump=el('button',{class:'membership-link'},'Open pack');jump.onclick=()=>{setTab('packs');selected=p.id;list();editor();};row.append(jump);root.append(row);}}if(!count)root.append(el('p',{class:'muted'},'Not in any pack'));
}

function search(){const q=$('#cardSearch').value.trim().toLowerCase();const root=$('#results');root.replaceChildren();if(!q)return;const matches=catalog.filter(c=>c.name.toLowerCase().includes(q)||String(c.id)===q||String(c.password)===q).sort((a,b)=>Number(b.id===b.canonical_id)-Number(a.id===a.canonical_id)).slice(0,40);for(const c of matches){const b=el('button',{class:'result',draggable:'true'});b.append(el('img',{src:`/api/image/card/${c.id}`,alt:'',loading:'lazy'}),el('span',{},c.id===c.canonical_id?c.name:`${c.name} · alternate artwork`));b.onclick=()=>cardInfo(c.ref);b.ondragstart=e=>{e.dataTransfer.setData('application/x-wc-card',JSON.stringify({ref:c.ref}));e.dataTransfer.effectAllowed='copy';};root.append(b);}if(!matches.length)root.append(el('p',{class:'muted'},'No cards found'));if(!resolve($('#cardSearch').value.trim())){const draft=el('button',{class:'result'},'Add as draft card');draft.onclick=()=>cardInfo($('#cardSearch').value.trim());root.append(draft);}}
function setTab(value){tabViews.set(tab,{query:$('#listSearch').value,scroll:$('#editor').scrollTop});tabSelections[tab]=selected;tab=value;selected=tabSelections[tab]??(tab==='packs'?1:tab==='decks'?project.decks[0]?.file:tab==='banlists'?project.banlists[0]?.id:0);$('.tabs').querySelectorAll('button').forEach(b=>(b.classList.toggle('active',b.dataset.tab===tab),b.setAttribute('aria-pressed',String(b.dataset.tab===tab))));$('#listSearch').value=tabViews.get(tab)?.query||'';$('#listSearch').placeholder=tab==='packs'?'Find a pack…':'Find an entry…';$('#listTitle').textContent={packs:'PACK LIBRARY',decks:'DECKS',opponents:'FREE DUEL ROSTER',banlists:'BANLISTS',patches:'PATCH OPTIONS'}[tab];$('#add').hidden=tab==='patches';$('#add').disabled=tab==='banlists'&&project.banlists.length>=2;$('#add').textContent=tab==='packs'?'+ New pack':tab==='decks'?'+ Copy deck':tab==='banlists'?'+ New list':'+ New CPU';ensureSelection();list();editor();$('#editor').scrollTop=tabViews.get(tab)?.scroll||0;$('.inspector').hidden=tab==='patches';if(selectedCard)cardInfo(selectedCard);}
function showProject(p){deckRule=undefined;returnToCpu=undefined;tabViews.clear();sectionViews.clear();undoStack=[];redoStack=[];tabSelections={};tab='packs';selected=1;p.banlists ||= [];p.default_banlist ||= 'base';p.base_cpus ||= {};project=p;lastState=JSON.stringify(p);savedState=dirty?undefined:lastState;$('#dirty').textContent=dirty?'Unsaved changes':'No unsaved changes';syncActions();$('#welcome').hidden=true;$('#workspace').hidden=false;$('#projectName').value=p.name;setTab('packs');status('Ready');}
async function load(){const r=await fetch('/api/project');const data=await r.json();if(!r.ok)throw Error(data.error);catalog=data.catalog;byRef=new Map(catalog.map(c=>[c.ref,c]));byName=new Map();for(const c of catalog)if(!byName.has(c.name.toLowerCase())||c.id===c.canonical_id)byName.set(c.name.toLowerCase(),c);displayNames.clear();byPassword.clear();const counts=new Map();for(const c of catalog)counts.set(c.name,(counts.get(c.name)||0)+1);for(const c of catalog){displayNames.set(c.ref,counts.get(c.name)>1?`${c.name} [id:${c.id}]`:c.name);if(!byPassword.has(String(c.password))||c.id===c.canonical_id)byPassword.set(String(c.password),c);}dirty=false;let p=data.project;const recovery=localStorage.getItem(storageKey);if(recovery){try{const candidate=JSON.parse(recovery);if(candidate.base_sha1===p.base_sha1&&confirm('Restore the browser recovery copy?')){p=await (await api('/api/open',candidate)).json();dirty=true;}}catch{toast('The recovery copy could not be read.');}}showProject(p);loadCpuMetadata().then(()=>{if(tab==='decks'||tab==='opponents'){list();if(!$('#editor').contains(document.activeElement))editor();}}).catch(e=>toast(e.message));}
async function importArt(file){const pack=current();if(tab!=='packs'||!pack||busy)return;try{if(!file.type.startsWith('image/'))throw Error('Choose an image file.');const bmp=await createImageBitmap(file);const canvas=document.createElement('canvas');canvas.width=64;canvas.height=128;const ctx=canvas.getContext('2d');const ratio=Math.max(64/bmp.width,128/bmp.height);ctx.drawImage(bmp,(64-bmp.width*ratio)/2,(128-bmp.height*ratio)/2,bmp.width*ratio,bmp.height*ratio);pack.image=canvas.toDataURL('image/png');bmp.close();changed();list();editor();}catch(e){toast(e.message);}}
$('#start').onclick=()=>$('#romFile').click();
$('#romFile').onchange=async e=>{const f=e.target.files[0];e.target.value='';if(!f||busy)return;commitFocused();if(dirty&&!confirm('Discard current edits and open a ROM?'))return;busy=true;syncActions();try{status('Loading ROM…');await api('/api/rom',await f.arrayBuffer(),true);cpuMetadata=null;baseBanlists=null;openingReady=false;await load();}catch(e){toast(e.message);status('ROM could not be opened');}finally{busy=false;syncActions();}};
$('#openProject').onclick=()=>{if(!project){toast('Open a clean ROM first.');return;}$('#projectFile').click();};
$('#projectFile').onchange=async e=>{const f=e.target.files[0];e.target.value='';if(!f||busy)return;commitFocused();if(dirty&&!confirm('Replace current edits with this project?'))return;busy=true;syncActions();try{status('Opening project…');const p=await (await api('/api/open',JSON.parse(await f.text()))).json();dirty=false;showProject(p);persistRecovery();}catch(e){toast(e instanceof SyntaxError?'This file is not a valid project.':e.message);status('Project could not be opened');}finally{busy=false;syncActions();}};
$('#saveProject').onclick=async()=>{commitFocused();if(!project||busy)return;const state=JSON.stringify(project),before=savedState;savedState=state;dirty=false;$('#dirty').textContent='Project downloaded';try{const r=await api('/api/save',JSON.parse(state));download(await r.blob(),'project.wcmod.json');}catch(e){savedState=before;dirty=lastState!==savedState;$('#dirty').textContent=dirty?'Unsaved changes':'No unsaved changes';toast(e.message);}};
$('#export').onclick=async()=>{
 commitFocused();if(!project||busy)return;busy=true;syncActions();status('Checking project…');
 try{
  const snapshot=structuredClone(project),check=await api('/api/validate',snapshot),result=await check.json();
  if(result.issues.length){showIssues(result.issues);status('Fix project issues before exporting');return;}
  status('Building patch…');const r=await api('/api/export',snapshot);download(await r.blob(),'mod-export.zip');status('Patch and project downloaded');
 }catch(e){toast(e.message);status('Export failed');}finally{busy=false;syncActions();}
};
$('#validate').onclick=async()=>{commitFocused();if(!project||busy)return;busy=true;syncActions();try{const r=await api('/api/validate',project);showIssues((await r.json()).issues);}catch(e){toast(e.message);}finally{busy=false;syncActions();}};
$('#closeIssues').onclick=()=>$('#issues').close();$('#cardSearch').oninput=search;$('#listSearch').oninput=list;
$('#projectName').oninput=e=>{project.name=e.target.value;changed();};$('.tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
$('#add').onclick=()=>{if(tab==='packs'){let id=97;while(project.packs.some(p=>p.id===id))id++;if(id>116){toast('You can add up to 20 packs.');return;}project.packs.push({id,name:Object.fromEntries(Object.keys(langs).map(l=>[l,'New pack'])),desc:Object.fromEntries(Object.keys(langs).map(l=>[l,'New booster pack'])),price:150,cards:Object.fromEntries(rarities.map(r=>[r,[]]))});selected=id;}else if(tab==='decks'){const source=current()||project.decks.find(d=>d.main.length===40);const d=structuredClone(source);d.file='user_'+crypto.randomUUID()+'.ydc';d.name='Copy of '+deckLabel(source);project.decks.push(d);selected=d.file;}else if(tab==='banlists'){newBanlistPicker();return;}else{newCpuPicker();return;}$('#listSearch').value='';changed();list();editor();$('#editor').scrollTop=0;};
$('#artFile').onchange=e=>{if(e.target.files[0])importArt(e.target.files[0]);e.target.value='';};window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
(async()=>{try{const r=await fetch('/api/session');const s=await r.json();token=s.token;window.qol=s.qol;openingReady=s.opening_ready;if(s.loaded)await load();}catch(e){toast(e.message);}})();

$('#donorFile').onchange=async e=>{const f=e.target.files[0];e.target.value='';if(!f||busy)return;busy=true;syncActions();try{status('Importing WC2010…');await api('/api/donor/wc2010',await f.arrayBuffer(),true);openingReady=true;if(!project.patches.includes('pack-opening')){project.patches.push('pack-opening');changed();}status('WC2010 imported');if(tab==='patches')editor();}catch(e){toast(e.message);status('WC2010 import failed');}finally{busy=false;syncActions();}};


$('#undo').onclick=()=>{commitFocused();historyStep();};$('#redo').onclick=()=>{commitFocused();historyStep(true);};
$('#dismissToast').onclick=()=>$('#toast').hidden=true;
document.addEventListener('keydown',e=>{
 if(!(e.ctrlKey||e.metaKey)||e.altKey)return;
 const key=e.key.toLowerCase(),typing=e.target.matches('input,textarea,[contenteditable=true]');
 if(key==='s'){e.preventDefault();$('#saveProject').click();}
 if(!typing&&(key==='z'||key==='y')){e.preventDefault();historyStep(key==='y'||e.shiftKey);}
});
syncActions();
