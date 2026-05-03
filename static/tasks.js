/* ══════════════════════════════════════
   AUD-IT TASK MANAGER — API VERSION
   ══════════════════════════════════════ */

var SPACES = [
  {id:'stephenson', name:'Stephenson', color:'#c8102e'},
  {id:'hormel', name:'Hormel', color:'#e67e22'},
  {id:'hardes', name:'Hardes', color:'#3498db'},
  {id:'general', name:'General / Dept', color:'#888078'}
];
var PRI_CLS={high:'pri-high',med:'pri-med',low:'pri-low',none:'pri-none'};
var PRI_LBL={high:'High',med:'Med',low:'Low',none:'—'};
var PRI_ORDER={high:0,med:1,low:2,none:3};
var URG_CLS={now:'urg-now',today:'urg-today',week:'urg-week',soon:'urg-soon',date:'urg-date'};
var URG_LBL={now:'RIGHT NOW',today:'Today',week:'This Week',soon:'Whenever',date:''};
var URG_ORDER={now:0,today:1,week:2,date:3,soon:4};

// Local state (loaded from API)
var tasks=[], shows=[], journal=[];
var currentView='dashboard', currentFilter='all';
var dragIdx=null, dateCallback=null, editingJournalId=null;
var journalPage=0, JOURNAL_PER_PAGE=10;
var taskSort='manual'; // 'manual', 'urgency', 'priority'

function closeModal(id){gi(id).classList.remove('open')}
function mobToggle(){gi('sidebar').classList.toggle('open');gi('mobOverlay').classList.toggle('open')}

/* ── LOAD FROM API ── */
async function loadAll(){
  var [t, s, j] = await Promise.all([
    api('GET','/api/tasks'),
    api('GET','/api/shows'),
    api('GET','/api/journal')
  ]);
  // Map DB fields to frontend fields
  tasks = (t||[]).map(function(r){
    return {id:r.id, text:r.text, space:r.space, show:r.show_id||'',
            pri:r.priority, urg:r.urgency, date:r.due_date||'',
            notes:r.notes||'', done:!!r.done, created:r.created_at,
            sort_order:r.sort_order};
  });
  shows = (s||[]).map(function(r){
    return {id:r.id, name:r.name, space:r.space,
            archived:!!r.archived, loadIn:r.load_in, openDate:r.open_date, closeDate:r.close_date};
  });
  journal = (j||[]).map(function(r){
    return {id:r.id, date:r.date, body:r.body,
            hours:r.hours||{}, totalHours:r.total_hours||0, author:r.author||'Matthew', created:r.created_at};
  });

  buildSidebar();
  buildAddSelects();
  if(currentView==='journal') renderJournal();
  else renderTasks();
}

/* ── SIDEBAR ── */
function buildSidebar(){
  var spNav='';
  SPACES.forEach(function(sp){
    var cnt=tasks.filter(function(t){return t.space===sp.id&&!t.done&&!t.show}).length;
    var cls=currentView==='space:'+sp.id?' active':'';
    spNav+='<div class="sb-item'+cls+'" data-view="space:'+sp.id+'" onclick="setView(\'space:'+sp.id+'\')">';
    spNav+='<div class="sb-dot" style="background:'+sp.color+'"></div>'+sp.name;
    spNav+='<span class="sb-count">'+cnt+'</span></div>';
  });
  gi('space-nav').innerHTML=spNav;

  var shNav='';
  var active=shows.filter(function(s){return !s.archived});
  active.forEach(function(sh){
    var sp=SPACES.find(function(s){return s.id===sh.space})||SPACES[3];
    var cnt=tasks.filter(function(t){return t.show===sh.id&&!t.done}).length;
    var cls=currentView==='show:'+sh.id?' active':'';
    shNav+='<div class="sb-item'+cls+'" data-view="show:'+sh.id+'" onclick="setView(\'show:'+sh.id+'\')">';
    shNav+='<div class="sb-dot" style="background:'+sp.color+'"></div>'+esc(sh.name);
    shNav+='<span class="sb-count">'+cnt+'</span></div>';
  });
  if(!active.length) shNav='<div style="padding:4px 10px;font-family:var(--mono);font-size:10px;color:var(--mut);font-style:italic">No active shows</div>';
  gi('show-nav').innerHTML=shNav;

  gi('cnt-all').textContent=tasks.filter(function(t){return !t.done}).length;
  gi('cnt-journal').textContent=journal.length;

  document.querySelector('[data-view=dashboard]').className='sb-item'+(currentView==='dashboard'?' active':'');
  var jItem=document.querySelector('[data-view=journal]');
  if(jItem) jItem.className='sb-item'+(currentView==='journal'?' active':'');
}

