/** Training-only administration; submission review never lists private drafts. */
import { api, state } from './api.js?v=20261114-ui-v17';
import { $, el, button, emptyState, notify, badge, requestText } from './ui.js?v=20261114-ui-v17';
import { selectField, chapterNames, pagination, questionEditor, questionPreview, clearLearningMedia } from './training-ui.js?v=20261121-question-markdown-v1';
let listRequest=0;
let generation=0, settings=null, tab='pending', page=1, query='', collection='', section='';
function live(key,token) { return key===generation && token===state.token && !$('trainingAdmin').hidden; }
export function clearTrainingAdmin() { generation++; settings=null; clearLearningMedia(); $('trainingAdminContent')?.replaceChildren(); }
export async function refreshTrainingAdmin() {
  const key=++generation,token=state.token;
  const value=await api('/admin/training/settings');
  if(!live(key,token))return;settings=value;render();await list();
}
function render() {
  listRequest++;
  const root=$('trainingAdminContent');root.replaceChildren();
  const head=el('div','','page-heading');const title=el('div');title.append(el('span','DAILY PRACTICE','eyebrow'),el('h1','训练题库'),el('p','维护参考答案，认真对待每一份分享。','muted'));
  if(tab==='public')head.append(button('新增公开题',()=>questionEditor(settings.collections,null,async data=>{await api('/admin/training/questions',{method:'POST',body:JSON.stringify(data)});await refreshSavedQuestions('公开训练题已保存');},true,section||'interview',collection),'button primary'));
  root.append(head);
  const tabs=el('div','','learning-tabs');
  for(const [value,label] of [['pending','投稿审核'],['public','公开题库'],['rewards','打卡奖励'],['contribution','投稿奖励'],['settings','训练设置']]) {
    const control=button(label,async()=>{tab=value;page=1;render();await list();},`button ${tab===value?'primary':'quiet'}`);control.setAttribute('aria-pressed',String(tab===value));tabs.append(control);
  }root.append(tabs);
  if(tab==='settings'){renderSettings(root);return;}
  if(tab==='contribution'){renderContribution(root);return;}
  if(tab!=='rewards'){
    const filters=el('form','','learning-filters learning-admin-filters');
    const chapter=selectField('篇章筛选',[['','全部篇章'],...Object.entries(chapterNames)],section);
    const c=selectField('题目集合',[['','全部集合'],...settings.collections.filter(c=>!section||c.section_id===section).map(c=>[c.id,`${chapterNames[c.section_id]} · ${c.name}`])],collection);
    chapter.input.addEventListener('change',async()=>{section=chapter.input.value;collection='';page=1;render();await list();});
    const input=el('input');input.type='search';input.placeholder='按题干搜索';input.value=query;input.setAttribute('aria-label','搜索训练题目');
    const search=button('查询',async()=>{query=input.value.trim();collection=c.input.value;page=1;await list();});
    c.input.addEventListener('change',()=>{collection=c.input.value;page=1;search.click();});
    filters.addEventListener('submit',e=>{e.preventDefault();search.click();});filters.append(chapter.wrap,c.wrap,input,search);root.append(filters);
    root.append(el('p',tab==='pending'?'只有用户主动提交的内容才会出现在这里；通过后才对所有用户可见。':'训练题库独立于模拟面试题库，修改不会影响已有面试记录。','muted'));
  }
  const listNode=el('div','','learning-list');listNode.id='trainingAdminList';root.append(listNode);
}
async function refreshSavedQuestions(message) {
  notify(message);
  try { await list(); }
  catch (error) { notify(`题目已保存，但列表刷新失败：${error.message}。请刷新列表查看。`, 'error'); }
}
async function list() {
  if(tab==='settings'||tab==='contribution'||$('trainingAdmin').hidden||!state.user?.is_admin)return;
  const request=++listRequest;
  const key=generation,token=state.token,current=tab;
  const params=new URLSearchParams({section_id:section,page,status:tab,collection_id:collection,q:query});
  const result=await api(tab==='rewards'?`/admin/training/rewards?page=${page}`:`/admin/training/questions?${params}`);
  if(!live(key,token)||current!==tab||request!==listRequest)return;
  const root=$('trainingAdminList');if(!root)return;root.replaceChildren();
  root.append(el('p',`共 ${result.total} 条`,'muted'));
  if(!result.items.length){
    const empty=tab==='pending'
      ?emptyState('当前没有待审核投稿','用户提交题目后会显示在这里；审核通过的题目会进入公开题库。','◇')
      :tab==='rewards'
        ?emptyState('暂无打卡奖励记录','用户达到奖励条件后，发放记录会显示在这里。','◇')
        :emptyState('没有找到匹配的题目','调整篇章、题目集合或搜索词，也可以新增公开题目。','◇');
    root.append(empty);
  }
  for(const item of result.items){
    const row=el('article','','learning-list-item');const info=el('div'),actions=el('div','','learning-list-actions');
    if(tab==='rewards'){
      info.append(el('h3',item.username),el('p',`${item.date} · 连续打卡 ${item.streak} 天`,'muted'));actions.append(badge(`+${item.credits} 积分`,'green'));
    }else{
      info.append(badge(item.collection_name),button(item.question,()=>questionPreview(item),`learning-question-link ${item.category === 'translation' ? 'learning-passage-link' : ''}`),el('p',`贡献者：${item.owner_name} · ${item.active?'启用':'已停用'}`,'muted'));
      if(item.category==='translation')info.append(el('p','点击原文查看完整内容与参考译文','muted'));
      if(tab==='pending'){
        actions.append(button('查看题目与答案',()=>questionPreview(item)),button('通过',async()=>{await api(`/admin/training/questions/${item.id}/review`,{method:'POST',body:JSON.stringify({version:item.version,approve:true,reason:''})});notify('审核通过，题目已公开');await list();},'button primary'),button('驳回',async()=>{
          const reason=await requestText('驳回投稿','',{message:'请说明需要补充或修改的内容，用户将看到这条意见。',confirmText:'确认驳回',input:{label:'驳回原因',value:'',maxLength:2000}});
          if(!reason)return;
          await api(`/admin/training/questions/${item.id}/review`,{method:'POST',body:JSON.stringify({version:item.version,approve:false,reason})});notify('已反馈审核意见');await list();
        },'button quiet'));
      }else{
        if(item.official)actions.append(button(item.category==='translation'?'编辑译文':'编辑答案',()=>questionEditor(settings.collections,item,async data=>{await api(`/admin/training/questions/${item.id}`,{method:'PATCH',body:JSON.stringify({...data,version:item.version,active:item.active})});await refreshSavedQuestions('题目与答案已更新');},true,section||'interview')));
        actions.append(button(item.active?'停用题目':'启用题目',async()=>{await api(`/admin/training/questions/${item.id}/active`,{method:'POST',body:JSON.stringify({version:item.version,active:!item.active})});await list();},'button secondary'));
      }
    }row.append(info,actions);root.append(row);
  }pagination(root,result,async value=>{page=value;await list();});
}

