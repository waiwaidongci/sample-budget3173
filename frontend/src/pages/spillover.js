import {DOMAIN} from '../constants/domain.js';
import {store,load} from '../stores/research.js';
import {spillover} from '../api/spillover.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {esc} from '../utils/format.js';
import {bindForm} from '../hooks/forms.js';

const SP=DOMAIN.spillover;
const local={subs:[],corrs:[],runs:[]};

async function refreshAll(){
  const sid=store.studyId;
  if(!sid){local.subs=[];local.corrs=[];local.runs=[];return;}
  [local.subs,local.corrs,local.runs]=await Promise.all([
    spillover.submissions(sid),spillover.corrections(sid),spillover.runs(sid)]);
}

function fileBadge(present,label){return `<span class="badge ${present?'ok':'missing'}">${present?'✓':'缺'} ${esc(label)}</span>`;}

export async function render(){
  await load();
  await refreshAll();
  const writable=localStorage.getItem('research-role')!=='viewer';
  const subRows=local.subs.map(s=>[
    {html:`<a href="#spillover-result?sub=${s.id}"><strong>${esc(s.batch_code)}</strong></a>`},
    {html:`<span class="badge ${s.status==='sealed'?'ok':''}">${s.status==='sealed'?'已封存':'开放补交'}</span>`},
    {html:[['roster','名单'],['edges','联系'],['clicks','点击']].map(([k,v])=>fileBadge(s.files_present?.[k],v)).join(' ')},
    s.missing_click_ids?.length?{html:`<span class="badge missing">缺报 ${s.missing_click_ids.length} 人（不算零）</span>`}:'点击齐全',
    s.sealed_run_id?`运行 #${s.sealed_run_id}`:'—',
  ]);
  return `<div class="eyebrow">05 / SPILLOVER WORKSHEET</div>
<h1>${esc(SP.page_label)}：留白人群的已投联系人点击差</h1>
<p class="lead">${esc(SP.note)}</p>
<div class="method-note"><strong>适用范围</strong>：${esc(SP.applicability)}</div>
<div class="toolbar">${studySelect()}</div>

${writable?`<details open><summary>① 新建${esc(SP.batch_label)}</summary>
<form id="sub-form" class="worksheet">
  <label>批次编号（三份资料共用同一编号并发补交）<input name="batch_code" required minlength="1" placeholder="如 SPILL-202611-A"></label>
  <label>说明<input name="note" placeholder="可选"></label>
  <button type="submit">创建批次</button>
</form></details>

<details open><summary>② 三份资料并发补交（只封存齐全的同一批）</summary>
<form id="upload-form" class="worksheet">
  <label>目标批次<select name="batch_code" required>${local.subs.map(s=>`<option value="${esc(s.batch_code)}" ${s.status==='sealed'?'disabled':''}>${esc(s.batch_code)}${s.status==='sealed'?'（已封存）':''}</option>`).join('')}</select></label>
  <label>资料类型<select name="kind" required><option value="roster">原分派名单（列：id,slot；slot=treated/holdout 或 已投/留白）</option><option value="edges">投放前双向联系（列：source,target）</option><option value="clicks">投放前点击（列：id,click；缺报整行省略，不得填零）</option></select></label>
  <label>来源文件名<input name="filename" required placeholder="如 roster-202611.csv"></label>
  <label>选择 CSV 文件<input name="file" type="file" accept=".csv,text/csv" required></label>
  <button type="submit">补交该份资料</button>
</form>
<p class="method-note">同批三份可任意顺序、并发补交；重复补交以最新齐全版本整份替换，封存前不污染历史。</p>
</details>

<details><summary>③ 联系/点击更正（独立封存，重跑不改封存依据）</summary>
<form id="corr-form" class="worksheet">
  <label>目标批次<select name="batch_code" required>${local.subs.map(s=>`<option value="${esc(s.batch_code)}">${esc(s.batch_code)}</option>`).join('')}</select></label>
  <label>人员 id<input name="person_id" required placeholder="如 P007"></label>
  <label>更正类型<select name="corr_kind" id="corr-kind"><option value="edge_add">新增双向联系</option><option value="edge_remove">移除双向联系</option><option value="click">更正点击为指定 0/1</option></select></label>
  <label>来源文件名<input name="source_filename" required placeholder="如 correction-202611-03.csv"></label>
  <div id="edge-fields"><label>联系另一端 id<input name="other_id" placeholder="如 P002"></label></div>
  <div id="click-field" hidden><label>点击值<select name="click_value"><option value="1">1 已点击</option><option value="0">0 未点击</option></select></label></div>
  <button type="submit">另封提交更正</button>
</form>
<p class="method-note">更正始终独立留痕并生成自己的 SHA256；已封存批次的更正标记 rejected_sealed，不并入封存依据，重跑结果不变。</p>
</details>

<details open><summary>④ 封存并运行（原预算照常，无新增预算参数）</summary>
<form id="run-form" class="worksheet">
  <label>选择齐全批次<select name="submission_id" required>${local.subs.map(s=>`<option value="${s.id}" ${s.status==='sealed'?'':''}>${esc(s.batch_code)}${s.status==='sealed'?'（已封存，可重跑）':''}</option>`).join('')}</select></label>
  <label>运行名称<input name="name" required minlength="2" value="${esc(DOMAIN.names[0])} · 留白外溢"></label>
  <button type="submit">封存齐全资料并排队 →</button>
</form></details>`:''}

<h2>批次与齐全度</h2>
${table(['批次','状态','三份资料','点击缺报','封存运行'],subRows)}

<h2>更正留痕（独立封存）</h2>
${table(['编号','人员','内容','来源','状态','SHA256','时间'],local.corrs.map(c=>[c.id,c.person_id,{html:Object.entries(c.payload).map(([k,v])=>`${esc(k)}=${esc(Array.isArray(v)?v.join('↔'):v)}`).join('；')},c.source_filename,{html:`<span class="badge ${c.status==='applied'?'ok':'missing'}">${c.status==='applied'?'并入开放批次':'独立留痕·不并入（已封存/批次或人员无效）'}</span>`},c.checksum.slice(0,12),c.created_at]))}

<h2>外溢运行记录</h2>
${table(['编号 / 运行','状态','适用人数','点击差','复核口径'],local.runs.map(r=>[
  {html:`<a href="#spillover-result/${r.id}">#${r.id} ${esc(r.name)}</a>`},
  r.status,
  r.result?.metrics?.['比较适用人数(两情形概率均为正)']??'—',
  r.result?.metrics?.['点击差(有联系人-无联系人)']??'—',
  r.checksum.slice(0,12),
]))}`;
}

export function bind(refresh){
  const sel=document.getElementById('study-select');if(sel)sel.onchange=()=>{store.studyId=+sel.value;refresh();};
  bindForm('sub-form',async d=>{
    await spillover.createSubmission({study_id:store.studyId,batch_code:d.batch_code,note:d.note||''});
    await refresh();refresh();
  });
  const kindSel=document.getElementById('corr-kind');
  if(kindSel)kindSel.onchange=()=>{
    const isClick=kindSel.value==='click';
    document.getElementById('edge-fields').hidden=isClick;
    document.getElementById('click-field').hidden=!isClick;
  };
  bindForm('corr-form',async d=>{
    let payload;
    if(d.corr_kind==='click')payload={click:+d.click_value};
    else payload={[d.corr_kind]:[d.person_id,d.other_id]};
    await spillover.submitCorrection({study_id:store.studyId,batch_code:d.batch_code,person_id:d.person_id,
      source_filename:d.source_filename,payload});
    await refresh();refresh();
  });
  bindForm('run-form',async d=>{
    const r=await spillover.createRun({study_id:store.studyId,submission_id:+d.submission_id,name:d.name,parameters:{}});
    location.hash='spillover-result/'+r.id;
  });
  const upForm=document.getElementById('upload-form');
  if(upForm)upForm.onsubmit=async e=>{
    e.preventDefault();
    const fd=new FormData(upForm);
    const file=fd.get('file');
    if(!file){document.getElementById('notice').textContent='请选择 CSV 文件';return;}
    const content=await file.text();
    const button=upForm.querySelector('button[type=submit]');button.disabled=true;
    try{
      const state=await spillover.upload({study_id:store.studyId,batch_code:fd.get('batch_code'),
        kind:fd.get('kind'),filename:fd.get('filename'),content});
      document.getElementById('notice').textContent=state.ready_to_seal?'三份资料齐全且点击无缺报，可以封存运行。':'已补交；当前齐全度：'+Object.entries(state.files_present).map(([k,v])=>k+'='+(v?'有':'缺')).join('，')+(state.missing_click_ids.length?`；缺报点击 ${state.missing_click_ids.length} 人（不算零）`:'');
      await refresh();refresh();
    }catch(err){document.getElementById('notice').textContent=err.message;}
    finally{button.disabled=false;}
  };
}