/* ── VIEW ── */
function setView(v){
  currentView=v;
  currentFilter='all';
  journalPerson=null;
  gi('sidebar').classList.remove('open');
  gi('mobOverlay').classList.remove('open');
  document.querySelectorAll('.fpill').forEach(function(el){el.className='fpill'+(el.getAttribute('data-f')==='all'?' on':'')});

  if(v.startsWith('space:')) gi('newSpace').value=v.split(':')[1];
  else if(v.startsWith('show:')){
    var sh=shows.find(function(s){return s.id===v.split(':')[1]});
    if(sh){gi('newSpace').value=sh.space; updateShowSelect(); gi('newShow').value=sh.id;}
  }

  buildSidebar();
  updateHeader();
  var isJ=v==='journal';
  document.querySelectorAll('.add-row,.toolbar,#statsBar').forEach(function(el){el.style.display=isJ?'none':''});
  if(isJ) renderJournal(); else renderTasks();
}

function updateHeader(){
  var v=currentView;
  if(v==='dashboard'){gi('viewTitle').textContent='Dashboard';gi('viewSub').textContent='All active tasks across all spaces';}
  else if(v.startsWith('space:')){var sp=SPACES.find(function(s){return s.id===v.split(':')[1]});gi('viewTitle').textContent=sp?sp.name:'Space';gi('viewSub').textContent='All tasks for '+(sp?sp.name:'this space');}
  else if(v.startsWith('show:')){var sh=shows.find(function(s){return s.id===v.split(':')[1]});var sp=sh?SPACES.find(function(s){return s.id===sh.space}):null;gi('viewTitle').textContent=sh?sh.name:'Show';gi('viewSub').textContent=(sp?sp.name+' — ':'')+'Show Tasks';}
  else if(v==='journal'){gi('viewTitle').textContent='Daily Journal';gi('viewSub').textContent='Select a team member';}
}

function buildAddSelects(){
  var h='';SPACES.forEach(function(sp){h+='<option value="'+sp.id+'">'+sp.name+'</option>';});
  gi('newSpace').innerHTML=h;gi('newShowSpace').innerHTML=h;
  updateShowSelect();
  gi('newUrg').onchange=function(){gi('newDate').style.display=this.value==='date'?'block':'none';if(this.value==='date'&&!gi('newDate').value)gi('newDate').value=new Date().toLocaleDateString('en-CA');};
  gi('newSpace').onchange=function(){updateShowSelect()};
}

function updateShowSelect(){
  var spId=gi('newSpace').value;
  var ss=shows.filter(function(s){return s.space===spId&&!s.archived});
  var h='<option value="">No Show</option>';
  ss.forEach(function(s){h+='<option value="'+s.id+'">'+esc(s.name)+'</option>';});
  gi('newShow').innerHTML=h;
}

/* ── ADD TASK ── */
async function addTask(){
  var text=gi('newTask').value.trim();if(!text)return;
  var task={id:uid(),text:text,space:gi('newSpace').value,show:gi('newShow').value||'',
    pri:gi('newPri').value,urg:gi('newUrg').value,
    date:gi('newUrg').value==='date'?gi('newDate').value:'',notes:'',done:false,sort_order:tasks.length};
  await api('POST','/api/tasks',task);
  tasks.push(task);
 gi('newTask').value='';gi('newPri').value='none';gi('newUrg').value='soon';gi('newDate').style.display='none';
  buildSidebar();renderTasks();gi('newTask').focus();toast('Task added');
   
/* ── TASK ACTIONS ── */
async function toggleTask(id){
  var t=tasks.find(function(x){return x.id===id});if(!t)return;
  t.done=!t.done;
  await api('PUT','/api/tasks/'+id,{done:t.done?1:0});
  buildSidebar();renderTasks();
}
async function delTask(id){
  await api('DELETE','/api/tasks/'+id);
  tasks=tasks.filter(function(x){return x.id!==id});
  buildSidebar();renderTasks();toast('Task removed');
}
async function clearDone(){
  var inView=getViewTasks().filter(function(t){return t.done});
  if(!inView.length){toast('No completed tasks');return;}
  if(!confirm('Clear '+inView.length+' completed?'))return;
  for(var i=0;i<inView.length;i++) await api('DELETE','/api/tasks/'+inView[i].id);
  var ids=inView.map(function(t){return t.id});
  tasks=tasks.filter(function(t){return ids.indexOf(t.id)===-1});
  buildSidebar();renderTasks();toast(inView.length+' cleared');
}

/* ── EDIT TEXT ── */
function editText(id,el){
  el.contentEditable=true;el.focus();
  var range=document.createRange();range.selectNodeContents(el);var sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);
  function finish(){el.contentEditable=false;var txt=el.textContent.trim();var t=tasks.find(function(x){return x.id===id});
    if(t&&txt){t.text=txt;api('PUT','/api/tasks/'+id,{text:txt});}else renderTasks();}
  el.onblur=finish;
  el.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();el.blur();}if(e.key==='Escape'){el.textContent=tasks.find(function(x){return x.id===id}).text;el.blur();}};
}

/* ── NOTES ── */
function toggleNotes(id){
  var area=gi('tna-'+id),bar=gi('tnb-'+id);if(!area)return;
  var isOpen=area.classList.contains('open');
  document.querySelectorAll('.task-notes-area.open').forEach(function(el){el.classList.remove('open')});
  document.querySelectorAll('.task-notes-bar').forEach(function(el){el.style.display=''});
  if(!isOpen){area.classList.add('open');if(bar)bar.style.display='none';var ta=area.querySelector('textarea');if(ta)ta.focus();}
}
function saveNote(id,val){
  var t=tasks.find(function(x){return x.id===id});if(!t)return;
  if(t.notes!==val){t.notes=val;api('PUT','/api/tasks/'+id,{notes:val});renderTasks();}
}

