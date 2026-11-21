/** Standalone course authoring with live safe preview, imports and session drafts. */
import {el,button,confirmAction} from './ui.js?v=20261114-ui-v17';
import {createMarkdownPreview,readMarkdownFile} from './course-markdown-model.mjs?v=20261121-v1';

export function mountMarkdownWorkspace({target,course,lesson,asset,source,userId,compile,render,uploadImage,save,onBack}) {
  const shell=el('section','','course-markdown-workspace');
  const header=el('header','','course-writer-header');
  const heading=el('div','','course-heading-copy');heading.append(el('span',`${course.title} / ${lesson.title}`,'eyebrow'),el('h1',asset?'编辑课程正文':'编写课程正文'));
  const actions=el('div','','course-writer-actions');
  const status=el('p','','course-writer-status');status.setAttribute('role','status');
  const name=el('input');name.type='text';name.maxLength=180;name.id='course-writer-name';name.placeholder='文档名称';name.value=asset?asset.original_name.replace(/\.md$/i,''):lesson.title;
  const titleField=el('div','','course-writer-title');const label=el('label','文档名称');label.htmlFor=name.id;titleField.append(label,name,el('span','.md','course-writer-extension'));
  const toolbar=el('div','','course-writer-toolbar');
  const modes=el('div','','course-writer-modes');modes.setAttribute('role','group');modes.setAttribute('aria-label','编辑器布局');
  const sourcePanel=el('section','','course-writer-source');const sourceHead=el('div','','course-writer-panel-heading');sourceHead.append(el('label','Markdown 源码'));
  const text=el('textarea');text.id='course-writer-source';text.spellcheck=false;text.value=source;text.placeholder='# 课时标题\n\n从这里开始编写，也可以导入已有的 .md 文件…';text.setAttribute('aria-label','Markdown 源码');sourceHead.firstChild.htmlFor=text.id;
  const counter=el('span','','course-writer-counter');sourceHead.append(counter);sourcePanel.append(sourceHead,text);
  const previewPanel=el('section','','course-writer-preview');const previewHead=el('div','','course-writer-panel-heading');const previewStatus=el('span','实时更新','course-writer-counter');previewHead.append(el('h2','效果预览'),previewStatus);
  const previewBody=el('div','','course-reading-body');previewPanel.append(previewHead,previewBody);previewBody.setAttribute('aria-label','Markdown 效果预览');
  const panes=el('div','','course-writer-panes');panes.append(sourcePanel,previewPanel);
  const message=(value,error=false)=>{status.textContent=value;status.classList.toggle('is-error',error);};
  const queue=createMarkdownPreview({compile,pending:()=>{previewStatus.textContent='正在编译…';},show:html=>{previewStatus.textContent='已更新';previewPanel.classList.remove('is-stale');if(html)render(previewBody,html);else previewBody.replaceChildren(el('p','开始编写后，效果会实时显示在这里。','course-writer-empty'));},failed:error=>{previewStatus.textContent='预览未更新';previewPanel.classList.add('is-stale');message(`${error.message}；正文已保留，可继续编辑。`,true);}});
  let disposed=false,busy=false,importing=false,uploading=false,saveSucceeded=false;
  const draftKey=`course-markdown-draft:${userId}:${lesson.id}:${asset?.id||'new'}`;
  const initial={name:name.value,text:source};
  try{
    const draft=JSON.parse(sessionStorage.getItem(draftKey)||'null');
    if(draft&&draft.base===source&&typeof draft.name==='string'&&typeof draft.text==='string'){
      name.value=draft.name;text.value=draft.text;message('已恢复本标签页中未提交的草稿。');
    }
  }catch(error){message('浏览器草稿存储不可用，请及时保存正文。',true);}
  const dirty=()=>name.value!==initial.name||text.value!==initial.text;
  const persist=()=>{
    if(saveSucceeded)return;
    try{if(dirty())sessionStorage.setItem(draftKey,JSON.stringify({base:source,name:name.value,text:text.value}));else sessionStorage.removeItem(draftKey);}
    catch(error){message('草稿未能暂存，请保存正文后再离开。',true);}
  };
  const changed=()=>{persist();counter.textContent=`${text.value.length.toLocaleString()} 字符`;queue.update(text.value);};
  const updateBusy=()=>{text.readOnly=busy||uploading||importing;name.disabled=busy;saveButton.disabled=busy||uploading||importing;importButton.disabled=busy||uploading||importing;imageButton.disabled=busy||uploading||importing;back.disabled=busy||uploading||importing;};
  const back=button('返回课时管理',async()=>{
    if(dirty()&&!await confirmAction('正文尚未提交到课程，草稿会暂存在当前标签页。确认返回课时管理吗？',{title:'离开正文编辑？',confirmText:'保留草稿并返回'}))return;
    persist();await onBack();
  },'button secondary');
  const saveButton=button(asset?'保存修改':'保存到课时',async()=>{
    const documentName=name.value.trim().replace(/[\\/]+/g,'-').replace(/\.md$/i,'');
    if(!documentName){message('请填写文档名称。',true);name.focus();return;}
    if(!text.value.trim()){message('请输入正文或导入一个 .md 文件。',true);text.focus();return;}
    busy=true;updateBusy();message('正在保存正文…');
    try{
      await save({name:documentName,markdown:text.value});
      saveSucceeded=true;try{sessionStorage.removeItem(draftKey);}catch(error){/* Saved content is already durable on the server. */}
      if(!disposed)await onBack();
    }catch(error){if(!disposed)message(`保存失败：${error.message}，正文和草稿均已保留。`,true);}
    finally{busy=false;updateBusy();}
  },'button primary');
  actions.append(back,saveButton);header.append(heading,actions);
  const filePicker=el('input');filePicker.type='file';filePicker.accept='.md,text/markdown';filePicker.hidden=true;
  const importButton=button('导入 MD 文件',()=>filePicker.click(),'button secondary');
  filePicker.addEventListener('change',async()=>{
    const file=filePicker.files?.[0];filePicker.value='';if(!file)return;
    importing=true;updateBusy();
    try{
      const imported=await readMarkdownFile(file);if(disposed)return;
      if(text.value.trim()&&!await confirmAction('导入后将替换编辑器中的正文，确认使用这个 Markdown 文件吗？',{title:'替换当前正文？',confirmText:'导入文件'}))return;
      if(disposed)return;name.value=imported.name;text.value=imported.text;changed();message(`已导入 ${file.name}，检查预览后保存到课时。`);
    }catch(error){if(!disposed)message(error.message,true);}
    finally{importing=false;updateBusy();}
  });
  const insertImages=async files=>{
    const images=[...files].filter(file=>file.type.startsWith('image/'));if(!images.length||busy||uploading||importing)return;
    uploading=true;updateBusy();const start=text.selectionStart,end=text.selectionEnd,links=[];
    try{
      for(const [index,file] of images.entries()){
        message(`正在上传图片 ${index+1}/${images.length}…`);
        const result=await uploadImage(file);if(disposed)return;links.push(`![图片](${result.url})`);
      }
      text.setRangeText(`\n\n${links.join('\n\n')}\n`,start,end,'end');changed();message('图片已插入正文。');
    }catch(error){if(!disposed)message(`图片上传失败：${error.message}，请重试。`,true);}
    finally{uploading=false;updateBusy();}
  };
  text.addEventListener('paste',event=>{const images=[...(event.clipboardData?.files||[])].filter(file=>file.type.startsWith('image/'));if(images.length){event.preventDefault();void insertImages(images);}});
  const imagePicker=el('input');imagePicker.type='file';imagePicker.accept='image/png,image/jpeg,image/webp';imagePicker.multiple=true;imagePicker.hidden=true;
  const imageButton=button('插入图片',()=>imagePicker.click(),'button secondary');imagePicker.addEventListener('change',()=>{void insertImages(imagePicker.files||[]);imagePicker.value='';});
  const modeButtons=[];
  for(const [mode,label] of [['split','双栏'],['source','编辑'],['preview','预览']]){
    const control=button(label,()=>setMode(mode),'course-writer-mode');control.dataset.mode=mode;modeButtons.push(control);modes.append(control);
  }
  function setMode(mode){shell.dataset.mode=mode;for(const control of modeButtons)control.setAttribute('aria-pressed',String(control.dataset.mode===mode));}
  setMode(window.matchMedia('(max-width:760px)').matches?'source':'split');
  const imports=el('div','','course-writer-imports');imports.append(importButton,imageButton,filePicker,imagePicker);
  toolbar.append(imports,modes);
  const hint=el('p','支持标题、列表、表格、代码块和公式；可粘贴图片。草稿仅暂存于当前浏览器标签页，保存后学员才可见。','course-writer-hint');
  text.addEventListener('input',changed);name.addEventListener('input',persist);
  shell.append(header,titleField,toolbar,panes,hint,status);target.replaceChildren(shell);changed();
  return ()=>{persist();disposed=true;queue.dispose();};
}
