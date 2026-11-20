import {spillover} from '../api/spillover.js';
import {table} from '../components/common/table.js';
import {esc,fmt} from '../utils/format.js';
import {download} from '../utils/download.js';

async function renderRun(id){
  const r=await spillover.getRun(id);
  return `<div class="eyebrow">06 / SPILLOVER ARCHIVE · RUN ${r.id}</div>
<h1>${esc(r.name)} <span class="badge ${r.status==='completed'?'ok':''}">${esc(r.status)}</span></h1>
<div class="checksum">封存依据 SHA256 ${esc(r.checksum)}</div>
<p>批次 ${esc(r.snapshot.batch_code)} · ${esc(r.created_at)} · 来源文件：${esc(Object.entries(r.snapshot.sources).map(([k,v])=>k+'='+v).join('；'))}</p>
${r.status==='failed'?`<div class="error">计算失败：${esc(r.error)}。补齐/更正开放批次资料后重新创建运行；已封存批次的更正不会改变本运行依据。</div>`:
r.result?`<section class="result-intro"><strong>${esc(r.result.interpretation)}</strong>
<div class="method-note"><strong>适用范围</strong>：${esc(r.result.applicability)}</div>
<p>${esc(r.result.caveat)}</p>
<div class="method-note"><strong>自检（孤立受众与全员相连）</strong>：${r.result.self_check.通过?'通过':'未通过'}，共 ${r.result.self_check.检查项数} 项。${esc(r.result.self_check.说明)}</div>
</section>
<h2>核心数值</h2>${table(['业务指标','计算值'],Object.entries(r.result.metrics).map(([k,v])=>[k,fmt(v)]))}
<h2>剔除人员与原因</h2>${table(['人员','原因'],r.result.excluded_detail.map(x=>[x.人员,x.原因]))}
<h2>${esc(r.result.table_title)}</h2>${table(r.result.columns,r.result.rows)}
<div class="toolbar"><button id="sp-export">下载外溢核算 CSV</button><a class="button secondary" href="#spillover">返回外溢工作席 →</a></div>`:
'<p class="method-note">任务正在队列中，此页每2秒更新。</p>'}
<details><summary>本次封存的三份资料快照</summary><pre>${esc(JSON.stringify(r.snapshot,null,2))}</pre></details>`;
}

export async function render(seg){
  if(!seg)return `<h1>留白外溢结果档案</h1><p>从外溢工作席选择一次运行查看封存依据、适用范围与逐人权重。</p>`;
  if(seg.startsWith('sub=')){
    const subId=+seg.slice(4);
    const runs=await spillover.runs();
    const mine=runs.filter(r=>r.submission_id===subId);
    return `<h1>批次 #${subId} 的运行</h1>${table(['运行','状态','点击差','SHA256'],mine.map(r=>[
      {html:`<a href="#spillover-result/${r.id}">#${r.id} ${esc(r.name)}</a>`},r.status,
      r.result?.metrics?.['点击差(有联系人-无联系人)']??'—',r.checksum.slice(0,12)]))}`;
  }
  return renderRun(+seg);
}

export function bind(){
  const button=document.getElementById('sp-export');
  if(button)button.onclick=async()=>{
    try{
      const id=Number(location.hash.split('/')[1]);
      download(await spillover.exportRun(id),'spillover-'+id+'.csv');
    }catch(e){document.getElementById('notice').textContent=e.message;}
  };
}