/* ── PRIORITY / URGENCY CTX ── */
function showCtx(e,type,taskId){
  e.stopPropagation();closeCtx();
  var menu=document.createElement('div');menu.className='ctx-menu';menu.id='ctx-active';
  var options=type==='pri'?[{val:'high',label:'High',color:'#e74c3c'},{val:'med',label:'Medium',color:'#eb984e'},{val:'low',label:'Low',color:'#58d68d'},{val:'none',label:'None',color:'#888'}]
    :[{val:'now',label:'Right Now',color:'#e74c3c'},{val:'today',label:'Today',color:'#eb984e'},{val:'week',label:'This Week',color:'#5dade2'},{val:'soon',label:'Whenever',color:'#888'},{val:'date',label:'Set Date...',color:'#bb8fce'}];
  options.forEach(function(o){
    var opt=document.createElement('div');opt.className='ctx-option';
    opt.innerHTML='<span class="dot" style="background:'+o.color+'"></span>'+o.label;
    opt.onclick=function(ev){ev.stopPropagation();var t=tasks.find(function(x){return x.id===taskId});if(!t)return;
      if(type==='pri'){t.pri=o.val;api('PUT','/api/tasks/'+taskId,{pri:o.val});renderTasks();closeCtx();}
      else{if(o.val==='date'){closeCtx();dateCallback=function(d){t.urg='date';t.date=d;api('PUT','/api/tasks/'+taskId,{urg:'date',date:d});renderTasks();};gi('modalDate').value=t.date||new Date().toLocaleDateString('en-CA');gi('dateModal').classList.add('open');}
      else{t.urg=o.val;t.date='';api('PUT','/api/tasks/'+taskId,{urg:o.val,date:''});renderTasks();closeCtx();}}};
    menu.appendChild(opt);
  });
  document.body.appendChild(menu);
  var rect=e.target.getBoundingClientRect();
  menu.style.top=Math.min(rect.bottom+4,window.innerHeight-menu.offsetHeight-8)+'px';
  menu.style.left=Math.min(rect.left,window.innerWidth-menu.offsetWidth-8)+'px';
  setTimeout(function(){document.addEventListener('click',closeCtx,{once:true})},10);
}
function closeCtx(){var el=gi('ctx-active');if(el)el.remove();}
function confirmDate(){var d=gi('modalDate').value;if(d&&dateCallback){dateCallback(d);dateCallback=null;}closeModal('dateModal');}

/* ── DRAG ── */
function dragStart(e,id){dragIdx=tasks.findIndex(function(t){return t.id===id});e.dataTransfer.effectAllowed='move';e.target.closest('.task').classList.add('dragging');}
function dragOver(e){e.preventDefault();var el=e.target.closest('.task-wrap');if(el)el.querySelector('.task').classList.add('drag-over');}
function dragLeave(e){var el=e.target.closest('.task-wrap');if(el)el.querySelector('.task').classList.remove('drag-over');}
async function drop(e,id){
  e.preventDefault();var toIdx=tasks.findIndex(function(t){return t.id===id});
  if(dragIdx!==null&&dragIdx!==toIdx){var item=tasks.splice(dragIdx,1)[0];tasks.splice(toIdx,0,item);
    await api('POST','/api/tasks/reorder',{ids:tasks.map(function(t){return t.id})});}
  dragIdx=null;renderTasks();
}
function dragEnd(){dragIdx=null;document.querySelectorAll('.task').forEach(function(el){el.classList.remove('dragging','drag-over')});}

/* ── SORT ── */
function toggleSort(){
  var modes=['manual','urgency','priority'];
  var labels=['Sort: Manual','Sort: Urgency','Sort: Priority'];
  var idx=modes.indexOf(taskSort);
  idx=(idx+1)%modes.length;
  taskSort=modes[idx];
  gi('sortBtn').textContent=labels[idx];
  renderTasks();
}

function sortTasks(arr){
  if(taskSort==='manual') return arr;
  var sorted=arr.slice();
  if(taskSort==='urgency'){
    sorted.sort(function(a,b){var u=(URG_ORDER[a.urg]||4)-(URG_ORDER[b.urg]||4);return u!==0?u:(PRI_ORDER[a.pri]||3)-(PRI_ORDER[b.pri]||3);});
  } else if(taskSort==='priority'){
    sorted.sort(function(a,b){var p=(PRI_ORDER[a.pri]||3)-(PRI_ORDER[b.pri]||3);return p!==0?p:(URG_ORDER[a.urg]||4)-(URG_ORDER[b.urg]||4);});
  }
  return sorted;
}

