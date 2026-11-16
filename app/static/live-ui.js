/** Shared classroom form, file and dialog primitives. */
import {api,state} from './api.js?v=20261114-ui-v17';
import {el,button,notify,run,confirmAction} from './ui.js?v=20261114-ui-v17';
export {el,button,notify,confirmAction};
export function field(label,control,hint='') {
  const group=el('label','','live-field');group.append(el('span',label),control);
  if(hint)group.append(el('small',hint));return group;
}
export function input(value='',type='text') { const node=el('input');node.type=type;node.value=value;return node; }
export function textArea(value='') { const node=el('textarea');node.value=value;node.rows=4;return node; }
export function modal(title,description='') {
  const dialog=el('dialog','','live-dialog account-dialog');
  const head=el('div','','dialog-header');const heading=el('h2',title);heading.id=`liveDialog-${crypto.randomUUID()}`;
  dialog.setAttribute('aria-labelledby',heading.id);
  const close=button('×',()=>dialog.close(),'icon-button');close.setAttribute('aria-label','关闭');head.append(heading,close);
  const body=el('div','','dialog-body');if(description)body.append(el('p',description,'live-helper'));
  const footer=el('div','','dialog-footer');const cancel=button('取消',()=>dialog.close());footer.append(cancel);
  dialog.append(head,body,footer);dialog.dataset.liveOwned='true';(document.fullscreenElement||document.body).append(dialog);
  const previous=document.activeElement;
  dialog.addEventListener('close',()=>{dialog.dispatchEvent(new Event('live-dispose'));dialog.remove();if(previous?.isConnected)previous.focus();},{once:true});
  dialog.showModal();return {dialog,body,footer};
}
/** Send authenticated files with bounded server-side checks and visible upload progress. */
export function uploadFile(url,file,onProgress=()=>{}) {
  return new Promise((resolve,reject)=>{
    const request=new XMLHttpRequest();request.open('POST',`/api${url}`);request.setRequestHeader('Authorization',`Bearer ${state.token}`);request.timeout=180000;
    request.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100));};
    request.onerror=()=>reject(new Error('上传连接中断，请重试'));request.ontimeout=()=>reject(new Error('上传超时，请重试'));
    request.onload=()=>{let result;try{result=JSON.parse(request.responseText);}catch(error){reject(new Error('无法读取上传结果，请刷新后确认'));return;}
      if(request.status>=200&&request.status<300)resolve(result);else reject(new Error(typeof result.detail==='string'?result.detail:'上传失败，请检查文件类型和大小'));};
    const form=new FormData();form.append('file',file);request.send(form);
  });
}
export async function privateDownload(path,name) {
  const response=await fetch(`/api/live${path}`,{headers:{Authorization:`Bearer ${state.token}`}});
  if(!response.ok)throw new Error('文件读取失败，请刷新后重试');
  const url=URL.createObjectURL(await response.blob());const link=el('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
export function materialList(target,lesson,{canManage=false,refresh=()=>{}}={}) {
  target.replaceChildren();
  if(!lesson.materials?.length)target.append(el('p','本节课暂无资料，上传后会保存在这里。','live-helper live-empty-note'));
  for(const material of lesson.materials||[]){
    const row=el('div','','live-material');const icon=el('span',/\.pdf$/i.test(material.name)?'PDF':'FILE','live-file-icon');
    const info=el('div');info.append(el('strong',material.name),el('small',`${(material.size/1024/1024).toFixed(1)} MB`));
    const download=button('下载',()=>privateDownload(`/materials/${material.id}/file`,material.name),'button secondary live-small');
    row.append(icon,info,download);
    if(canManage)row.append(button('删除',async()=>{if(await confirmAction(`删除资料“${material.name}”？`,{danger:true,confirmText:'删除资料'})){await api(`/live/materials/${material.id}`,{method:'DELETE'});await refresh();}},'text-button live-small'));
    target.append(row);
  }
  if(canManage){
    const picker=el('input');picker.type='file';picker.hidden=true;
    const status=el('span','','live-helper');status.setAttribute('role','status');
    picker.addEventListener('change',()=>{const file=picker.files[0];if(!file)return;void run(async()=>{upload.disabled=true;target.dataset.uploading='true';status.textContent='正在上传…';try{await uploadFile(`/live/lessons/${lesson.id}/materials`,file,percent=>status.textContent=`正在上传 ${percent}%`);if(target.isConnected)await refresh();}finally{delete target.dataset.uploading;upload.disabled=false;picker.value='';status.textContent='';}},upload);});
    const upload=button('＋ 上传课程资料',()=>picker.click(),'button secondary');
    const footer=el('div','','live-upload-actions');footer.append(upload,status,picker);target.append(footer);
  }
}
