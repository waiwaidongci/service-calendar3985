import {esc,fmt,time} from '../utils/format.js';import {healthBadge} from './common/health.js';import {REPAIR_STATUS} from '../constants/enums.js';import {store} from '../stores/business.js';

export function integrityPanel(run,d){
 const role=store.session?.role;const isAdmin=role==='admin';const canCheck=role==='admin'||role==='analyst';
 const jobs=(d.repair_jobs||[]).filter(j=>j.run_id===run.id);
 return `<section class="integrity">
 <h2>自检 · 修复 · 复核轨迹</h2>
 <p class="health-line">当前版本 <b>v${run.result_version||1}</b> · 状态 ${healthBadge(run.health)} · 修复轮次 ${run.repair_seq||0}</p>
 <p class="health-detail">${esc(run.health_detail||'尚未自检')}</p>
 <div class="integrity-actions">
  ${canCheck?`<button class="act-selfcheck" data-id="${run.id}">执行自检</button>`:''}
  ${isAdmin?`<button class="act-repair" data-id="${run.id}">按冻结底稿修复</button>
  <button class="act-tamper-result" data-id="${run.id}">模拟结果损坏</button>
  <button class="act-tamper-source" data-id="${run.id}">模拟底稿受损</button>`:''}
 </div>
 <details class="lazy" data-kind="versions" data-id="${run.id}"><summary>结果版本与原子切换记录</summary><div class="lazy-body">点击展开加载</div></details>
 <details class="lazy" data-kind="diff" data-id="${run.id}"><summary>版本差异（v1 ↔ 当前）</summary><div class="lazy-body">点击展开加载</div></details>
 <details class="lazy" data-kind="events" data-id="${run.id}"><summary>先后次序事件流水（可追查）</summary><div class="lazy-body">点击展开加载</div></details>
 <details class="lazy" data-kind="reviews" data-id="${run.id}"><summary>复核与撤销记录</summary><div class="lazy-body">点击展开加载</div></details>
 ${jobs.length?`<details open><summary>修复任务（${jobs.length}）</summary><div class="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>损坏类型</th><th>版本</th><th>尝试</th><th>原因</th></tr></thead><tbody>${jobs.map(j=>`<tr><td>#${j.id}</td><td>${esc(REPAIR_STATUS[j.status]||j.status)}</td><td>${esc(j.damage||'')}</td><td>v${j.from_version||1}→${j.to_version?('v'+j.to_version):'—'}</td><td>${j.attempts||0}</td><td>${esc(j.last_error||j.reason||'')}</td></tr>`).join('')}</tbody></table></div></details>`:''}
 </section>`;
}

export function renderVersions(rows){
 if(!rows.length)return '<p class="empty">暂无版本记录。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>版本</th><th>类型</th><th>结果校验和</th><th>底稿校验和</th><th>操作者</th><th>说明</th><th>时间</th></tr></thead><tbody>'+
 rows.map(v=>`<tr><td>v${v.version}</td><td>${esc(v.kind)}</td><td class="mono">${esc((v.result_checksum||'').slice(0,16))}…</td><td class="mono">${esc((v.source_checksum||'').slice(0,16))}…</td><td>${esc(v.actor)}</td><td>${esc(v.note||'')}</td><td>${time(v.created)}</td></tr>`).join('')+'</tbody></table></div>';
}

export function renderEvents(rows){
 if(!rows.length)return '<p class="empty">暂无事件。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>序号</th><th>时间</th><th>操作者</th><th>动作</th><th>明细</th></tr></thead><tbody>'+
 rows.map(e=>`<tr><td>${e.seq}</td><td>${time(e.at)}</td><td>${esc(e.actor)}</td><td class="mono">${esc(e.action)}</td><td>${esc(e.detail)}</td></tr>`).join('')+'</tbody></table></div>';
}

export function renderReviews(rows){
 if(!rows.length)return '<p class="empty">暂无复核记录。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>版本</th><th>状态</th><th>复核人</th><th>说明</th><th>时间</th></tr></thead><tbody>'+
 rows.map(v=>`<tr><td>v${v.version}</td><td>${v.state==='active'?'<b class="tone-ok">有效</b>':'<span class="tone-bad">已撤销</span>'}</td><td>${esc(v.actor)}</td><td>${esc(v.note)}</td><td>${time(v.created)}</td></tr>`).join('')+'</tbody></table></div>';
}

export function renderDiff(d){
 const sum=(s)=>s?Object.entries(s).map(([k,v])=>`${esc(k)}: ${fmt(v)}`).join(' · '):'';
 const rows=d.row_changes||[];
 return `<div class="diff-box"><p><b>旧汇总：</b>${sum(d.summary_old)}</p><p><b>新汇总：</b>${sum(d.summary_new)}</p></div>`+
  (rows.length?'<div class="table-wrap"><table><thead><tr><th>分组</th><th>变化</th><th>字段</th><th>旧值</th><th>新值</th></tr></thead><tbody>'+
  rows.flatMap(c=>{
   const key=(c.key||[]).join(' / ');
   if(c.change!=='变更')return [`<tr><td>${esc(key)}</td><td>${esc(c.change)}</td><td colspan="3">${esc(c.change==='新增'?'新增分组':'删除分组')}</td></tr>`];
   return Object.entries(c.fields).map(([f,vv])=>`<tr><td>${esc(key)}</td><td>变更</td><td>${esc(f)}</td><td class="tone-bad">${fmt(vv.old)}</td><td class="tone-ok">${fmt(vv.new)}</td></tr>`);
  }).join('')+'</tbody></table></div>':'<p class="empty">两个版本的透视行无差异。</p>');
}