/* ── FILTER ── */
function getViewTasks(){var v=currentView;return tasks.filter(function(t){if(v==='dashboard')return true;if(v.startsWith('space:'))return t.space===v.split(':')[1]&&!t.show;if(v.startsWith('show:'))return t.show===v.split(':')[1];return true;});}
function getFilteredTasks(){var ts=getViewTasks(),f=currentFilter;return ts.filter(function(t){if(f==='active')return!t.done;if(f==='done')return t.done;if(f==='high')return t.pri==='high'&&!t.done;if(f==='med')return t.pri==='med'&&!t.done;if(f==='low')return t.pri==='low'&&!t.done;if(f==='now')return t.urg==='now'&&!t.done;if(f==='today')return t.urg==='today'&&!t.done;if(f==='week')return t.urg==='week'&&!t.done;return true;});}
function setFilter(f){currentFilter=f;document.querySelectorAll('.fpill').forEach(function(el){el.className='fpill'+(el.getAttribute('data-f')===f?' on':'')});renderTasks();}

/* ── RENDER ── */
function renderTasks(){
  var filtered=getFilteredTasks(),view=getViewTasks();
  var total=view.length,done=view.filter(function(t){return t.done}).length,active=total-done;
  var highCnt=view.filter(function(t){return t.pri==='high'&&!t.done}).length;
  var nowCnt=view.filter(function(t){return t.urg==='now'&&!t.done}).length;
  gi('statsBar').innerHTML='<div class="stat"><span class="stat-num">'+total+'</span><span class="stat-lbl">Total</span></div>'
    +'<div class="stat"><span class="stat-num">'+active+'</span><span class="stat-lbl">Active</span></div>'
    +'<div class="stat stat-grn"><span class="stat-num">'+done+'</span><span class="stat-lbl">Done</span></div>'
    +(highCnt?'<div class="stat stat-red"><span class="stat-num">'+highCnt+'</span><span class="stat-lbl">High Pri</span></div>':'')
    +(nowCnt?'<div class="stat stat-red"><span class="stat-num">'+nowCnt+'</span><span class="stat-lbl">Right Now</span></div>':'');
  if(!filtered.length){gi('tlist').innerHTML='<div class="empty-state">'+(total?'No tasks match this filter':'No tasks yet — add one above')+'</div>';return;}
  filtered=sortTasks(filtered);
  var html='';
  if(currentView==='dashboard'){SPACES.forEach(function(sp){var st=filtered.filter(function(t){return t.space===sp.id});if(!st.length)return;html+='<div class="task-group-label" style="color:'+sp.color+'">'+sp.name+' ('+st.filter(function(t){return!t.done}).length+' active)</div>';st.forEach(function(t){html+=renderTask(t)});});}
  else{filtered.forEach(function(t){html+=renderTask(t)});}
  gi('tlist').innerHTML=html;
}

function renderTask(t){
  var sp=SPACES.find(function(s){return s.id===t.space})||SPACES[3];
  var sh=t.show?shows.find(function(s){return s.id===t.show}):null;
  var urgLabel=t.urg==='date'&&t.date?fmtDate(t.date):URG_LBL[t.urg]||'';
  var urgCls=URG_CLS[t.urg]||'urg-soon';
  var hasNote=t.notes&&t.notes.trim().length>0;
  var notePreview=hasNote?esc(t.notes.trim().substring(0,60))+(t.notes.length>60?'...':''):'';
  var h='<div class="task-wrap'+(hasNote?'':' no-notes')+'" id="tw-'+t.id+'">';
  h+='<div class="task'+(t.done?' done':'')+'" draggable="true" ondragstart="dragStart(event,\''+t.id+'\')" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="drop(event,\''+t.id+'\')" ondragend="dragEnd()">';
  h+='<input type="checkbox" class="task-cb"'+(t.done?' checked':'')+' onchange="toggleTask(\''+t.id+'\')">';
  h+='<span class="task-text" ondblclick="editText(\''+t.id+'\',this)">'+esc(t.text);
  if(sh) h+=' <span style="font-family:var(--mono);font-size:9px;color:'+sp.color+';opacity:.7">'+esc(sh.name)+'</span>';
  h+='</span>';
  h+='<button class="note-toggle'+(hasNote?' has-note':'')+'" onclick="toggleNotes(\''+t.id+'\')" title="'+(hasNote?'View notes':'Add notes')+'">&#x1F4DD; '+(hasNote?'Notes':'Note')+'</button>';
  h+='<span class="task-badges">';
  h+='<span class="task-urg '+urgCls+'" onclick="showCtx(event,\'urg\',\''+t.id+'\')">'+urgLabel+'</span>';
  h+='<span class="task-pri '+PRI_CLS[t.pri]+'" onclick="showCtx(event,\'pri\',\''+t.id+'\')">'+PRI_LBL[t.pri]+'</span>';
  h+='</span>';
  h+='<button class="xbtn" onclick="delTask(\''+t.id+'\')">&#x2715;</button>';
  h+='</div>';
  if(hasNote){h+='<div class="task-notes-bar" id="tnb-'+t.id+'"><span class="task-note-preview">'+notePreview+'</span></div>';}
  h+='<div class="task-notes-area" id="tna-'+t.id+'"><textarea placeholder="Add context, blockers, follow-ups..." onblur="saveNote(\''+t.id+'\',this.value)" onkeydown="if(event.key===\'Escape\')this.blur()">'+esc(t.notes||'')+'</textarea></div>';
  h+='</div>';
  return h;
}

