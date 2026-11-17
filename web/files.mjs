const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function showFiles(container){
 container.innerHTML='<div class="card">Loading sandbox files…</div>';
 let state,selected;
 const alive=()=>document.querySelector('#file-panel')===container.querySelector('#file-panel');
 async function load(){const r=await fetch('/api/files',{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'Cannot load files');state=d;selected=state.files.find(f=>f.id===selected?.id)||state.files[0];}
 function draw(message=''){
 container.innerHTML=`<div id="file-panel"><div class="notice"><div><b>Real file operations · sandbox only</b><br>${esc(state.root)} · Edits and restores automatically preserve the previous file in .backups.</div></div><div class="cards" style="margin-top:20px"><section class="card"><h3>Managed sample saves</h3><p>These files are synthetic. The save-library rules do not control these manual sandbox actions.</p>${state.files.map(f=>`<button class="file-choice secondary" data-file="${f.id}" aria-pressed="${f.id===selected.id}" style="display:block;width:100%;text-align:left;margin-top:15px"><b>${esc(f.game)}</b><br><small>${esc(f.path)} · ${f.bytes} bytes · ${f.backups.length} backups</small></button>`).join('')}<button class="secondary" id="file-refresh" style="margin-top:20px">Refresh from disk</button></section><section class="card"><h3>${esc(selected.game)}</h3><p>${esc(selected.path)}</p><label for="file-content" style="display:block;margin:18px 0 8px">Save contents (JSON)</label><textarea id="file-content" spellcheck="false" style="width:100%;min-height:230px;background:#0c192d;color:#e4edfa;border:1px solid #365070;border-radius:7px;padding:14px;font:12px monospace">${esc(selected.content)}</textarea><div style="display:flex;gap:10px;margin-top:15px"><button class="primary" id="file-save">Save changes</button><button class="secondary" id="file-backup">Create backup</button></div><label for="file-version" style="display:block;margin:25px 0 8px">Restore a backup</label><select id="file-version" class="select" style="max-width:100%;width:100%" ${selected.backups.length?'':'disabled'}>${selected.backups.length?selected.backups.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join(''):'<option>No backups yet</option>'}</select><button class="secondary" id="file-restore" style="margin-top:10px" ${selected.backups.length?'':'disabled'}>Restore selected backup</button><p id="file-message" role="status" style="margin-top:15px">${esc(message)}</p></section></div></div>`;
 const panel=container.querySelector('#file-panel');
 const dirty=()=>panel.querySelector('#file-content').value!==selected.content;
 const discard=()=>!dirty()||confirm('Discard your unsaved editor changes?');
 panel.querySelectorAll('[data-file]').forEach(b=>b.onclick=()=>{if(discard()){selected=state.files.find(f=>f.id===b.dataset.file);draw()}});
 panel.querySelector('#file-refresh').onclick=async()=>{if(!discard())return;try{await load();if(container.contains(panel))draw('Reloaded from disk.')}catch(e){panel.querySelector('#file-message').textContent=e.message}};
 async function action(type){
  if(type==='restore'&&!confirm('Restore this backup? The current file will be backed up first.'))return;
  if(type==='backup'&&dirty()&&!confirm('Back up the file currently on disk? Unsaved editor changes will be discarded.'))return;
  const body={id:selected.id,revision:selected.revision,action:type};
  if(type==='save')body.content=panel.querySelector('#file-content').value;
  if(type==='restore')body.backup=panel.querySelector('#file-version').value;
  panel.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{const r=await fetch('/api/files',{method:'POST',headers:{'Content-Type':'application/json','X-Savehaven-Token':state.token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error);await load();if(container.contains(panel))draw(d.message+'.');}
  catch(e){panel.querySelector('#file-message').textContent=e.message;panel.querySelectorAll('button').forEach(b=>b.disabled=false);}
 }
 panel.querySelector('#file-save').onclick=()=>action('save');panel.querySelector('#file-backup').onclick=()=>action('backup');panel.querySelector('#file-restore').onclick=()=>action('restore');
 }
 try{await load();if(document.querySelector('#breadcrumb')?.textContent==='Sandbox files')draw();}catch(e){container.innerHTML=`<div class="card"><h3>Local file manager unavailable</h3><p>${esc(e.message)}. Start the updated local launcher to manage sandbox files.</p></div>`;}
}
