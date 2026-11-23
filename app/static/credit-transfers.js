/** Transfer personal interview credits with a stable retry key and private receipts. */
import { api, state } from './api.js?v=20261122-session-guard-v1';
import { $, el, button, confirmAction, notify, dateTime, badge } from './ui.js?v=20261114-ui-v17';
import { learningDialog, pagination } from './training-ui.js?v=20261121-question-markdown-v1';
let generation=0,page=1;
export function clearTransfers(){generation++;page=1;for(const d of document.querySelectorAll('dialog.transfer-dialog'))d.close();}
export async function refreshTransfers(profile,refreshProfile){
  const request=++generation,token=state.token;
  const result=await api(`/profile/transfers?page=${page}`);
  if(request!==generation||token!==state.token||$('profile').hidden)return;
  const root=$('profileTransfers');root.replaceChildren();
  const head=el('div','','transfer-heading');
  const title=el('div');title.append(el('span','SHARE YOUR NEXT STEP','eyebrow'),el('h2','积分转赠'),el('p','把暂时用不到的积分，送给一起备考的同学。','muted'));
  head.append(title);
  if(!profile.is_admin){
    const control=button('赠送积分',()=>transferDialog(profile,refreshProfile),'button primary');
    control.disabled=profile.points<1;head.append(control);
  }
  root.append(head);
  if(!profile.is_admin){
    const balance=el('div','','transfer-balance');
    balance.append(el('span','可转赠余额','transfer-balance-label'),el('strong',`${profile.points} 积分`,'transfer-balance-value'));
    if(profile.points<1)balance.append(el('p','先通过签到、榜单奖励或卡密兑换获得积分，即可转赠给其他用户。','transfer-balance-hint'));
    else balance.append(el('p','转赠不收费，成功后无法撤回。','transfer-balance-hint'));
    root.append(balance);
  }else root.append(el('p','以下为与你有关的积分转赠记录。','muted transfer-admin-note'));
  const historyHeading=el('div','','transfer-history-heading');
  historyHeading.append(el('h3','转赠记录'),el('span',`${result.total} 笔`,'transfer-history-count'));
  root.append(historyHeading);
  if(!result.items.length)root.append(el('p','暂无转赠记录','muted transfer-empty-history'));
  for(const item of result.items){
    const row=el('article','','redemption-record');const info=el('div');
    info.append(el('strong',`${item.direction==='out'?'转赠给':'收到来自'} ${item.other_username}`),el('p',dateTime(item.created)));
    row.append(info,badge(`${item.direction==='out'?'−':'+'}${item.credits} ${item.currency === 'credits' ? '次' : '积分'}`,item.direction==='out'?'gray':'green'));root.append(row);
  }pagination(root,result,async value=>{page=value;await refreshTransfers(profile,refreshProfile);});
  root.hidden=false;
}
function transferDialog(profile,refreshProfile){
  const {dialog,body,footer}=learningDialog('转赠积分');dialog.classList.add('transfer-dialog');
  const token=state.token,key=generation;
  const form=el('form');form.id=`transfer-form-${crypto.randomUUID()}`;
  const balance=el('div','','transfer-dialog-balance');
  balance.append(el('span','当前可转赠'),el('strong',`${profile.points} 积分`));
  body.append(balance,el('p','输入对方注册时使用的用户名或邮箱。转赠成功后无法撤回。','muted transfer-dialog-description'));
  const fields=el('div','','transfer-fields');
  const receiverField=el('div','','transfer-field');
  const recipient=el('input');recipient.id='transferRecipient';recipient.required=true;recipient.autocomplete='off';recipient.maxLength=1000;recipient.placeholder='输入用户名或邮箱';
  const receiverLabel=el('label','接收人');receiverLabel.htmlFor=recipient.id;
  receiverField.append(receiverLabel,recipient,el('small','仅支持已注册的普通用户','muted'));
  const amount=el('input');amount.id='transferAmount';amount.type='number';amount.min='1';amount.max=String(profile.points);amount.step='1';amount.value='1';amount.required=true;
  const amountField=el('div','','transfer-field');
  const amountLabel=el('label','转赠积分');amountLabel.htmlFor=amount.id;
  amountField.append(amountLabel,amount,el('small',`最多 ${profile.points} 积分`,'muted'));
  const error=el('p','','form-error');error.setAttribute('role','alert');error.hidden=true;
  fields.append(receiverField,amountField);form.append(fields,error);body.append(form);
  const submit=el('button','确认转赠','button primary');submit.type='submit';submit.setAttribute('form',form.id);
  footer.append(button('取消',()=>dialog.close()),submit);
  let last='',requestKey=crypto.randomUUID();
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submit.disabled)return;submit.disabled=true;error.textContent='';error.hidden=true;
    try{
      const payload={recipient:recipient.value,credits:Number(amount.value)};
      if(!await confirmAction(`向「${payload.recipient}」转赠 ${payload.credits} 积分，成功后不可撤回。`,{title:'确认接收人与积分',confirmText:'确认转赠'}))return;
      if(!dialog.open||token!==state.token||key!==generation)return;
      const identity=JSON.stringify(payload);if(last&&last!==identity)requestKey=crypto.randomUUID();last=identity;
      const result=await api('/profile/transfers',{method:'POST',body:JSON.stringify({...payload,idempotency_key:requestKey})});
      if(!dialog.open||token!==state.token||key!==generation)return;
      dialog.close();notify(result.already_transferred?'这笔转赠已完成，记录已更新':`已向 ${result.recipient} 转赠 ${result.credits} 积分`);await refreshProfile();
    }catch(failure){if(dialog.isConnected){error.textContent=failure.message;error.hidden=false;}}
    finally{submit.disabled=false;}
  });
}
