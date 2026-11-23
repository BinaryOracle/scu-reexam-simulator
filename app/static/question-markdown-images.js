/** Load private inline illustrations with the current session rather than public URLs. */
import {state} from './api.js?v=20261122-session-guard-v1';

export function hydrateQuestionImages(root){
  for(const image of root.querySelectorAll('img')){
    const path=image.getAttribute('src');
    if(!path?.startsWith('/api/question-markdown/images/'))continue;
    image.removeAttribute('src');image.decoding='async';
    const token=state.token;
    const unavailable=()=>{if(root.contains(image))image.replaceWith(Object.assign(document.createElement('span'),{textContent:'图片暂不可用，请刷新后重试',className:'question-image-unavailable'}));};
    if(!/^\/api\/question-markdown\/images\/[a-f0-9]{32}$/.test(path)){unavailable();continue;}
    fetch(path,{headers:{Authorization:`Bearer ${token}`}}).then(response=>{
      if(!response.ok)throw new Error('图片读取失败');return response.blob();
    }).then(async blob=>{
      if(!root.contains(image)||state.token!==token)return;
      const url=URL.createObjectURL(blob);image.src=url;
      try{await image.decode();}catch(error){unavailable();}finally{URL.revokeObjectURL(url);}
    }).catch(unavailable);
  }
}
