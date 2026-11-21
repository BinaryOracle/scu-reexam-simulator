/** Debounce Markdown compilation and discard responses from superseded edits. */
export function createMarkdownPreview({compile,show,pending,failed,delay=350}) {
  let timer=null,revision=0,controller=null,disposed=false;
  return {
    update(source){
      if(disposed)return;
      const turn=++revision;clearTimeout(timer);controller?.abort();controller=null;
      if(!source.trim()){show('');return;}
      pending();
      timer=setTimeout(async()=>{
        const request=new AbortController();controller=request;
        try{const html=await compile(source,request.signal);if(!disposed&&turn===revision)show(html);}
        catch(error){if(!disposed&&turn===revision)failed(error);}
        finally{if(controller===request)controller=null;}
      },delay);
    },
    dispose(){disposed=true;revision++;clearTimeout(timer);controller?.abort();},
  };
}
/** Decode a UTF-8 Markdown file without replacing the editor on invalid input. */
export async function readMarkdownFile(file) {
  if(!/\.md$/i.test(file.name))throw new Error('请选择 .md 格式的 Markdown 文件');
  let text;
  try{text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());}
  catch(error){throw new Error('文件无法读取，请将 Markdown 保存为 UTF-8 编码后重新导入');}
  if(text.includes('\0'))throw new Error('文件不是有效的 Markdown 文本');
  return {name:file.name.replace(/\.md$/i,''),text};
}