async function renderContribution(root) {
  const value=await api('/admin/training/contribution-rewards');
  const panel=el('section','','panel contribution-admin');
  const heading=el('div');heading.append(el('span','CONTRIBUTION REWARDS','eyebrow'),el('h2','题库投稿奖励'),el('p','仅统计规则生效后审核通过并公开的普通用户题目。规则变更不重算历史投稿。','muted'));
  const form=el('form','','contribution-policy-form');
  const questions=el('input');questions.type='number';questions.min='1';questions.max='10000';questions.required=true;questions.value=String(value.policy.questions_per_reward);
  const credits=el('input');credits.type='number';credits.min='1';credits.max='1000000';credits.required=true;credits.value=String(value.policy.credits_per_reward);
  for(const [text,input] of [['审核通过题数',questions],['奖励积分',credits]]){const label=el('label',text);label.append(input);form.append(label);}
  form.append(button('保存新规则',async()=>{
    await api('/admin/training/contribution-rewards',{method:'PUT',body:JSON.stringify({questions_per_reward:Number(questions.value),credits_per_reward:Number(credits.value)})});
    notify('投稿奖励新规则已生效');await refreshTrainingAdmin();
  },'button primary'));
  panel.append(heading,form,el('p','当前统计 ' + value.total + ' 个普通用户 · 规则版本 ' + value.policy.id,'muted'));
  const table=el('div','','contribution-admin-list');
  for(const item of value.items){const row=el('div','','contribution-admin-row');row.append(el('strong',item.username),el('span',item.approved_count+' 道通过'),el('span','累计 +'+item.credits_earned+' 积分'));table.append(row);}
  panel.append(table);root.append(panel);
}
function renderSettings(root){
  const panel=el('section','','learning-setup');panel.append(el('h2','每日目标与练习长度'),el('p','目标修改对下一个自然日或当天尚未开始训练的用户生效，已开始用户保留当日目标。','muted'));
  const form=el('form','','learning-filters learning-settings-form');
  const fields={};
  for(const [key,label,max]of [['daily_goal','每日不同题目标',100],['round_size','默认每轮题数',50]]){
    const wrap=el('label','','learning-field'),input=el('input');input.type='number';input.min='1';input.max=String(max);input.required=true;input.value=String(settings[key]);wrap.append(el('span',label),input);form.append(wrap);fields[key]=input;
  }
  const save=el('button','保存设置','button primary');save.type='submit';form.append(save);
  const error=el('p','','form-error');error.setAttribute('role','alert');
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(save.disabled)return;save.disabled=true;error.textContent='';
    const key=generation,token=state.token;
    try{const result=await api('/admin/training/settings',{method:'PATCH',body:JSON.stringify({daily_goal:Number(fields.daily_goal.value),round_size:Number(fields.round_size.value)})});if(live(key,token)){settings=result;notify('训练设置已保存');}}
    catch(failure){if(form.isConnected)error.textContent=failure.message;}finally{save.disabled=false;}
  });panel.append(form,error);root.append(panel);
  const collections=el('section','','learning-setup learning-collections-panel');collections.append(el('h2','训练集合'),el('p',`单批导入上限 ${settings.max_import_items} 道，文件最大 ${Math.round(settings.max_import_bytes/1024)} KB。`,'muted'));
  const list=el('div','','learning-collections-list');
  for(const item of settings.collections){const row=el('div','','learning-setting-row');row.append(el('span',`${chapterNames[item.section_id]} · ${item.name}`),button(item.active?'已启用 · 点击停用':'已停用 · 点击启用',async()=>{await api(`/admin/training/collections/${item.id}`,{method:'PATCH',body:JSON.stringify({active:!item.active})});item.active=!item.active;render();},'button secondary'));list.append(row);}
  collections.append(list);root.append(collections);
}
