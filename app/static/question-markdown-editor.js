/** Shared question editor with debounced safe preview and authenticated image insertion. */
import {api,state} from './api.js?v=20261114-ui-v17';
import {el,button,confirmAction} from './ui.js?v=20261114-ui-v17';
import {createMarkdownPreview,readMarkdownFile} from './course-markdown-model.mjs?v=20261121-v1';
import {appendProblemStatement} from './problem-content.js?v=20261121-question-images-v1';

export function questionMarkdownEditor(text,{onBusy=()=>{}}={}){
  const shell=el('section','','question-md-editor');const toolbar=el('div','','question-md-toolbar');
  const panes=el('div','','question-md-panes');const source=el('div','','question-md-source');const preview=el('div','','question-md-preview');preview.setAttribute('aria-label','Markdown 效果预览');
  const status=el('p','','question-md-status');status.setAttribute('role','status');
  const message=(value,error=false)=>{status.textContent=value;status.classList.toggle('is-error',error);};
  const sessionToken=state.token;
  text.classList.add('question-md-input');text.required=false;
  source.append(text);panes.append(source,preview);
  const modes=el('div','','question-md-modes');modes.setAttribute('role','group');modes.setAttribute('aria-label','Markdown 编辑布局');
  const modeButtons=[];
  const setMode=mode=>{shell.dataset.mode=mode;for(const control of modeButtons)control.setAttribute('aria-pressed',String(control.dataset.mode===mode));};
  for(const [mode,label]of [['source','编辑'],['split','双栏'],['preview','预览']]){
    const control=button(label,()=>setMode(mode),'question-md-mode');control.dataset.mode=mode;modeButtons.push(control);modes.append(control);
  }
  setMode(matchMedia('(max-width:700px)').matches?'source':'split');
  const queue=createMarkdownPreview({
    compile:async(markdown,signal)=>{const result=await api('/question-markdown/preview',{method:'POST',body:JSON.stringify({markdown}),signal});if(state.token!==sessionToken)throw new Error('登录状态已变化，请重新打开编辑器');return result.html;},
    pending:()=>{preview.setAttribute('aria-busy','true');},
    show:html=>{preview.setAttribute('aria-busy','false');preview.replaceChildren();if(html)appendProblemStatement(preview,html);else preview.append(el('p','输入 Markdown 后在这里查看效果。','muted'));},
    failed:error=>{preview.setAttribute('aria-busy','false');message(`预览未更新：${error.message}，正文已保留。`,true);},
  });
  let busy=false,disposed=false;
  const setBusy=value=>{busy=value;text.readOnly=value;imageButton.disabled=value;importButton.disabled=value;onBusy(value);};
  const changed=()=>{if(!disposed)queue.update(text.value);};
  text.addEventListener('input',changed);
  const imagePicker=el('input');imagePicker.type='file';imagePicker.accept='image/png,image/jpeg,image/webp';imagePicker.hidden=true;
  const insertImages=async files=>{
    const images=[...files].filter(file=>file.type.startsWith('image/'));
    if(!images.length||busy||disposed)return;
    setBusy(true);const token=state.token;let start=text.selectionStart,end=text.selectionEnd;
    try{
      for(const [index,file]of images.entries()){
        message(`正在上传图片 ${index+1}/${images.length}…`);
        const body=new FormData();body.append('file',file);
        const result=await api('/question-markdown/images',{method:'POST',body});
        if(disposed||state.token!==token)return;
        const insertion=`\n\n![diagram](${result.url})\n`;
        if(text.maxLength>0&&text.value.length-(end-start)+insertion.length>text.maxLength)throw new Error('正文长度超出限制，请缩短后再插入图片');
        text.setRangeText(insertion,start,end,'end');start=end=text.selectionEnd;
        text.dispatchEvent(new Event('input',{bubbles:true}));
      }
      message('图片已插入正文，保存题目后生效。');
    }catch(error){if(!disposed)message(`图片上传失败：${error.message}，已输入内容保留。`,true);}
    finally{setBusy(false);}
  };
  text.addEventListener('paste',event=>{const files=[...(event.clipboardData?.files||[])].filter(file=>file.type.startsWith('image/'));if(files.length){event.preventDefault();void insertImages(files);}});
  const imageButton=button('上传图片',()=>imagePicker.click(),'button secondary');
  imagePicker.addEventListener('change',()=>{const files=[...(imagePicker.files||[])];imagePicker.value='';void insertImages(files);});
  const filePicker=el('input');filePicker.type='file';filePicker.accept='.md,text/markdown';filePicker.hidden=true;
  const importButton=button('导入 MD',()=>filePicker.click(),'button secondary');
  filePicker.addEventListener('change',async()=>{
    const file=filePicker.files?.[0];filePicker.value='';if(!file||busy)return;setBusy(true);
    try{
      const imported=await readMarkdownFile(file);
      if(disposed)return;
      if(text.maxLength>0&&imported.text.length>text.maxLength)throw new Error('文件内容超出本字段字数限制');
      if(text.value.trim()&&!await confirmAction('导入文件将替换当前字段正文，是否继续？',{title:'导入 Markdown 文件',confirmText:'导入文件'}))return;
      if(disposed)return;
      text.value=imported.text;text.dispatchEvent(new Event('input',{bubbles:true}));message('已导入 Markdown，请检查后保存题目。');
    }catch(error){if(!disposed)message(error.message,true);}finally{setBusy(false);}
  });
  const uploads=el('div','','question-md-uploads');uploads.append(imageButton,importButton,imagePicker,filePicker);
  toolbar.append(modes,uploads);shell.append(toolbar,panes,el('p','支持标题、表格、代码、公式和粘贴图片；图片随题目权限开放。','question-md-hint'),status);
  changed();
  return {node:shell,refresh:changed,get busy(){return busy;},dispose(){disposed=true;queue.dispose();}};
}