function fmtDate(d){try{var dt=new Date(d+'T00:00:00');var m=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];return m[dt.getMonth()]+' '+dt.getDate();}catch(e){return d}}
function fmtDateLong(d){try{return new Date(d+'T00:00:00').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'});}catch(e){return d}}
function getDayOfWeek(d){try{return new Date(d+'T00:00:00').toLocaleDateString('en-US',{weekday:'long'});}catch(e){return ''}}

/* ── SHOWS ── */
function openShowModal(){renderShowList();gi('showModal').classList.add('open');}
async function addShow(){
  var name=gi('newShowName').value.trim();if(!name)return;
  var sh={id:uid(),name:name,space:gi('newShowSpace').value,archived:false};
  await api('POST','/api/shows',sh);
  shows.push(sh);gi('newShowName').value='';
  buildSidebar();buildAddSelects();renderShowList();toast('"'+name+'" added');
}
async function archiveShow(id){var sh=shows.find(function(s){return s.id===id});if(!sh)return;sh.archived=true;await api('PUT','/api/shows/'+id,{archived:1});buildSidebar();buildAddSelects();renderShowList();toast('"'+sh.name+'" archived');}
async function unarchiveShow(id){var sh=shows.find(function(s){return s.id===id});if(!sh)return;sh.archived=false;await api('PUT','/api/shows/'+id,{archived:0});buildSidebar();buildAddSelects();renderShowList();toast('"'+sh.name+'" restored');}
async function deleteShow(id){
  var sh=shows.find(function(s){return s.id===id});if(!sh)return;
  var cnt=tasks.filter(function(t){return t.show===id}).length;
  if(!confirm('Delete "'+sh.name+'"?'+(cnt?'\n'+cnt+' tasks will be unlinked.':'')))return;
  await api('DELETE','/api/shows/'+id);
  shows=shows.filter(function(s){return s.id!==id});
  tasks.forEach(function(t){if(t.show===id)t.show='';});
  buildSidebar();buildAddSelects();renderShowList();toast('"'+sh.name+'" deleted');
}
function renderShowList(){
  var a=shows.filter(function(s){return !s.archived}),ar=shows.filter(function(s){return s.archived});
  var h='';if(!a.length)h='<div style="color:var(--mut);font-size:11px;font-style:italic;padding:8px">No active shows</div>';
  a.forEach(function(s){var sp=SPACES.find(function(x){return x.id===s.space})||SPACES[3];var cnt=tasks.filter(function(t){return t.show===s.id}).length;h+='<div class="show-manage-item"><div class="sb-dot" style="background:'+sp.color+'"></div><span>'+esc(s.name)+' <span style="color:var(--mut);font-size:9px">('+sp.name+', '+cnt+')</span></span><button onclick="archiveShow(\''+s.id+'\')" title="Archive">&#x2193;</button><button onclick="deleteShow(\''+s.id+'\')" title="Delete">&#x2715;</button></div>';});
  gi('showList').innerHTML=h;
  var ah='';if(!ar.length)ah='<div style="color:var(--mut);font-size:11px;font-style:italic;padding:8px">None</div>';
  ar.forEach(function(s){ah+='<div class="show-manage-item" style="opacity:.6"><div class="sb-dot" style="background:var(--mut)"></div><span>'+esc(s.name)+'</span><button onclick="unarchiveShow(\''+s.id+'\')">&#x2191;</button><button onclick="deleteShow(\''+s.id+'\')">&#x2715;</button></div>';});
  gi('archivedShowList').innerHTML=ah;
}

/* ── JOURNAL ── */
var TEAM=['Matthew','Katie','Jess'];
var AUTHOR_CLS={Matthew:'author-matthew',Katie:'author-katie',Jess:'author-jess'};
var AUTHOR_COLOR={Matthew:'#c8102e',Katie:'#3498db',Jess:'#27ae60'};
var journalAuthorFilter='all';
var journalPerson=null; // null = show covers, string = show that person's entries

function openJournalModal(existingId, defaultAuthor){
  editingJournalId=existingId||null;
  var entry=existingId?journal.find(function(j){return j.id===existingId}):null;
  gi('jmTitle').textContent=entry?'Edit Entry':'Log Your Day';
  gi('jmSaveBtn').textContent=entry?'Update Entry':'Save Entry';
  gi('jmAuthor').value=entry&&entry.author?entry.author:(defaultAuthor||'Matthew');
  gi('jmDate').value=entry?entry.date:new Date().toLocaleDateString('en-CA');
  gi('jmBody').value=entry?entry.body:'';
  var h='';SPACES.forEach(function(sp){var val=entry&&entry.hours&&entry.hours[sp.id]?entry.hours[sp.id]:'';h+='<div class="jm-hour-row"><div class="sb-dot" style="background:'+sp.color+'"></div><label>'+sp.name+'</label><input type="number" min="0" max="24" step="0.25" id="jmh-'+sp.id+'" value="'+val+'" placeholder="0" oninput="updateJmTotal()"></div>';});
  gi('jmHoursGrid').innerHTML=h;updateJmTotal();
  gi('journalModal').classList.add('open');
  setTimeout(function(){gi('jmBody').focus()},150);
}
function updateJmTotal(){var total=0;SPACES.forEach(function(sp){total+=parseFloat(gi('jmh-'+sp.id).value)||0;});gi('jmTotal').innerHTML='Total: <b>'+total+'</b> hrs';}

async function saveJournalEntry(){
  var date=gi('jmDate').value,body=gi('jmBody').value.trim(),author=gi('jmAuthor').value;
  if(!date){toast('Set a date');return;}if(!body){toast('Write something');return;}
  var hours={},totalHrs=0;
  SPACES.forEach(function(sp){var v=parseFloat(gi('jmh-'+sp.id).value)||0;if(v>0){hours[sp.id]=v;totalHrs+=v;}});
  if(editingJournalId){
    var entry=journal.find(function(j){return j.id===editingJournalId});
    if(entry){entry.date=date;entry.body=body;entry.hours=hours;entry.totalHours=totalHrs;entry.author=author;}
    await api('PUT','/api/journal/'+editingJournalId,{date:date,body:body,hours:hours,totalHours:totalHrs,author:author});
    toast('Entry updated');
  } else {
    var ne={id:uid(),date:date,body:body,hours:hours,totalHours:totalHrs,author:author,created:new Date().toISOString()};
    await api('POST','/api/journal',ne);
    journal.push(ne);toast('Day logged — '+author);
  }
  journal.sort(function(a,b){return b.date.localeCompare(a.date)});
  editingJournalId=null;closeModal('journalModal');buildSidebar();
  if(currentView==='journal'){
    if(journalPerson) renderJournalPerson(journalPerson);
    else renderJournal();
  }
}

async function deleteJournalEntry(id){
  var e=journal.find(function(j){return j.id===id});if(!e)return;
  if(!confirm('Delete entry for '+fmtDateLong(e.date)+'?'))return;
  await api('DELETE','/api/journal/'+id);
  journal=journal.filter(function(j){return j.id!==id});
  buildSidebar();renderJournal();toast('Entry deleted');
}

function renderJournal(){
  var list=gi('tlist');
  if(journalPerson) return renderJournalPerson(journalPerson);

  // Book cover view
  var html='<div class="journal-covers">';
  TEAM.forEach(function(name){
    var entries=journal.filter(function(e){return e.author===name});
    var totalHrs=0;entries.forEach(function(e){totalHrs+=e.totalHours||0});
    var latest=entries.length?entries[0]:null;
    var color=AUTHOR_COLOR[name]||'#888';
    html+='<div class="journal-cover" onclick="openJournalPerson(\''+name+'\')">';
    html+='<div class="journal-cover-bar" style="background:'+color+'"></div>';
    html+='<div class="journal-cover-name">'+esc(name)+'</div>';
    html+='<div class="journal-cover-stat">'+entries.length+' entr'+(entries.length===1?'y':'ies')+' &middot; '+totalHrs.toFixed(1)+' hrs</div>';
    if(latest) html+='<div class="journal-cover-latest">Last: '+fmtDateLong(latest.date)+'</div>';
    else html+='<div class="journal-cover-latest">No entries yet</div>';
    html+='</div>';
  });
  html+='</div>';
  list.innerHTML=html;
}

function openJournalPerson(name){
  journalPerson=name;
  journalPage=0;
  gi('viewTitle').textContent=name+'\'s Journal';
  gi('viewSub').textContent='Daily logs and hours';
  renderJournalPerson(name);
}

function closeJournalPerson(){
  journalPerson=null;
  gi('viewTitle').textContent='Daily Journal';
  gi('viewSub').textContent='Select a team member';
  renderJournal();
}

function renderJournalPerson(name){
  var list=gi('tlist');
  var entries=journal.filter(function(e){return e.author===name});
  var color=AUTHOR_COLOR[name]||'#888';

  var html='<div class="journal-back" onclick="closeJournalPerson()">&#x2190; All Journals</div>';

  // Add entry button
  html+='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">';
  html+='<div class="journal-person-header"><div class="journal-person-name" style="color:'+color+'">'+esc(name)+'</div></div>';
  html+='<button class="btn btnp" onclick="openJournalModal(null,\''+name+'\')">+ Add Entry</button>';
  html+='</div>';

  if(!entries.length){
    html+='<div class="journal-empty"><div class="journal-empty-text">No entries yet for '+esc(name)+'</div></div>';
    list.innerHTML=html;return;
  }

  // Stats
  var totalHrs=0,spaceTotals={};SPACES.forEach(function(sp){spaceTotals[sp.id]=0;});
  entries.forEach(function(e){totalHrs+=e.totalHours||0;SPACES.forEach(function(sp){spaceTotals[sp.id]+=(e.hours&&e.hours[sp.id])||0;});});
  var now=new Date(),wa=new Date(now);wa.setDate(wa.getDate()-7);var ws=wa.toISOString().slice(0,10);
  var weekHrs=0;entries.filter(function(e){return e.date>=ws}).forEach(function(e){weekHrs+=e.totalHours||0;});

  html+='<div class="journal-summary">';
  html+='<div class="js-card"><div class="js-card-num">'+entries.length+'</div><div class="js-card-lbl">Entries</div></div>';
  html+='<div class="js-card js-card-accent"><div class="js-card-num">'+totalHrs.toFixed(1)+'</div><div class="js-card-lbl">Total Hours</div></div>';
  html+='<div class="js-card"><div class="js-card-num">'+weekHrs.toFixed(1)+'</div><div class="js-card-lbl">This Week</div></div>';
  html+='<div class="js-card"><div class="js-card-num">'+(entries.length?(totalHrs/entries.length).toFixed(1):'0')+'</div><div class="js-card-lbl">Avg / Day</div></div>';
  SPACES.forEach(function(sp){if(spaceTotals[sp.id]>0)html+='<div class="js-card"><div class="js-card-num" style="color:'+sp.color+'">'+spaceTotals[sp.id].toFixed(1)+'</div><div class="js-card-lbl">'+sp.name+'</div></div>';});
  html+='</div>';

  // Pagination
  var start=journalPage*JOURNAL_PER_PAGE,page=entries.slice(start,start+JOURNAL_PER_PAGE),tp=Math.ceil(entries.length/JOURNAL_PER_PAGE);
  if(tp>1)html+='<div class="journal-nav"><button onclick="jPrev()"'+(journalPage<=0?' disabled style="opacity:.3"':'')+'>&#x2190; Newer</button><span class="journal-nav-label">Page '+(journalPage+1)+'/'+tp+'</span><button onclick="jNext()"'+(journalPage>=tp-1?' disabled style="opacity:.3"':'')+'>Older &#x2192;</button></div>';

  page.forEach(function(e){
    html+='<div class="journal-entry" style="border-left-color:'+color+'">';
    html+='<div class="journal-date"><span>'+fmtDateLong(e.date)+'</span><div class="journal-actions" style="opacity:1"><button class="btn" style="height:24px;font-size:9px;padding:0 8px" onclick="openJournalModal(\''+e.id+'\',\''+name+'\')">Edit</button><button class="btn" style="height:24px;font-size:9px;padding:0 8px" onclick="deleteJournalEntry(\''+e.id+'\')">&#x2715;</button></div></div>';
    html+='<div class="journal-date-sub">'+getDayOfWeek(e.date)+'</div>';
    if(e.totalHours>0){html+='<div class="journal-hours">';SPACES.forEach(function(sp){var hrs=(e.hours&&e.hours[sp.id])||0;if(hrs>0)html+='<span class="journal-hour-chip"><span class="jh-dot" style="background:'+sp.color+'"></span>'+sp.name+': <span class="jh-val">'+hrs+'h</span></span>';});html+='<span class="journal-total">'+e.totalHours.toFixed(1)+' hrs total</span></div>';}
    html+='<div class="journal-body">'+esc(e.body)+'</div></div>';
  });
  list.innerHTML=html;
}
function setJAuthor(a){journalAuthorFilter=a;journalPage=0;renderJournal();}
function jPrev(){if(journalPage>0){journalPage--;if(journalPerson)renderJournalPerson(journalPerson);else renderJournal();}}
function jNext(){var entries=journalPerson?journal.filter(function(e){return e.author===journalPerson}):journal;var tp=Math.ceil(entries.length/JOURNAL_PER_PAGE);if(journalPage<tp-1){journalPage++;if(journalPerson)renderJournalPerson(journalPerson);else renderJournal();}}

/* ── EXPORT / IMPORT ── */
async function tskExportJSON(){
  var data=await api('GET','/api/backup');
  var blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='AUD-IT_Backup_'+new Date().toISOString().slice(0,10)+'.json';a.click();
  URL.revokeObjectURL(a.href);toast('Backup exported');
}

function tskImportJSON(e){
  var file=e.target.files[0];if(!file)return;
  var reader=new FileReader();
  reader.onload=async function(ev){
    try{
      var d=JSON.parse(ev.target.result);
      if(d.tasks && Array.isArray(d.tasks)){
        // Task-specific or full backup
        if(!confirm('Restore tasks and journal from backup?'))return;
        await api('POST','/api/restore/tasks',{tasks:d.tasks,journal:d.journal||[],shows:d.shows||[]});
        await loadAll();toast('Tasks restored');
      } else if(d.type==='audit_suite_backup'){
        if(!confirm('Restore all data from suite backup?'))return;
        await api('POST','/api/restore/full',d);
        await loadAll();toast('Suite restored');
      } else {toast('Unrecognized format');}
    }catch(err){toast('Import failed: '+err.message);}
    e.target.value='';
  };
  reader.readAsText(file);
}

function tskExportCSV(){
  var rows=[['ID','Text','Space','Show','Priority','Urgency','Due Date','Notes','Done','Created']];
  tasks.forEach(function(t){var sp=SPACES.find(function(s){return s.id===t.space});var sh=t.show?shows.find(function(s){return s.id===t.show}):null;
    rows.push([t.id,'"'+t.text.replace(/"/g,'""')+'"',sp?sp.name:'',sh?sh.name:'',PRI_LBL[t.pri]||'',URG_LBL[t.urg]||(t.urg==='date'?t.date:''),t.date||'','"'+(t.notes||'').replace(/"/g,'""')+'"',t.done?'Yes':'No',t.created||'']);});
  var csv=rows.map(function(r){return r.join(',')}).join('\n');
  var blob=new Blob([csv],{type:'text/csv'});var a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='audit-tasks-'+new Date().toISOString().slice(0,10)+'.csv';a.click();toast('CSV exported');
}

/* ── PRINT ── */
function printList(){
  if(currentView==='journal')return printJournal();
  var ts=getFilteredTasks().filter(function(t){return !t.done});if(!ts.length){toast('No active tasks');return;}
  ts.sort(function(a,b){var u=(URG_ORDER[a.urg]||4)-(URG_ORDER[b.urg]||4);return u!==0?u:(PRI_ORDER[a.pri]||3)-(PRI_ORDER[b.pri]||3);});
  var today=new Date().toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric'});
  var PPRI={high:'ppri-high',med:'ppri-med',low:'ppri-low',none:'ppri-none'};
  var rows='';ts.forEach(function(t){var sh=t.show?shows.find(function(s){return s.id===t.show}):null;var sp=SPACES.find(function(s){return s.id===t.space});var urgStr=t.urg==='date'&&t.date?fmtDate(t.date):(URG_LBL[t.urg]||'');
    rows+='<tr><td style="width:24px;text-align:center"><span class="pcb"></span></td><td style="font-size:11px">'+esc(t.text)+(sh?' <span style="font-size:8px;color:#999">['+esc(sh.name)+']</span>':'')+(t.notes?'<div style="font-size:9px;color:#888;margin-top:2px;font-style:italic">'+esc(t.notes.substring(0,120))+'</div>':'')+'</td><td style="text-align:center;font-size:9px;color:#666">'+(sp?sp.name:'')+'</td><td style="text-align:center"><span class="ppri '+PPRI[t.pri]+'">'+PRI_LBL[t.pri].toUpperCase()+'</span></td><td style="text-align:center;font-size:9px;color:#666">'+urgStr+'</td><td class="pinit-cell"><span class="pinit-line"></span></td></tr>';});
  gi('pr').innerHTML='<div style="padding:20mm"><div class="ph"><div class="pho">Phoenix Theatre Company — Audio Department</div><div class="pht">'+esc(gi('viewTitle').textContent)+'</div><div class="phm">'+ts.length+' tasks &middot; Printed '+today+'</div></div><table class="ptbl"><thead><tr><th style="width:28px">&#x2610;</th><th>Task</th><th style="width:80px;text-align:center">Space</th><th style="width:60px;text-align:center">Priority</th><th style="width:70px;text-align:center">Urgency</th><th style="width:70px">Initials</th></tr></thead><tbody>'+rows+'</tbody></table><div class="pft"><span>AUD-IT Task Manager</span><span>'+today+'</span></div></div>';
  setTimeout(function(){window.print()},200);
}
function printJournal(){
  if(!journal.length){toast('No entries');return;}
  var today=new Date().toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric'});
  var totalHrs=0;journal.forEach(function(e){totalHrs+=e.totalHours||0;});
  var body='';journal.forEach(function(e){body+='<div class="pj-entry"><div class="pj-date">'+fmtDateLong(e.date)+' — '+getDayOfWeek(e.date)+' <span style="font-weight:400;color:#999">('+(e.author||'Matthew')+')</span></div>';if(e.totalHours>0){var hp=[];SPACES.forEach(function(sp){var hrs=(e.hours&&e.hours[sp.id])||0;if(hrs>0)hp.push(sp.name+': '+hrs+'h');});body+='<div class="pj-hours">'+hp.join(' | ')+' — '+e.totalHours.toFixed(1)+' hrs</div>';}body+='<div class="pj-body">'+esc(e.body)+'</div></div>';});
  gi('pr').innerHTML='<div style="padding:20mm"><div class="ph"><div class="pho">Phoenix Theatre Company — Audio Department</div><div class="pht">Daily Journal</div><div class="phm">'+journal.length+' entries &middot; '+totalHrs.toFixed(1)+' hrs &middot; '+today+'</div></div>'+body+'<div class="pft"><span>AUD-IT Task Manager</span><span>'+today+'</span></div></div>';
  setTimeout(function(){window.print()},200);
}

/* ── INIT ── */
loadAll();

/* ── SMART POLLING — only reload if data changed ── */
var _lastMod='';
async function pollForChanges(){
  var res=await api('GET','/api/last-modified');
  if(!res) return;
  if(_lastMod && res.ts !== _lastMod){
    await loadAll();
  }
  _lastMod=res.ts||'';
}
setInterval(pollForChanges, 10000);
